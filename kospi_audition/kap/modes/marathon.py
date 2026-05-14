"""Marathon Mode score per PRD section 2.4.

Marathon_Score = 0.10*RS20 + 0.20*RS60 + 0.20*RS120 + 0.15*RS252
               + 0.05*Acceleration + 0.05*RankVelocity
               + 0.10*Volume + 0.10*Flow + 0.05*EarningsDrift
"""

from __future__ import annotations

import pandas as pd

from kap import config


def compute_marathon_score(
    rs: pd.DataFrame,
    acceleration: pd.DataFrame,
    rank_velocity: pd.DataFrame,
    volume: pd.DataFrame | None = None,
    flow: pd.DataFrame | None = None,
    earnings_drift: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if rs.empty:
        return pd.DataFrame()
    weights = config.MODES["marathon"]["weights"]

    base = rs.copy()
    base = base.merge(acceleration[["ticker", "acceleration_pct"]], on="ticker", how="left")
    base = base.merge(rank_velocity[["ticker", "rank_velocity_pct"]], on="ticker", how="left")
    if volume is not None and not volume.empty:
        base = base.merge(volume[["ticker", "volume_pct"]], on="ticker", how="left")
    else:
        base["volume_pct"] = 50.0
    if flow is not None and not flow.empty:
        base = base.merge(flow[["ticker", "flow_pct"]], on="ticker", how="left")
    else:
        base["flow_pct"] = 50.0
    if earnings_drift is not None and not earnings_drift.empty:
        base = base.merge(
            earnings_drift[["ticker", "earnings_drift_pct"]], on="ticker", how="left"
        )
    else:
        base["earnings_drift_pct"] = 50.0

    pct_cols = [
        "rs_20d_pct", "rs_60d_pct", "rs_120d_pct", "rs_252d_pct",
        "acceleration_pct", "rank_velocity_pct",
        "volume_pct", "flow_pct", "earnings_drift_pct",
    ]
    for c in pct_cols:
        if c not in base.columns:
            base[c] = 50.0
        base[c] = base[c].fillna(50.0)

    base["marathon_score"] = (
        weights["rs_20d"] * base["rs_20d_pct"]
        + weights["rs_60d"] * base["rs_60d_pct"]
        + weights["rs_120d"] * base["rs_120d_pct"]
        + weights["rs_252d"] * base["rs_252d_pct"]
        + weights["acceleration"] * base["acceleration_pct"]
        + weights["rank_velocity"] * base["rank_velocity_pct"]
        + weights["volume"] * base["volume_pct"]
        + weights["flow"] * base["flow_pct"]
        + weights["earnings_drift"] * base["earnings_drift_pct"]
    )
    base["marathon_score_pct"] = base["marathon_score"].rank(pct=True, method="average") * 100.0
    return base
