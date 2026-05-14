"""Earnings Drift (PEAD) per PRD section 6.6.

  PEAD = (P_{t+5}/P_{t-1} - 1) - (KOSPI_{t+5}/KOSPI_{t-1} - 1)
  where t = most recent announcement_date within trailing 30 trading days.

Marathon mode weighting = 5%. Sprint mode ignores it.
"""

from __future__ import annotations

import pandas as pd


def compute_earnings_drift(
    ohlcv: pd.DataFrame,
    benchmark: pd.Series,
    fundamentals: pd.DataFrame,
) -> pd.DataFrame:
    if ohlcv.empty or fundamentals is None or fundamentals.empty:
        return pd.DataFrame(
            columns=["ticker", "earnings_drift", "earnings_drift_pct"]
        )

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    bench = benchmark.copy()
    bench.index = pd.to_datetime(bench.index)
    bench = bench.sort_index()
    last_date = df["date"].max()

    fund = fundamentals.copy()
    fund["announcement_date"] = pd.to_datetime(fund["announcement_date"])

    wide = df.pivot_table(index="date", columns="ticker", values="close").sort_index()

    rows: list[dict[str, object]] = []
    for ticker in wide.columns:
        ann = fund[fund["ticker"] == ticker]["announcement_date"]
        if ann.empty:
            continue
        # Most-recent announcement within 30 trading days of last_date.
        recent_ann = ann[ann <= last_date].max()
        if pd.isna(recent_ann):
            continue
        idx_ann = wide.index.searchsorted(recent_ann)
        if idx_ann <= 0 or idx_ann >= len(wide):
            continue
        if (last_date - recent_ann).days > 45:
            continue
        d_minus_1 = wide.index[idx_ann - 1]
        d_plus_5 = wide.index[min(idx_ann + 5, len(wide) - 1)]
        if d_minus_1 not in bench.index or d_plus_5 not in bench.index:
            continue
        p_pre = wide.loc[d_minus_1, ticker]
        p_post = wide.loc[d_plus_5, ticker]
        b_pre = float(bench.loc[d_minus_1])
        b_post = float(bench.loc[d_plus_5])
        if (
            pd.isna(p_pre) or pd.isna(p_post) or p_pre == 0 or b_pre == 0
        ):
            continue
        stock_ret = float(p_post) / float(p_pre) - 1.0
        bench_ret = b_post / b_pre - 1.0
        rows.append({"ticker": ticker, "earnings_drift": stock_ret - bench_ret})

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["ticker", "earnings_drift", "earnings_drift_pct"])
    out["earnings_drift_pct"] = out["earnings_drift"].rank(pct=True, method="average") * 100.0
    return out
