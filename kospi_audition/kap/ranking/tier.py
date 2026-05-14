"""Tier classification + Mode-aware pyramiding weights per PRD section 7."""

from __future__ import annotations

import pandas as pd

from kap import config


def assign_tiers(
    scored: pd.DataFrame,
    mode: str,
    score_pct_col: str,
) -> pd.DataFrame:
    """Assign S/A/B/C/D tiers using mode-specific thresholds and max-count caps.

    Parameters
    ----------
    scored : DataFrame with a percentile column.
    mode   : "sprint" or "marathon".
    score_pct_col : name of the percentile column (e.g. "sprint_score_pct").
    """
    if scored.empty:
        return scored.assign(tier="D")
    cfg = config.MODES[mode]
    thresholds = cfg["tier_thresholds"]
    caps = cfg["tier_max_count"]

    df = scored.sort_values(score_pct_col, ascending=False).reset_index(drop=True)
    tiers: list[str] = []
    counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    for _, row in df.iterrows():
        p = float(row[score_pct_col])
        if p >= thresholds["S"] and counts["S"] < caps["S"]:
            tiers.append("S"); counts["S"] += 1
        elif p >= thresholds["A"] and counts["A"] < caps["A"]:
            tiers.append("A"); counts["A"] += 1
        elif p >= thresholds["B"] and counts["B"] < caps["B"]:
            tiers.append("B"); counts["B"] += 1
        elif p >= thresholds["C"]:
            tiers.append("C"); counts["C"] += 1
        else:
            tiers.append("D")
    df["tier"] = tiers
    return df


def assign_weights(
    tiered: pd.DataFrame,
    mode: str,
    regime_multiplier: float,
    allowed_tiers: list[str],
) -> pd.DataFrame:
    """Apply mode base weights * regime multiplier and enforce min-cash floor."""
    cfg = config.MODES[mode]
    base = cfg["base_weights"]
    min_cash = float(cfg["min_cash"])

    df = tiered.copy()

    def _w(tier: str) -> float:
        if tier not in allowed_tiers:
            return 0.0
        return float(base.get(tier, 0.0)) * float(regime_multiplier)

    df["weight_target"] = df["tier"].map(_w)
    total_invested = float(df["weight_target"].sum())
    available = 1.0 - min_cash
    if total_invested > available and total_invested > 0:
        df["weight_target"] = df["weight_target"] * (available / total_invested)
    df["weight"] = df["weight_target"]
    return df
