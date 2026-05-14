"""Relative Strength factor (PRD §6.1).

RS_nD = (P_t / P_{t-n}) / (KOSPI_t / KOSPI_{t-n}) - 1
Computed for n in {5, 20, 60, 120, 252} as cross-sectional percentiles.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd
from loguru import logger

RS_PERIODS: Final[tuple[int, ...]] = (5, 20, 60, 120, 252)


def _percentile_rank(s: pd.Series) -> pd.Series:
    """Cross-sectional percentile, 0..100. NaNs preserved."""
    return s.rank(pct=True, method="average") * 100.0


def compute_rs(
    ohlcv: pd.DataFrame, index_df: pd.DataFrame, universe: pd.DataFrame
) -> pd.DataFrame:
    """One row per universe ticker with raw RS and percentile columns."""
    as_of = ohlcv["date"].max()
    tickers = set(universe["ticker"])
    px = ohlcv[ohlcv["ticker"].isin(tickers)].pivot(index="date", columns="ticker", values="close").sort_index()
    kospi = index_df.set_index("date")["kospi_close"].reindex(px.index).ffill()

    out: dict[str, pd.Series] = {}
    for n in RS_PERIODS:
        if len(px) <= n:
            continue
        stock_ret = px.iloc[-1] / px.iloc[-1 - n] - 1
        bench_ret = kospi.iloc[-1] / kospi.iloc[-1 - n] - 1
        rs = (stock_ret - bench_ret).astype(float)
        out[f"rs_{n}d"] = rs
        out[f"rs_{n}d_pct"] = _percentile_rank(rs)

    df = pd.DataFrame(out).reset_index().rename(columns={"index": "ticker"})
    df["date"] = pd.Timestamp(as_of)
    logger.info("RS computed for {} tickers, periods={}", len(df), list(RS_PERIODS))
    return df
