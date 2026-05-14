"""Marathon Mode Score (PRD §2.4, §14).

Marathon_Score = RS_20d*0.10 + RS_60d*0.20 + RS_120d*0.20 + RS_252d*0.15
               + Acceleration*0.05 + RankVelocity*0.05
               + Volume*0.10 + Flow*0.10 + EarningsDrift*0.05
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from kap.config import MODES


def _percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def compute_marathon_score(factors: pd.DataFrame) -> pd.DataFrame:
    w = MODES["marathon"]["weights"]
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
    for f, weight in w.items():
        col = col_map[f]
        if col not in df.columns:
            logger.warning("Marathon: missing column {} — skipping (will reweight)", col)
            continue
        score = score + df[col].fillna(50.0) * weight
        weight_sum += weight
    if weight_sum > 0 and weight_sum != 1.0:
        score = score / weight_sum
    df["marathon_score"] = score
    df["marathon_score_pct"] = _percentile_rank(score)
    logger.info("Marathon score computed for {} tickers (weight sum={:.2f})", len(df), weight_sum)
    return df
