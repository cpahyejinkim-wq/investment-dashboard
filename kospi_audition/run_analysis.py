"""End-to-end runner for KOSPI Audition Pyramid v2.1 (Stages 1 + 2).

Stage 1 wired:
    Regime -> RS/Accel/RankVel -> Sprint score -> Tier+Weight -> Stops -> JSON
Stage 2 wired:
    + Volume + Flow + Marathon score
    + Mode Comparison
    + Entry signals (Breakout / VCP / Pullback)
    + Sector cap + Correlation cluster
    + Soft Migration position book
"""

from __future__ import annotations

import argparse
import datetime as _dt
import time

import pandas as pd
from loguru import logger

from kap import config
from kap.data import collector, universe as universe_mod
from kap.export import json_writer
from kap.factors import (
    acceleration as accel_mod,
    flow as flow_mod,
    rank_velocity as rv_mod,
    rs as rs_mod,
    volume as volume_mod,
)
from kap.logging_setup import configure_logging
from kap.backtest import engine as bt_engine
from kap.backtest import walk_forward as wf_mod
from kap.data import fundamentals as fund_mod
from kap.factors import earnings as earnings_mod
from kap.factors import quality as quality_mod
from kap.modes import marathon as marathon_mode
from kap.modes import sprint as sprint_mode
from kap.ops import notify as notify_mod
from kap.ops import paper_trading as paper_mod
from kap.ops import regime_history as hist_mod
from kap.ops.retry import retry
from kap.portfolio import positions as positions_mod
from kap.portfolio import vol_weight as vol_weight_mod
from kap.ranking import leader_score as leader_mod
from kap.ranking import mode_compare, sector_power as sector_power_mod, tier as tier_mod
from kap.regime import compute_regime
from kap.risk import entry_signal as entry_mod
from kap.risk import sector_cap as sector_mod
from kap.risk import stops as stops_mod


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=400)
    p.add_argument("--mode", choices=["sprint", "marathon"], default=None,
                   help="Active mode for Soft Migration (default: regime recommendation)")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--with-backtest", action="store_true",
                   help="Also run Stage 3 backtest (slow)")
    p.add_argument("--with-walk-forward", action="store_true",
                   help="Also run Stage 3 walk-forward harness (very slow)")
    p.add_argument("--paper-trading", action="store_true",
                   help="Stage 4: update paper-trading state (output/paper_trading.json)")
    p.add_argument("--notify", action="store_true",
                   help="Stage 4: dispatch Slack/Email alerts based on env vars")
    return p.parse_args()


def _kospi_series(index_df: pd.DataFrame) -> pd.Series:
    s = index_df[index_df["index_name"] == "KOSPI"].copy()
    s["date"] = pd.to_datetime(s["date"])
    return s.set_index("date")["close"].sort_index()


def _build_score_history(ohlcv: pd.DataFrame, bench: pd.Series, n_days: int = 10) -> pd.DataFrame:
    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot_table(index="date", columns="ticker", values="close").sort_index()
    bench = bench.copy()
    bench.index = pd.to_datetime(bench.index)
    rows: dict[pd.Timestamp, pd.Series] = {}
    window = 20
    for d in wide.index[-n_days:]:
        if d not in bench.index:
            continue
        idx = wide.index.get_indexer([d])[0]
        if idx < window:
            continue
        past = wide.index[idx - window]
        if past not in bench.index:
            continue
        b_now = float(bench.loc[d])
        b_past = float(bench.loc[past])
        if b_past == 0:
            continue
        rs = (wide.loc[d] / wide.loc[past]) / (b_now / b_past) - 1.0
        rows[d] = rs
    return pd.DataFrame(rows).T.sort_index() if rows else pd.DataFrame()


