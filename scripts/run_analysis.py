"""End-to-end analysis pipeline (PRD §13.1 step 1-13).

Collects data → computes regime → factors → Sprint score → tiers/weights →
risk stops → JSON exports → dashboard data.

Stage 1 covers Sprint Mode end-to-end with Marathon stubbed. Stage 2 will
fully wire Marathon and the toggle.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

# Ensure repo root is on sys.path when running as a script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kap.config import MODES, OUTPUT_DIR
from kap.data.collector import collect, write_parquet
from kap.data.universe import build_universe
from kap.regime.filter import compute_regime
from kap.factors.rs import compute_rs
from kap.factors.acceleration import compute_acceleration
from kap.factors.rank_velocity import compute_rank_velocity
from kap.factors.volume import compute_volume
from kap.factors.flow import compute_flow
from kap.modes.sprint import compute_sprint_score
from kap.modes.marathon import compute_marathon_score
from kap.ranking.tier import classify_tier, apply_tier_caps, assign_weights
from kap.ranking.leader_score import compute_leader_score
from kap.risk.stop_loss import compute_initial_stops_for_candidates
from kap.export.json_export import (
    export_regime, export_ranking, export_new_leaders,
    export_sector_summary, export_risk_alerts,
)


def _build_score_history_for_rank_velocity(
    ohlcv: pd.DataFrame, index_df: pd.DataFrame, universe: pd.DataFrame, mode: str, lookback_days: int = 10
) -> pd.DataFrame:
    """Build a short score history by snapshotting Sprint score over the last `lookback_days`
    business days. Enables Rank Velocity for the *current* day's snapshot."""
    history_rows = []
    tickers = set(universe["ticker"])
    dates_avail = sorted(ohlcv["date"].unique())
    snapshot_dates = dates_avail[-(lookback_days + 1):]

    for snap_d in snapshot_dates:
        sub_ohlcv = ohlcv[ohlcv["date"] <= snap_d]
        sub_index = index_df[index_df["date"] <= snap_d]
        if len(sub_index) < 252:
            continue
        rs_df = compute_rs(sub_ohlcv, sub_index, universe)
        try:
            accel_df = compute_acceleration(sub_ohlcv, sub_index, universe)
        except ValueError:
            continue
        # Lightweight Sprint score (use available factors; missing → percentile 50)
        df = rs_df.merge(accel_df, on="ticker", how="outer")
        df["volume_pct"] = 50.0
        df["flow_pct"] = 50.0
        df["rank_velocity_pct"] = 50.0
        scored = compute_sprint_score(df)
        for _, r in scored.iterrows():
            history_rows.append({
                "ticker": r["ticker"],
                "date": snap_d,
                "score": float(r["sprint_score"]),
            })
    return pd.DataFrame(history_rows)


