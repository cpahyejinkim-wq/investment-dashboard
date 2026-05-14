"""Mode Comparison helper per PRD section 11.3."""

from __future__ import annotations

from typing import Any

import pandas as pd


def compare_modes(
    sprint_ranked: pd.DataFrame, marathon_ranked: pd.DataFrame, top_n: int = 10
) -> dict[str, Any]:
    """Return a JSON-ready dict describing Sprint vs Marathon Top-N divergence."""
    sprint_top = (
        sprint_ranked.head(top_n)["ticker"].tolist() if not sprint_ranked.empty else []
    )
    marathon_top = (
        marathon_ranked.head(top_n)["ticker"].tolist() if not marathon_ranked.empty else []
    )
    sprint_set = set(sprint_top)
    marathon_set = set(marathon_top)
    intersection = sorted(sprint_set & marathon_set)
    sprint_only = [t for t in sprint_top if t not in marathon_set]
    marathon_only = [t for t in marathon_top if t not in sprint_set]

    overlap_ratio = len(intersection) / top_n if top_n else 0.0
    if 0.30 <= overlap_ratio <= 0.70:
        health = "healthy"
    elif overlap_ratio < 0.30:
        health = "diverged"
    else:
        health = "collapsed"

    return {
        "top_n": top_n,
        "sprint_top": sprint_top,
        "marathon_top": marathon_top,
        "intersection": intersection,
        "sprint_only": sprint_only,
        "marathon_only": marathon_only,
        "overlap_ratio": overlap_ratio,
        "health": health,
    }
