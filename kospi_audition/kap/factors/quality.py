"""Quality Score Gate per PRD section 6.5.

Sprint S entry  : op_profit_positive (recommended), no mgmt-flag (required)
Marathon S/A    : op_profit_positive (required), rev_YoY >= -10% (required),
                  debt_ratio <= 300 (required), ROE >= 0 (recommended for S)
"""

from __future__ import annotations

import pandas as pd


def evaluate_quality(fundamentals: pd.DataFrame) -> pd.DataFrame:
    """Return a per-ticker quality summary used by both modes.

    Columns: ticker, op_profit_positive, revenue_yoy, debt_ratio, roe,
             quality_flags (list)
    """
    if fundamentals is None or fundamentals.empty:
        return pd.DataFrame(
            columns=[
                "ticker", "op_profit_positive", "revenue_yoy", "debt_ratio", "roe",
                "quality_flags",
            ]
        )
    df = fundamentals.copy()
    df["announcement_date"] = pd.to_datetime(df["announcement_date"])
    df = df.sort_values(["ticker", "announcement_date"])

    rows: list[dict[str, object]] = []
    for tk, g in df.groupby("ticker", sort=False):
        if len(g) == 0:
            continue
        latest = g.iloc[-1]
        op_pos = bool(float(latest["operating_profit"]) > 0)
        yoy = None
        if len(g) >= 5:
            prev = g.iloc[-5]
            prev_rev = float(prev["revenue"])
            if prev_rev > 0:
                yoy = float(latest["revenue"]) / prev_rev - 1.0
        flags: list[str] = []
        if not op_pos:
            flags.append("op_profit_negative")
        if yoy is not None and yoy < -0.10:
            flags.append("revenue_decline")
        if float(latest["debt_ratio"]) > 300:
            flags.append("high_debt")
        if float(latest["roe"]) < 0:
            flags.append("negative_roe")
        rows.append(
            {
                "ticker": tk,
                "op_profit_positive": op_pos,
                "revenue_yoy": yoy,
                "debt_ratio": float(latest["debt_ratio"]),
                "roe": float(latest["roe"]),
                "quality_flags": flags,
            }
        )
    return pd.DataFrame(rows)


def apply_quality_gate(ranking: pd.DataFrame, quality: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Drop tickers in restricted tiers that violate the mode's required checks.

    Sprint (PRD §6.5): only "A tier required"; S can bypass profit check.
    Marathon: S and A both require op_profit_positive + revenue_yoy >= -10%
              + debt_ratio <= 300.
    """
    if ranking.empty:
        return ranking
    if quality is None or quality.empty:
        ranking["quality_pass"] = True
        ranking["quality_flags"] = [[] for _ in range(len(ranking))]
        return ranking

    df = ranking.merge(quality, on="ticker", how="left")

    def _pass(row: pd.Series) -> bool:
        tier = row.get("tier")
        flags = row.get("quality_flags") if isinstance(row.get("quality_flags"), list) else []
        if mode == "sprint":
            if tier != "A":
                return True
            return "op_profit_negative" not in flags
        # Marathon
        if tier not in ("S", "A"):
            return True
        required_violations = {"op_profit_negative", "revenue_decline", "high_debt"}
        if any(f in flags for f in required_violations):
            return False
        if tier == "S" and "negative_roe" in flags:
            return False
        return True

    df["quality_pass"] = df.apply(_pass, axis=1)
    df.loc[~df["quality_pass"] & df["tier"].isin(["S", "A"]), "tier"] = "B"
    df["quality_flags"] = df["quality_flags"].apply(lambda x: x if isinstance(x, list) else [])
    return df