def _build_ranking(
    scored: pd.DataFrame,
    mode: str,
    score_col: str,
    score_pct_col: str,
    snap: pd.DataFrame,
    ohlcv: pd.DataFrame,
    entry_signals: pd.DataFrame,
    regime_multiplier: float,
    allowed_tiers: list[str],
) -> pd.DataFrame:
    tiered = tier_mod.assign_tiers(scored, mode=mode, score_pct_col=score_pct_col)
    tiered = tier_mod.assign_weights(
        tiered,
        mode=mode,
        regime_multiplier=regime_multiplier,
        allowed_tiers=allowed_tiers,
    )
    meta = snap[["ticker", "market", "last_close"]].rename(columns={"last_close": "current_price"})
    tiered = tiered.merge(meta, on="ticker", how="left")
    tiered = stops_mod.attach_stops(tiered, mode=mode)

    # Synthetic sector assignment (KOSPI/KOSDAQ market is used as a stand-in
    # until DART/GICS data is wired in Stage 3). Use first digit of ticker as
    # a deterministic synthetic "sector" so the cap logic exercises real groups.
    tiered["sector"] = tiered["ticker"].str[:1]

    investable_mask = tiered["tier"].isin(["S", "A", "B", "C"])
    investable = tiered[investable_mask].copy()
    if not investable.empty:
        investable = sector_mod.enforce_sector_cap(investable)
        investable = sector_mod.apply_correlation_cap(investable, ohlcv)
        tiered.loc[investable.index, "weight"] = investable["weight"].values

    if not entry_signals.empty:
        tiered = tiered.merge(entry_signals, on="ticker", how="left")
    else:
        tiered["entry_signal"] = None
        tiered["entry_signal_date"] = None

    tiered["mode"] = mode
    tiered["mode_score"] = tiered[score_col]
    tiered["mode_score_pct"] = tiered[score_pct_col]

    tier_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
    tiered["_t"] = tiered["tier"].map(tier_order).fillna(5)
    tiered = tiered.sort_values(["_t", score_pct_col], ascending=[True, False]).drop(columns="_t")
    return tiered


def _select_new_leaders(tiered: pd.DataFrame, rv: pd.DataFrame, accel: pd.DataFrame) -> pd.DataFrame:
    if tiered.empty or rv.empty:
        return pd.DataFrame()
    merged = tiered.merge(rv[["ticker", "rank_velocity_5d", "rank_today", "rank_past"]],
                          on="ticker", how="left")
    merged = merged.merge(accel[["ticker", "acceleration_pct"]], on="ticker", how="left",
                          suffixes=("", "_a"))
    candidates = merged[
        (merged["rank_velocity_5d"].fillna(0) >= 100)
        & (merged["rank_today"].fillna(9999) <= 200)
    ].sort_values("rank_velocity_5d", ascending=False).head(20)
    keep = ["ticker", "tier", "rank_velocity_5d", "rank_today", "rank_past",
            "acceleration_pct", "mode_score"]
    for c in keep:
        if c not in candidates.columns:
            candidates[c] = None
    return candidates[keep]


