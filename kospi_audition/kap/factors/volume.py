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

    rows: list[dict[str, object]] = []
    for ticker, g in df.groupby("ticker", sort=False):
        g = g.tail(80).reset_index(drop=True)
        if len(g) < 20:
            continue

        tv_short = g["trade_value"].tail(20).mean()
        tv_long = g["trade_value"].tail(60).mean() if len(g) >= 60 else g["trade_value"].mean()
        spread = float(tv_short / tv_long) if tv_long else np.nan

        ret = g["close"].pct_change()
        recent = g.tail(50)
        recent_ret = ret.tail(50)
        up_vol = float(recent.loc[recent_ret > 0, "volume"].sum())
        down_vol = float(recent.loc[recent_ret < 0, "volume"].sum())
        ud_ratio = up_vol / down_vol if down_vol > 0 else np.nan

        obv = _obv(g["close"].values, g["volume"].values)
        obv_tail = obv[-20:] if len(obv) >= 20 else obv
        if len(obv_tail) >= 2:
            x = np.arange(len(obv_tail), dtype=float)
            slope = float(np.polyfit(x, obv_tail, 1)[0])
        else:
            slope = np.nan

        rows.append(
            {
                "ticker": ticker,
                "tv_spread": spread,
                "ud_volume_ratio": ud_ratio,
                "obv_slope": slope,
            }
        )

    out = pd.DataFrame(rows)
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
