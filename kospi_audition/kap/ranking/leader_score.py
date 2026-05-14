"""Leader Score per PRD section 6.8.

  Leader_Score = 0.70 * Mode_Score(active mode)
               + 0.30 * Survival_Days_weighted_pct
  Survival_Days_weighted = S_days*3 + A_days*2 + B_days*1
"""

from __future__ import annotations

import pandas as pd


def compute_leader_score(
    ranking: pd.DataFrame, tier_history: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Attach survival_days, survival_weighted, leader_score columns.

    Parameters
    ----------
    ranking : current ranking dataframe with `mode_score_pct` column.
    tier_history : long-form (ticker, date, tier). If None, survival defaults
        to 0 — Stage 3 has no prior history on first run.
    """
    if ranking.empty:
        return ranking.assign(survival_days=0, survival_weighted=0, leader_score=0.0)
    df = ranking.copy()
    if tier_history is None or tier_history.empty:
        df["survival_days"] = 0
        df["survival_weighted"] = 0
    else:
        agg = (
            tier_history.groupby(["ticker", "tier"]).size().unstack(fill_value=0)
        )
        for col in ("S", "A", "B"):
            if col not in agg.columns:
                agg[col] = 0
        agg["survival_weighted"] = agg["S"] * 3 + agg["A"] * 2 + agg["B"] * 1
        agg["survival_days"] = agg[["S", "A", "B"]].sum(axis=1)
        df = df.merge(
            agg[["survival_days", "survival_weighted"]].reset_index(),
            on="ticker",
            how="left",
        )
        df["survival_days"] = df["survival_days"].fillna(0).astype(int)
        df["survival_weighted"] = df["survival_weighted"].fillna(0).astype(int)

    df["survival_weighted_pct"] = (
        df["survival_weighted"].rank(pct=True, method="average") * 100.0
    ).fillna(50.0)
    df["leader_score"] = 0.70 * df["mode_score_pct"] + 0.30 * df["survival_weighted_pct"]
    return df