def main() -> None:
    args = _parse_args()
    configure_logging(args.log_level)
    started = time.time()
    logger.info("=== Stage 1+2 run started ===")

    end = _dt.date.today()
    start = end - _dt.timedelta(days=args.days)
    win = collector.CollectionWindow(start=start, end=end)

    ohlcv = _retry_collect_ohlcv(win)
    if ohlcv.empty:
        logger.error("no OHLCV - aborting")
        return
    collector.save_parquet(ohlcv, "ohlcv")
    index_df = _retry_collect_index(win)
    collector.save_parquet(index_df, "index_ohlcv")

    snap = universe_mod.build_universe(ohlcv)
    collector.save_parquet(snap, "universe")
    included = snap.loc[snap["included"], "ticker"].tolist()
    ohlcv_uni = ohlcv[ohlcv["ticker"].isin(included)].copy()
    kospi = _kospi_series(index_df)

    regime = compute_regime(index_df=index_df, market_ohlcv=ohlcv)
    json_writer.write_regime(regime.as_dict())
    logger.info("regime: state={} rec_mode={}", regime.state, regime.recommended_mode)

    active_mode = args.mode or (
        regime.recommended_mode if regime.recommended_mode in ("sprint", "marathon") else "sprint"
    )
    logger.info("active mode: {}", active_mode)

    # ---- Factors ----------------------------------------------------------
    rs_df = rs_mod.compute_rs(ohlcv_uni, kospi)
    accel_df = accel_mod.compute_acceleration(ohlcv_uni, kospi)
    rv_df = rv_mod.compute_rank_velocity(_build_score_history(ohlcv_uni, kospi))
    volume_df = volume_mod.compute_volume_score(ohlcv_uni)
    flow_raw = flow_mod.synthetic_flow(ohlcv_uni)
    flow_df = flow_mod.compute_flow_score(flow_raw)
    entry_df = entry_mod.compute_entry_signals(ohlcv_uni)

    # Stage 3 fundamentals + PEAD
    fund_df = fund_mod.fetch_fundamentals(included, end=end)
    quality_df = quality_mod.evaluate_quality(fund_df)
    earnings_df = earnings_mod.compute_earnings_drift(ohlcv_uni, kospi, fund_df)

    logger.info(
        "factors: rs={} accel={} rv={} vol={} flow={} entry={} qual={} pead={}",
        len(rs_df), len(accel_df), len(rv_df), len(volume_df), len(flow_df),
        len(entry_df), len(quality_df), len(earnings_df),
    )

    # ---- Mode scores ------------------------------------------------------
    sprint_scored = sprint_mode.compute_sprint_score(
        rs_df, accel_df, rv_df, volume=volume_df, flow=flow_df,
    )
    marathon_scored = marathon_mode.compute_marathon_score(
        rs_df, accel_df, rv_df, volume=volume_df, flow=flow_df,
        earnings_drift=earnings_df,
    )

    sprint_ranked = _build_ranking(
        sprint_scored, "sprint", "sprint_score", "sprint_score_pct",
        snap, ohlcv_uni, entry_df,
        regime.weight_multiplier, regime.allowed_tiers,
    )
    marathon_ranked = _build_ranking(
        marathon_scored, "marathon", "marathon_score", "marathon_score_pct",
        snap, ohlcv_uni, entry_df,
        regime.weight_multiplier, regime.allowed_tiers,
    )

    # Stage 3: Quality Gate (may demote S/A -> B), Leader Score, Vol-Adjusted Weight
    sprint_ranked = quality_mod.apply_quality_gate(sprint_ranked, quality_df, mode="sprint")
    marathon_ranked = quality_mod.apply_quality_gate(marathon_ranked, quality_df, mode="marathon")

    sprint_ranked = leader_mod.compute_leader_score(sprint_ranked)
    marathon_ranked = leader_mod.compute_leader_score(marathon_ranked)

    sprint_ranked = vol_weight_mod.adjust_weights(sprint_ranked, ohlcv_uni)
    marathon_ranked = vol_weight_mod.adjust_weights(marathon_ranked, ohlcv_uni)

    as_of = regime.as_of.isoformat()
    json_writer.write_ranking(sprint_ranked, "sprint", as_of, len(included))
    json_writer.write_ranking(marathon_ranked, "marathon", as_of, len(included))

    # Stage 3: Sector Power Score
    active_for_sectors = sprint_ranked if active_mode == "sprint" else marathon_ranked
    sector_power_df = sector_power_mod.compute_sector_power(active_for_sectors, ohlcv_uni)
    top_tickers = sector_power_mod.top_tickers_per_sector(active_for_sectors)
    json_writer.write_sector_power(sector_power_df, top_tickers, as_of=as_of)

    # ---- Mode Comparison --------------------------------------------------
    investable = ["S", "A", "B"]
    sprint_top = sprint_ranked[sprint_ranked["tier"].isin(investable)]
    marathon_top = marathon_ranked[marathon_ranked["tier"].isin(investable)]
    compare = mode_compare.compare_modes(sprint_top, marathon_top, top_n=10)
    json_writer.write_mode_compare(compare, as_of=as_of)
    logger.info(
        "mode compare: overlap={:.0%} health={}", compare["overlap_ratio"], compare["health"]
    )

    # ---- Risk alerts ------------------------------------------------------
    active_ranked = sprint_ranked if active_mode == "sprint" else marathon_ranked
    risk_alerts = stops_mod.build_risk_alerts(
        active_ranked[active_ranked["tier"].isin(["S", "A", "B"])], mode=active_mode
    )
    json_writer.write_risk_alerts(risk_alerts, as_of=as_of)

    # ---- New leaders ------------------------------------------------------
    leaders = _select_new_leaders(active_ranked, rv_df, accel_df)
    json_writer.write_new_leaders(leaders, as_of=as_of)

    # ---- Soft Migration position book ------------------------------------
    book = positions_mod.load_positions()
    book, events = positions_mod.reconcile(
        book,
        active_ranked,
        active_mode=active_mode,
        regime_state=regime.state,
        today=regime.as_of,
        allowed_tiers=regime.allowed_tiers,
    )
    migrated = positions_mod.soft_migration_check(book, active_mode)
    if migrated:
        events.append({
            "type": "soft_migration_notice",
            "active_mode": active_mode,
            "count": len(migrated),
            "tickers": [p["ticker"] for p in migrated[:10]],
        })
    positions_mod.save_positions(book, as_of=as_of)
    json_writer.write_positions(book, events, as_of=as_of)

    # ---- Stage 3 backtest (opt-in) ---------------------------------------
    if args.with_backtest or args.with_walk_forward:
        index_df_full = index_df.copy()
        ohlcv_full = ohlcv_uni.copy()
        results = bt_engine.run_all(ohlcv_full, index_df_full)
        metrics_payload = {
            name: res.metrics(
                config.BACKTEST["commission_pct"], config.BACKTEST["slippage_pct"]
            )
            for name, res in results.items()
        }
        if args.with_walk_forward:
            metrics_payload["walk_forward"] = wf_mod.run_walk_forward(ohlcv_full, index_df_full)
            metrics_payload["oos"] = wf_mod.run_oos(ohlcv_full, index_df_full)
        json_writer.write_backtest(metrics_payload, as_of=as_of)
        logger.info("backtest written ({} strategies)", len(results))

    logger.info("=== Stage 1+2+3 done in {:.1f}s ===", time.time() - started)

    # ---- Stage 4: paper trading + notifications + history ----------------
    if args.paper_trading:
        state = paper_mod.load_state()
        state = paper_mod.rebalance(
            state, active_ranked, active_mode, as_of, regime.allowed_tiers
        )
        paper_mod.save_state(state)
        last_nav = state["nav_history"][-1]["nav"] if state["nav_history"] else 0.0
        logger.info("paper trading NAV @ {} = {:,.0f}", as_of, last_nav)

    hist_state = hist_mod.load()
    hist_new, prev_regime, mismatch_streak = hist_mod.update(
        hist_state, regime.as_of, regime.state, active_mode, regime.recommended_mode,
    )
    hist_mod.save(hist_new)

    if args.notify:
        channels = notify_mod.AlertChannels.from_env()
        msgs: list[str] = []
        m = notify_mod.build_risk_alert_message(risk_alerts)
        if m:
            msgs.append(m)
        m = notify_mod.build_regime_change_message(prev_regime, regime.state, regime.recommended_mode)
        if m:
            msgs.append(m)
        m = notify_mod.build_mode_mismatch_message(active_mode, regime.recommended_mode, mismatch_streak)
        if m:
            msgs.append(m)
        if msgs:
            notify_mod.dispatch("\n\n".join(msgs), subject=f"[KAP] {regime.as_of}", channels=channels)


# Wrapped data fetch with exponential back-off retries (Stage 4 4-4).
_retry_collect_ohlcv = retry(attempts=3, initial_delay=2.0)(collector.fetch_ohlcv)
_retry_collect_index = retry(attempts=3, initial_delay=2.0)(collector.fetch_index_ohlcv)


if __name__ == "__main__":
    main()
