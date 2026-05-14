"""Entry signal detection per PRD section 8.1.

  Breakout : 52-week new high + volume >= 20D avg * 1.5
  VCP      : volatility contraction then box-top breakout
  Pullback : touch 20MA +/- 2% then rebound

Returns DataFrame[ticker, entry_signal, entry_signal_date].
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_entry_signals(ohlcv: pd.DataFrame) -> pd.DataFrame:
    if ohlcv.empty:
        return pd.DataFrame(columns=["ticker", "entry_signal", "entry_signal_date"])

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])

    rows: list[dict[str, object]] = []
    for ticker, g in df.groupby("ticker", sort=False):
        g = g.tail(260).reset_index(drop=True)
        if len(g) < 60:
            continue
        sig = _classify(g)
        if sig is None:
            continue
        rows.append(
            {
                "ticker": ticker,
                "entry_signal": sig,
                "entry_signal_date": g["date"].iloc[-1].date().isoformat(),
            }
        )
    return pd.DataFrame(rows)


def _classify(g: pd.DataFrame) -> str | None:
    close = g["close"].values
    high = g["high"].values
    volume = g["volume"].values

    # ---- Breakout: today's high >= max of last 252 highs and volume surge ----
    lookback = min(252, len(high) - 1)
    if lookback >= 20:
        past_max = float(np.max(high[-(lookback + 1):-1]))
        vol_avg = float(np.mean(volume[-21:-1]))
        if close[-1] >= past_max and vol_avg > 0 and volume[-1] >= vol_avg * 1.5:
            return "breakout"

    # ---- VCP: 3 successive contractions then close > recent box top ---------
    if len(close) >= 60:
        win_atr = pd.Series(close).pct_change().rolling(10).std().values
        if (
            not np.isnan(win_atr[-1])
            and not np.isnan(win_atr[-21])
            and not np.isnan(win_atr[-41])
            and win_atr[-1] < win_atr[-21] < win_atr[-41]
        ):
            box_top = float(np.max(high[-20:-1]))
            if close[-1] > box_top:
                return "vcp"

    # ---- Pullback: touched 20MA +/- 2% and rebounded today ------------------
    if len(close) >= 25:
        ma20 = float(np.mean(close[-21:-1]))
        if ma20 > 0:
            yesterday = close[-2]
            today = close[-1]
            touched = abs(yesterday - ma20) / ma20 <= 0.02
            rebounded = today > yesterday
            uptrend = ma20 > float(np.mean(close[-61:-1]))
            if touched and rebounded and uptrend:
                return "pullback"

    return None
