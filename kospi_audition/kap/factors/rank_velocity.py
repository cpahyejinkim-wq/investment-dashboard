"""Rank Velocity per PRD section 6.3.

  RankVelocity_5D = Rank_{t-5} - Rank_t  (higher = climbing the leaderboard)
  Apply only to absolute rank <= 200 today (noise filter).
"""

from __future__ import annotations

import pandas as pd

from kap import config


def compute_rank_velocity(score_history: pd.DataFrame) -> pd.DataFrame:
    """Compute rank velocity from a wide-format score history.

    Parameters
    ----------
    score_history : DataFrame with index = date, columns = ticker, values = mode score.
    """
    if score_history.empty or len(score_history) < config.RANK_VELOCITY_LOOKBACK + 1:
        return pd.DataFrame(columns=["ticker", "rank_velocity_5d", "rank_velocity_pct"])

    lookback = config.RANK_VELOCITY_LOOKBACK
    ranks = score_history.rank(axis=1, ascending=False, method="min")
    today = ranks.iloc[-1]
    past = ranks.iloc[-1 - lookback]

    velocity = (past - today).rename("rank_velocity_5d")
    out = velocity.reset_index()
    out.columns = ["ticker", "rank_velocity_5d"]
    out["rank_today"] = today.values
    out["rank_past"] = past.values

    cutoff = config.RANK_VELOCITY_RANK_CUTOFF
    masked = out["rank_velocity_5d"].where(out["rank_today"] <= cutoff)
    out["rank_velocity_pct"] = masked.rank(pct=True, method="average") * 100.0
    out["rank_velocity_pct"] = out["rank_velocity_pct"].fillna(50.0)
    return out
