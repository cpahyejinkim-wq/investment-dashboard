"""Tier classification & pyramiding weight allocation (PRD §7).

Given mode scores (percentile) and the mode's tier thresholds/caps, assign
S/A/B/C/D tiers and target weights. Applies regime weight multiplier and
allowed-tier filter.
"""

from __future__ import annotations

from typing import cast

import pandas as pd
from loguru import logger

from kap.config import MODES, REGIME


def classify_tier(score_pct: pd.Series, mode: str) -> pd.Series:
    th = MODES[mode]["tier_thresholds"]
    out = pd.Series("D", index=score_pct.index, dtype=object)
    out[score_pct >= th["C"]] = "C"
    out[score_pct >= th["B"]] = "B"
    out[score_pct >= th["A"]] = "A"
    out[score_pct >= th["S"]] = "S"
    return out


def apply_tier_caps(df: pd.DataFrame, mode: str, score_col: str, tier_col: str = "tier") -> pd.DataFrame:
    """Enforce tier max counts — if more candidates than cap, demote the lowest scoring."""
    caps = MODES[mode]["tier_max_count"]
    out = df.copy()
    for tier in ["S", "A", "B"]:
        mask = out[tier_col] == tier
        if mask.sum() > caps[tier]:
            sorted_idx = out.loc[mask].sort_values(score_col, ascending=False).index
            keep = sorted_idx[: caps[tier]]
            demote = sorted_idx[caps[tier]:]
            next_tier = {"S": "A", "A": "B", "B": "C"}[tier]
            out.loc[demote, tier_col] = next_tier
    return out


def assign_weights(df: pd.DataFrame, mode: str, regime_state: str, tier_col: str = "tier") -> pd.DataFrame:
    """Target portfolio weight per ticker = base_weight × regime_multiplier.

    Applies allowed-tier filter (Risk-Off → all weights 0).
    """
    base = MODES[mode]["base_weights"]
    mult_map = cast(dict[str, float], REGIME["weight_multiplier"])
    allowed_map = cast(dict[str, list[str]], REGIME["allowed_tiers"])
    mult = mult_map.get(regime_state, 0.0)
    allowed = set(allowed_map.get(regime_state, []))

    out = df.copy()
    out["weight_base"] = out[tier_col].map(base).fillna(0.0)
    out["weight_target"] = out["weight_base"] * mult
    out.loc[~out[tier_col].isin(allowed), "weight_target"] = 0.0
    # Active 1st-tranche entry size: 60% of target for Sprint, 50% for Marathon (PRD §8.3)
    pyramid_first = 0.6 if mode == "sprint" else 0.5
    out["weight"] = out["weight_target"] * pyramid_first

    min_cash = MODES[mode]["min_cash"]
    total = float(out["weight"].sum())
    if total > 1.0 - min_cash:
        scale = (1.0 - min_cash) / total
        out["weight"] = out["weight"] * scale
        out["weight_target"] = out["weight_target"] * scale
        logger.info("Scaled weights by {:.3f} to enforce min_cash={:.0%}", scale, min_cash)
    logger.info(
        "Tier weights assigned ({}): S={}, A={}, B={}, C={}, sum_weight={:.3f}",
        mode,
        (out[tier_col] == "S").sum(), (out[tier_col] == "A").sum(),
        (out[tier_col] == "B").sum(), (out[tier_col] == "C").sum(),
        out["weight"].sum(),
    )
    return out
