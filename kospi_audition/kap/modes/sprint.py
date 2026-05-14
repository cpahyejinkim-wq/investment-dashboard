"""Sprint Mode score per PRD section 2.4 (Stage 1 MVP).

Sprint Score = 0.35*RS20 + 0.20*RS60 + 0.05*RS120
             + 0.20*Acceleration + 0.10*RankVelocity
             + 0.05*Volume + 0.05*Flow

Volume and Flow factors are not implemented in Stage 1; their percentile is
treated as a neutral 50 so the weights still sum to 1.0. Stage 2 will replace
those neutrals with the real values.
"""

from __future__ import annotations

import pandas as pd

from kap import config


def compute_sprint_score(
    rs: pd.DataFrame,
    acceleration: pd.DataFrame,
    rank_velocity: pd.DataFrame,
    volume: pd.DataFrame | None = None,
    flow: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine factor frames into the Sprint score.

    Each input frame must contain a ``ticker`` column. RS frame must provide
    ``rs_<n>d_pct`` columns. Acceleration provides ``acceleration_pct``.
    Rank velocity provides ``rank_velocity_pct``.
    """
    if rs.empty:
        return pd.DataFrame()

    weights = config.MODES["sprint"]["weights"]
    base = rs.copy()
    base = base.merge(acceleration[["ticker", "acceleration_pct"]], on="ticker", how="left")
    base = base.merge(
        rank_velocity[["ticker", "rank_velocity_pct"]], on="ticker", how="left"
    )

    if volume is not None and not volume.empty:
        base = base.merge(volume[["ticker", "volume_pct"]], on="ticker", how="left")
    else:
        base["volume_pct"] = 50.0
    if flow is not None and not flow.empty:
        base = base.merge(flow[["ticker", "flow_pct"]], on="ticker", how="left")
    else:
        base["flow_pct"] = 50.0

    # Fill missing percentiles with neutral 50 so scores remain comparable.
    pct_cols = [
        "rs_20d_pct", "rs_60d_pct", "rs_120d_pct",
        "acceleration_pct", "rank_velocity_pct", "volume_pct", "flow_pct",
    ]
    for c in pct_cols:
        if c not in base.columns:
            base[c] = 50.0
        base[c] = base[c].fillna(50.0)

    base["sprint_score"] = (
        weights["rs_20d"] * base["rs_20d_pct"]
        + weights["rs_60d"] * base["rs_60d_pct"]
        + weights["rs_120d"] * base["rs_120d_pct"]
        + weights["acceleration"] * base["acceleration_pct"]
        + weights["rank_velocity"] * base["rank_velocity_pct"]
        + weights["volume"] * base["volume_pct"]
        + weights["flow"] * base["flow_pct"]
    )
    base["sprint_score_pct"] = base["sprint_score"].rank(pct=True, method="average") * 100.0
    return base
