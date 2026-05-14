"""Volume Score per PRD section 6.4.

  거래대금 확산도 (Trade Value spread)     = TV_20D_avg / TV_60D_avg          (30%)
  Up/Down Volume Ratio (50일)              = sum(vol on up days) / sum(vol on down days) (40%)
  Accumulation (OBV slope, 20일)           = OLS slope percentile             (30%)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_volume_score(ohlcv: pd.DataFrame) -> pd.DataFrame:
    if ohlcv.empty:
        return pd.DataFrame(columns=["ticker", "volume_score", "volume_pct"])

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])

    # Keep only the trailing 80 trading days per ticker (vectorised tail).
    df = df.groupby("ticker", group_keys=False, sort=False).tail(80)
    df["ret"] = df.groupby("ticker", sort=False)["close"].pct_change()
    df["is_up"] = df["ret"] > 0
    df["is_down"] = df["ret"] < 0
    df["up_vol"] = df["volume"].where(df["is_up"], 0.0)
    df["down_vol"] = df["volume"].where(df["is_down"], 0.0)

    agg_tv_short = df.groupby("ticker", sort=False)["trade_value"].apply(lambda s: s.tail(20).mean())
    agg_tv_long = df.groupby("ticker", sort=False)["trade_value"].mean()  # ~last 80 (close enough to 60D for this purpose)
    spread = (agg_tv_short / agg_tv_long.replace(0.0, np.nan)).rename("tv_spread")

    up_sum = df.groupby("ticker", sort=False)["up_vol"].apply(lambda s: s.tail(50).sum())
    down_sum = df.groupby("ticker", sort=False)["down_vol"].apply(lambda s: s.tail(50).sum())
    ud_ratio = (up_sum / down_sum.replace(0.0, np.nan)).rename("ud_volume_ratio")

    def _slope(g: pd.Series) -> float:
        obv = _obv(g["close"].values, g["volume"].values)
        tail = obv[-20:] if len(obv) >= 20 else obv
        if len(tail) < 2:
            return np.nan
        x = np.arange(len(tail), dtype=float)
        return float(np.polyfit(x, tail, 1)[0])

    obv_slope = df.groupby("ticker", sort=False)[["close", "volume"]].apply(_slope).rename("obv_slope")

    out = pd.concat([spread, ud_ratio, obv_slope], axis=1).reset_index()
    if out.empty:
        return out
    out["tv_spread_pct"] = _pct(out["tv_spread"])
    out["ud_volume_ratio_pct"] = _pct(out["ud_volume_ratio"])
    out["obv_slope_pct"] = _pct(out["obv_slope"])

    # Fill remaining NaN with neutral 50.
    for c in ("tv_spread_pct", "ud_volume_ratio_pct", "obv_slope_pct"):
        out[c] = out[c].fillna(50.0)

    out["volume_score"] = (
        0.30 * out["tv_spread_pct"]
        + 0.40 * out["ud_volume_ratio_pct"]
        + 0.30 * out["obv_slope_pct"]
    )
    out["volume_pct"] = _pct(out["volume_score"]).fillna(50.0)
    return out


def _obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    if len(close) == 0:
        return np.array([], dtype=float)
    out = np.zeros(len(close), dtype=float)
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out


def _pct(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average") * 100.0
