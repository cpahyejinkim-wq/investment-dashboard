"""Sprint Mode Score (PRD §2.4, §14).

Sprint_Score = RS_20d*0.35 + RS_60d*0.20 + RS_120d*0.05
             + Acceleration*0.20 + RankVelocity*0.10
             + Volume*0.05 + Flow*0.05

Re-normalized cross-sectionally to percentile.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from kap.config import MODES


def _percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def compute_sprint_score(factors: pd.DataFrame) -> pd.DataFrame:
    """`factors` must contain *_pct columns for each weighted factor."""
    w = MODES["sprint"]["weights"]
    needed = list(w.keys())
    col_map = {
        "rs_20d": "rs_20d_pct",
        "rs_60d": "rs_60d_pct",
        "rs_120d": "rs_120d_pct",
        "rs_252d": "rs_252d_pct",
        "acceleration": "acceleration_pct",
        "rank_velocity": "rank_velocity_pct",
        "volume": "volume_pct",
        "flow": "flow_pct",
        "earnings_drift": "earnings_drift_pct",
    }
    df = factors.copy()
    score = pd.Series(0.0, index=df.index)
    weight_sum = 0.0
    for f in needed:
        col = col_map[f]
        if col not in df.columns:
            logger.warning("Sprint: missing column {} — skipping (will reweight)", col)
            continue
        score = score + df[col].fillna(50.0) * w[f]
        weight_sum += w[f]
    if weight_sum > 0 and weight_sum != 1.0:
        score = score / weight_sum
    df["sprint_score"] = score
    df["sprint_score_pct"] = _percentile_rank(score)
    logger.info("Sprint score computed for {} tickers (weight sum={:.2f})", len(df), weight_sum)
    return df
