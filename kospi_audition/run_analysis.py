"""End-to-end Stage 1 MVP runner for KOSPI Audition Pyramid v2.1.

Usage:
    python run_analysis.py [--days 400] [--mode sprint]

Stage 1 wires the following pipeline:
    1. Data Collector  (pykrx -> parquet, or synthetic fallback)
    2. Universe Filter
    3. Regime Filter   (-> regime_data.json)
    4. RS / Acceleration / Rank Velocity factors
    5. Sprint Mode Score
    6. Tier classification + mode-aware weights
    7. Mode-aware stop loss
    8. JSON export     (-> ranking_sprint.json, risk_alerts.json, new_leaders.json)
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
from kap.factors import acceleration as accel_mod
from kap.factors import rank_velocity as rv_mod
from kap.factors import rs as rs_mod
from kap.logging_setup import configure_logging
from kap.modes import sprint as sprint_mode
from kap.ranking import tier as tier_mod
from kap.regime import compute_regime
from kap.risk import stops as stops_mod


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=400)
    p.add_argument("--mode", choices=["sprint", "marathon"], default="sprint")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def _build_score_history(
    ohlcv: pd.DataFrame, bench: pd.Series, n_days: int = 10
) -> pd.DataFrame:
    """Build a date-indexed score-rank history for rank-velocity calculation.

    A simple proxy is used here: the 20-day RS percentile reverse-ranked daily.
    Stage 2 will replace this with the actual daily Sprint score recomputation.
    """
    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot_table(index="date", columns="ticker", values="close").sort_index()
    bench = bench.copy()
    bench.index = pd.to_datetime(bench.index)

    history_dates = wide.index[-n_days:]
    rows: dict[pd.Timestamp, pd.Series] = {}
    window = 20
    for d in history_dates:
        if d not in bench.index:
            continue
        idx_d = wide.index.get_indexer([d])[0]
        if idx_d < window:
            continue
        past = wide.index[idx_d - window]
        if past not in bench.index:
            continue
        p_now = wide.loc[d]
        p_past = wide.loc[past]
        b_now = float(bench.loc[d])
        b_past = float(bench.loc[past])
        if b_past == 0:
            continue
        rs = (p_now / p_past) / (b_now / b_past) - 1.0
        rows[d] = rs

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).T.sort_index()


def main() -> None:
    args = _parse_args()
    configure_logging(args.log_level)
    started = time.time()
    logger.info("=== Stage 1 MVP run started ===  mode={}", args.mode)

    end = _dt.date.today()
    start = end - _dt.timedelta(days=args.days)
    window = collector.CollectionWindow(start=start, end=end)
    logger.info("collection window: {} -> {}", window.start, window.end)

    ohlcv = collector.fetch_ohlcv(window)
    if ohlcv.empty:
        logger.error("no OHLCV data available - aborting")
        return
    collector.save_parquet(ohlcv, "ohlcv")

    index_df = collector.fetch_index_ohlcv(window)
    collector.save_parquet(index_df, "index_ohlcv")

    snap = universe_mod.build_universe(ohlcv)
    collector.save_parquet(snap, "universe")
    included = snap.loc[snap["included"], "ticker"].tolist()
    logger.info("universe size: {}", len(included))

    ohlcv_uni = ohlcv[ohlcv["ticker"].isin(included)].copy()

    # Benchmark = KOSPI close indexed by date.
    kospi = index_df[index_df["index_name"] == "KOSPI"].set_index(
        pd.to_datetime(index_df[index_df["index_name"] == "KOSPI"]["date"])
    )["close"]
    kospi = kospi.sort_index()

    regime = compute_regime(index_df=index_df, market_ohlcv=ohlcv)
    json_writer.write_regime(regime.as_dict())
    logger.info(
        "regime: score={} state={} recommended_mode={}",
        regime.score,
        regime.state,
        regime.recommended_mode,
    )

    rs_df = rs_mod.compute_rs(ohlcv_uni, kospi)
    accel_df = accel_mod.compute_acceleration(ohlcv_uni, kospi)
    score_hist = _build_score_history(ohlcv_uni, kospi, n_days=10)
    rv_df = rv_mod.compute_rank_velocity(score_hist)
    logger.info(
        "factors built: rs={} accel={} rv={}", len(rs_df), len(accel_df), len(rv_df)
    )

    if args.mode == "sprint":
        scored = sprint_mode.compute_sprint_score(rs_df, accel_df, rv_df)
        score_pct_col = "sprint_score_pct"
        score_col = "sprint_score"
    else:
        logger.warning("Stage 1 does not implement marathon yet - falling back to sprint")
        scored = sprint_mode.compute_sprint_score(rs_df, accel_df, rv_df)
        score_pct_col = "sprint_score_pct"
        score_col = "sprint_score"

    tiered = tier_mod.assign_tiers(scored, mode=args.mode, score_pct_col=score_pct_col)
    tiered = tier_mod.assign_weights(
        tiered,
        mode=args.mode,
        regime_multiplier=regime.weight_multiplier,
        allowed_tiers=regime.allowed_tiers,
    )

    # Enrich with current price / market for stop calc.
    meta = (
        snap[["ticker", "market", "last_close"]]
        .rename(columns={"last_close": "current_price"})
    )
    tiered = tiered.merge(meta, on="ticker", how="left")
    tiered = stops_mod.attach_stops(tiered, mode=args.mode)

    # Mode-specific score aliasing for downstream consumers.
    tiered["mode"] = args.mode
    tiered["mode_score"] = tiered[score_col]
    tiered["mode_score_pct"] = tiered[score_pct_col]

    # Order output: investable tiers first, then by score.
    tier_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
    tiered["_tier_order"] = tiered["tier"].map(tier_order).fillna(5)
    tiered = tiered.sort_values(["_tier_order", score_pct_col], ascending=[True, False])
    tiered = tiered.drop(columns=["_tier_order"])

    as_of = regime.as_of.isoformat()
    json_writer.write_ranking(
        tiered, mode=args.mode, as_of=as_of, universe_size=len(included)
    )

    risk_alerts = stops_mod.build_risk_alerts(
        tiered[tiered["tier"].isin(["S", "A", "B"])], mode=args.mode
    )
    json_writer.write_risk_alerts(risk_alerts, as_of=as_of)

    new_leaders = _select_new_leaders(tiered, rv_df, accel_df)
    json_writer.write_new_leaders(new_leaders, as_of=as_of)

    elapsed = time.time() - started
    logger.info("=== Stage 1 MVP done in {:.1f}s ===", elapsed)


def _select_new_leaders(
    tiered: pd.DataFrame, rv: pd.DataFrame, accel: pd.DataFrame
) -> pd.DataFrame:
    if tiered.empty or rv.empty:
        return pd.DataFrame()
    merged = tiered.merge(
        rv[["ticker", "rank_velocity_5d", "rank_today", "rank_past"]],
        on="ticker",
        how="left",
    )
    merged = merged.merge(accel[["ticker", "acceleration_pct"]], on="ticker", how="left", suffixes=("", "_a"))
    candidates = merged[
        (merged["rank_velocity_5d"].fillna(0) >= 100)
        & (merged["rank_today"].fillna(9999) <= 200)
    ].copy()
    candidates = candidates.sort_values("rank_velocity_5d", ascending=False).head(20)
    keep = [
        "ticker",
        "tier",
        "rank_velocity_5d",
        "rank_today",
        "rank_past",
        "acceleration_pct",
        "mode_score",
    ]
    for c in keep:
        if c not in candidates.columns:
            candidates[c] = None
    return candidates[keep]


if __name__ == "__main__":
    main()
