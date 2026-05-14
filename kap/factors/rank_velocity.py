"""Rank Velocity (PRD §6.3) — NEW v2.1.

Daily rank-change of the mode-specific score. Catches early leaders before
they hit the upper tiers. Only meaningful for tickers already inside rank 200
to avoid noise from rank 3000 → 2800 moves.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

RANK_FLOOR = 200
WINDOW_DAYS = 5


def _percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def compute_rank_velocity(
    score_history: pd.DataFrame, window: int = WINDOW_DAYS, rank_floor: int = RANK_FLOOR
) -> pd.DataFrame:
    """Given a long-format DataFrame [ticker, date, score], return rank velocity.

    Output columns: ticker, rank_today, rank_window_ago, rank_velocity, rank_velocity_pct.
    Tickers ranked worse than `rank_floor` on BOTH dates are excluded from
    percentile computation (set to NaN) per PRD §6.3.
    """
    if score_history.empty:
        return pd.DataFrame(columns=["ticker", "rank_today", "rank_window_ago",
                                      "rank_velocity", "rank_velocity_pct"])
    df = score_history.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["rank"] = df.groupby("date")["score"].rank(ascending=False, method="min")
    pivot = df.pivot(index="date", columns="ticker", values="rank").sort_index()

    if len(pivot) <= window:
        # Fall back: zero velocity if not enough history yet
        last = pivot.iloc[-1]
        out = pd.DataFrame({
            "ticker": last.index,
            "rank_today": last.values,
            "rank_window_ago": last.values,
            "rank_velocity": 0.0,
            "rank_velocity_pct": 50.0,
        })
        return out.reset_index(drop=True)

    rank_today = pivot.iloc[-1]
    rank_past = pivot.iloc[-1 - window]
    velocity = rank_past - rank_today  # higher = climbed in rank

    eligible = (rank_today <= rank_floor) | (rank_past <= rank_floor)
    v_eligible = velocity.where(eligible)
    v_pct = _percentile_rank(v_eligible).fillna(50.0)

    out = pd.DataFrame({
        "ticker": velocity.index,
        "rank_today": rank_today.values,
        "rank_window_ago": rank_past.values,
        "rank_velocity": velocity.values,
        "rank_velocity_pct": v_pct.values,
    }).reset_index(drop=True)
    logger.info("Rank velocity computed for {} tickers (eligible: {})", len(out), int(eligible.sum()))
    return out
