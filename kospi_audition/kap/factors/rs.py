"""Relative Strength factor per PRD section 6.1.

RS_nD = (P_t / P_{t-n}) / (KOSPI_t / KOSPI_{t-n}) - 1

Returned columns are RS_<n>D and their cross-sectional percentile RS_<n>D_pct.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kap import config


def compute_rs(
    ohlcv: pd.DataFrame,
    benchmark: pd.Series,
    windows: tuple[int, ...] = config.RS_WINDOWS,
) -> pd.DataFrame:
    """Compute per-ticker RS over multiple windows on the latest date.

    Parameters
    ----------
    ohlcv : long-form OHLCV (ticker, date, close, ...)
    benchmark : close-price Series indexed by date (KOSPI typically)
    """
    if ohlcv.empty:
        return pd.DataFrame()

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    bench = benchmark.copy()
    bench.index = pd.to_datetime(bench.index)
    bench = bench.sort_index()

    last_date = df["date"].max()
    out_rows: list[dict[str, object]] = []

    # Pivot once for speed.
    wide = df.pivot_table(index="date", columns="ticker", values="close").sort_index()

    if last_date not in wide.index or last_date not in bench.index:
        return pd.DataFrame()

    bench_now = float(bench.loc[last_date])
    last_prices = wide.loc[last_date]

    for ticker, p_now in last_prices.items():
        if pd.isna(p_now):
            continue
        row: dict[str, object] = {"ticker": ticker}
        for n in windows:
            if len(wide) <= n:
                row[f"rs_{n}d"] = np.nan
                continue
            past_date = wide.index[-n - 1]
            p_past = wide.loc[past_date, ticker]
            b_past = bench.asof(past_date)
            if pd.isna(p_past) or pd.isna(b_past) or b_past == 0 or p_past == 0:
                row[f"rs_{n}d"] = np.nan
                continue
            stock_ret = float(p_now) / float(p_past)
            bench_ret = bench_now / float(b_past)
            row[f"rs_{n}d"] = stock_ret / bench_ret - 1.0
        out_rows.append(row)

    out = pd.DataFrame(out_rows)
    for n in windows:
        col = f"rs_{n}d"
        out[f"{col}_pct"] = _percentile_rank(out[col])
    return out


def _percentile_rank(series: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank in [0, 100]."""
    return series.rank(pct=True, method="average") * 100.0
