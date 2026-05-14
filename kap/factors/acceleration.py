"""Acceleration Score (PRD §6.2) — NEW v2.1.

Captures the second derivative of momentum + trade-value acceleration.
Designed to surface stocks that *just started* getting stronger — critical
in Korean markets where sector rotation is fast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger


def _percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def compute_acceleration(
    ohlcv: pd.DataFrame, index_df: pd.DataFrame, universe: pd.DataFrame
) -> pd.DataFrame:
    """Returns ticker, acceleration_raw, acceleration_pct (and components)."""
    tickers = set(universe["ticker"])
    px = ohlcv[ohlcv["ticker"].isin(tickers)].pivot(index="date", columns="ticker", values="close").sort_index()
    tv = ohlcv[ohlcv["ticker"].isin(tickers)].pivot(index="date", columns="ticker", values="trade_value").sort_index()
    kospi = index_df.set_index("date")["kospi_close"].reindex(px.index).ffill()

    if len(px) < 7:
        raise ValueError("Not enough history for acceleration (need ≥ 7 days)")

    # RS_5D today
    stock_ret_today = px.iloc[-1] / px.iloc[-6] - 1
    bench_ret_today = float(kospi.iloc[-1] / kospi.iloc[-6] - 1)
    rs_5d_today = stock_ret_today - bench_ret_today

    # RS_5D yesterday
    stock_ret_yest = px.iloc[-2] / px.iloc[-7] - 1
    bench_ret_yest = float(kospi.iloc[-2] / kospi.iloc[-7] - 1)
    rs_5d_yest = stock_ret_yest - bench_ret_yest

    rs_accel = (rs_5d_today - rs_5d_yest).astype(float)

    # Volume (trade value) acceleration: log(TV_5D / TV_20D)
    if len(tv) >= 20:
        tv_5d = tv.tail(5).mean()
        tv_20d = tv.tail(20).mean()
        vol_accel = np.log((tv_5d + 1.0) / (tv_20d + 1.0)).astype(float)
    else:
        vol_accel = pd.Series(0.0, index=tv.columns)

    rs_pct = _percentile_rank(rs_accel)
    vol_pct = _percentile_rank(vol_accel)
    accel = (rs_pct * 0.5 + vol_pct * 0.5)
    accel_pct = _percentile_rank(accel)

    df = pd.DataFrame({
        "ticker": rs_accel.index,
        "rs_acceleration": rs_accel.values,
        "volume_acceleration": vol_accel.reindex(rs_accel.index).values,
        "acceleration_raw": accel.values,
        "acceleration_pct": accel_pct.values,
    }).reset_index(drop=True)
    logger.info("Acceleration computed for {} tickers", len(df))
    return df
