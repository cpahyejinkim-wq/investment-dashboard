"""Leader Score (PRD §6.8) — NEW v2.1.

Display-only indicator combining mode score with weighted survival days.
"""

from __future__ import annotations

import pandas as pd


def _percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def survival_weight(s_days: int = 0, a_days: int = 0, b_days: int = 0) -> int:
    return s_days * 3 + a_days * 2 + b_days * 1


def compute_leader_score(
    df: pd.DataFrame,
    mode_score_pct_col: str,
    survival_weighted_col: str = "survival_weighted",
) -> pd.Series:
    """Leader = mode_score_pct × 0.7 + survival_weighted_pct × 0.3."""
    sw_pct = _percentile_rank(df[survival_weighted_col].astype(float))
    return df[mode_score_pct_col].fillna(50.0) * 0.7 + sw_pct.fillna(50.0) * 0.3