def run() -> None:
    t_start = time.time()
    logger.info("=== KAP v2.1 analysis pipeline starting ===")

    # 1. Data collection
    result = collect()
    write_parquet(result)
    ohlcv, flow_df, index_df, metadata = result.ohlcv, result.flow, result.index, result.metadata
    as_of = pd.Timestamp(ohlcv["date"].max())
    logger.info("Data as_of={}, source={}", as_of.strftime("%Y-%m-%d"), result.source)

    # 2. Universe filter
    universe = build_universe(ohlcv, metadata, as_of=as_of)
    if universe.empty:
        logger.error("Universe is empty — cannot proceed")
        return

    # 3. Regime
    regime = compute_regime(ohlcv, index_df, as_of=as_of)

    # 4. Factors
    logger.info("Computing factors…")
    rs_df = compute_rs(ohlcv, index_df, universe)
    accel_df = compute_acceleration(ohlcv, index_df, universe)
    volume_df = compute_volume(ohlcv, universe)
    flow_score_df = compute_flow(flow_df, ohlcv, universe)

    # 5. Rank Velocity needs a short Sprint-score history → rebuild over recent days
    logger.info("Building short Sprint-score history for Rank Velocity…")
    score_history = _build_score_history_for_rank_velocity(ohlcv, index_df, universe, mode="sprint")
    rv_df = compute_rank_velocity(score_history)

    # 6. Merge factors → mode scores
    factors = (
        universe[["ticker", "name", "market", "sector", "close", "market_cap"]]
        .merge(rs_df.drop(columns=["date"]), on="ticker", how="left")
        .merge(accel_df, on="ticker", how="left")
        .merge(rv_df, on="ticker", how="left")
        .merge(volume_df, on="ticker", how="left")
        .merge(flow_score_df, on="ticker", how="left")
    )

    sprint_scored = compute_sprint_score(factors)
    marathon_scored = compute_marathon_score(factors)

    # 7. Tier classification & weight allocation — Sprint
    sprint_scored["tier"] = classify_tier(sprint_scored["sprint_score_pct"], mode="sprint")
    sprint_scored = apply_tier_caps(sprint_scored, mode="sprint", score_col="sprint_score_pct")
    sprint_scored = assign_weights(sprint_scored, mode="sprint", regime_state=regime.state)

    # Marathon
    marathon_scored["tier"] = classify_tier(marathon_scored["marathon_score_pct"], mode="marathon")
    marathon_scored = apply_tier_caps(marathon_scored, mode="marathon", score_col="marathon_score_pct")
    marathon_scored = assign_weights(marathon_scored, mode="marathon", regime_state=regime.state)

    # 8. Leader score (Stage 1 has no survival history — set 0 → still works)
    sprint_scored["survival_days"] = 0
    sprint_scored["survival_weighted"] = 0
    sprint_scored["leader_score"] = compute_leader_score(
        sprint_scored, "sprint_score_pct", "survival_weighted"
    )
    marathon_scored["survival_days"] = 0
    marathon_scored["survival_weighted"] = 0
    marathon_scored["leader_score"] = compute_leader_score(
        marathon_scored, "marathon_score_pct", "survival_weighted"
    )

    # 9. Entry-time stop levels for ranked candidates
    sprint_active = sprint_scored[sprint_scored["tier"].isin(["S", "A", "B"])].copy()
    sprint_active = compute_initial_stops_for_candidates(sprint_active, mode="sprint")
    sprint_scored = sprint_scored.merge(
        sprint_active[["ticker", "hard_stop_price", "trailing_stop_price"]],
        on="ticker", how="left",
    )
    marathon_active = marathon_scored[marathon_scored["tier"].isin(["S", "A", "B"])].copy()
    marathon_active = compute_initial_stops_for_candidates(marathon_active, mode="marathon")
    marathon_scored = marathon_scored.merge(
        marathon_active[["ticker", "hard_stop_price", "trailing_stop_price"]],
        on="ticker", how="left",
    )

    # 10. JSON exports
    export_regime(regime, current_mode=regime.recommended_mode)
    export_ranking(
        sprint_scored.sort_values("sprint_score_pct", ascending=False),
        mode="sprint", regime_state=regime.state, universe_size=len(universe),
    )
    export_ranking(
        marathon_scored.sort_values("marathon_score_pct", ascending=False),
        mode="marathon", regime_state=regime.state, universe_size=len(universe),
    )
    export_new_leaders(sprint_scored, mode="sprint")
    export_sector_summary(sprint_scored, mode="sprint")
    export_risk_alerts(pd.DataFrame())  # Stage 1: no holdings yet → no triggered stops

    elapsed = time.time() - t_start
    logger.info("=== Pipeline complete in {:.1f}s ===", elapsed)
    print(f"\nDone. Outputs in {OUTPUT_DIR}\n"
          f"  Regime: {regime.state} (score={regime.score}) → recommended: {regime.recommended_mode}\n"
          f"  Sprint candidates (S+A+B): {len(sprint_active)}\n"
          f"  Marathon candidates (S+A+B): {len(marathon_active)}\n"
          f"  Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    run()
