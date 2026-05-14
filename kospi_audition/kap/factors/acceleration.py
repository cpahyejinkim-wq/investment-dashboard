"""Acceleration Score per PRD section 6.2.

  RS_acceleration    = RS_5D(t) - RS_5D(t-1)
  Volume_acceleration = log( mean_trade_value_5D / mean_trade_value_20D )
  Acceleration_Score = 0.5 * RS_accel_pct + 0.5 * Vol_accel_pct
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kap import config


def compute_acceleration(ohlcv: pd.DataFrame, benchmark: pd.Series) -> pd.DataFrame:
    """Return DataFrame[ticker, rs_acceleration, volume_acceleration, acceleration_score, acceleration_pct]."""
    if ohlcv.empty:
        return pd.DataFrame()

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    bench = benchmark.copy()
    bench.index = pd.to_datetime(bench.index)
    bench = bench.sort_index()

    close = df.pivot_table(index="date", columns="ticker", values="close").sort_index()
    trade_value = df.pivot_table(index="date", columns="ticker", values="trade_value").sort_index()

    if len(close) < 7:
        return pd.DataFrame()

    last_date = close.index[-1]
    if last_date not in bench.index:
        return pd.DataFrame()

    short, long = config.ACCELERATION_VOLUME_WINDOWS

    # RS_5D today and yesterday
    def rs_5d(date_idx: int) -> pd.Series:
        if abs(date_idx) + 5 >= len(close):
            return pd.Series(dtype=float)
        p_now = close.iloc[date_idx]
        p_past = close.iloc[date_idx - 5]
        b_now = float(bench.iloc[bench.index.get_indexer([close.index[date_idx]])[0]])
        b_past = float(bench.iloc[bench.index.get_indexer([close.index[date_idx - 5]])[0]])
        if b_past == 0:
            return pd.Series(dtype=float)
        return (p_now / p_past) / (b_now / b_past) - 1.0

    rs_today = rs_5d(-1)
    rs_yest = rs_5d(-2)
    if rs_today.empty or rs_yest.empty:
        return pd.DataFrame()

    rs_accel = (rs_today - rs_yest).rename("rs_acceleration")

    tv_short = trade_value.tail(short).mean()
    tv_long = trade_value.tail(long).mean()
    safe_long = tv_long.replace(0.0, np.nan)
    ratio = (tv_short / safe_long).replace([np.inf, -np.inf], np.nan)
    # log(0) is -inf which throws RuntimeWarning; mask zeros first.
    ratio = ratio.where(ratio > 0, other=np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        vol_accel = np.log(ratio).rename("volume_acceleration")

    out = pd.concat([rs_accel, vol_accel], axis=1).reset_index().rename(columns={"index": "ticker"})
    if "ticker" not in out.columns:
        out = out.rename(columns={out.columns[0]: "ticker"})

    out["rs_acceleration_pct"] = _pct(out["rs_acceleration"])
    out["volume_acceleration_pct"] = _pct(out["volume_acceleration"])
    out["acceleration_score"] = (
        0.5 * out["rs_acceleration_pct"] + 0.5 * out["volume_acceleration_pct"]
    )
    out["acceleration_pct"] = _pct(out["acceleration_score"])
    return out


def _pct(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average") * 100.0
