"""Flow Score (외국인·기관 수급) per PRD section 6.7.

  Flow_Score = foreign_20d_net_buy_pct * 0.5 + inst_20d_net_buy_pct * 0.5

Boolean side flags (5일 연속 순매수) are surfaced for the dashboard.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_flow_score(flow: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-ticker 20-day cumulative flow and produce percentile scores.

    Parameters
    ----------
    flow : long-form DataFrame with columns
        ticker, date, foreign_net_buy, foreign_holding (optional),
        inst_net_buy, individual_net_buy
    """
    if flow is None or flow.empty:
        return pd.DataFrame(
            columns=["ticker", "flow_score", "flow_pct", "foreign_streak_5d", "inst_streak_5d"]
        )

    df = flow.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])

    rows: list[dict[str, object]] = []
    for ticker, g in df.groupby("ticker", sort=False):
        last_20 = g.tail(20)
        last_5 = g.tail(5)
        foreign_sum = float(last_20["foreign_net_buy"].sum())
        inst_sum = float(last_20["inst_net_buy"].sum())
        foreign_streak = bool((last_5["foreign_net_buy"] > 0).all()) if len(last_5) >= 5 else False
        inst_streak = bool((last_5["inst_net_buy"] > 0).all()) if len(last_5) >= 5 else False
        rows.append(
            {
                "ticker": ticker,
                "foreign_net_buy_20d": foreign_sum,
                "inst_net_buy_20d": inst_sum,
                "foreign_streak_5d": foreign_streak,
                "inst_streak_5d": inst_streak,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["foreign_pct"] = _pct(out["foreign_net_buy_20d"]).fillna(50.0)
    out["inst_pct"] = _pct(out["inst_net_buy_20d"]).fillna(50.0)
    out["flow_score"] = 0.5 * out["foreign_pct"] + 0.5 * out["inst_pct"]
    out["flow_pct"] = _pct(out["flow_score"]).fillna(50.0)
    return out


def synthetic_flow(ohlcv: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Generate deterministic synthetic flow data when pykrx flow is unavailable."""
    if ohlcv.empty:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    df = ohlcv[["ticker", "date", "trade_value"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])
    n = len(df)
    foreign = rng.normal(0, 1, n) * (df["trade_value"].values * 0.05)
    inst = rng.normal(0, 1, n) * (df["trade_value"].values * 0.04)
    indiv = -(foreign + inst)
    return pd.DataFrame(
        {
            "ticker": df["ticker"].values,
            "date": df["date"].values,
            "foreign_net_buy": foreign,
            "inst_net_buy": inst,
            "individual_net_buy": indiv,
        }
    )


def _pct(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average") * 100.0
