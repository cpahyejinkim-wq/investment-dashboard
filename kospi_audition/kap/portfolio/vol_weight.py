"""Volatility-Adjusted Weight per PRD section 7.3 (opt-in via config)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from kap import config


def adjust_weights(
    ranking: pd.DataFrame, ohlcv: pd.DataFrame, weight_col: str = "weight"
) -> pd.DataFrame:
    """Multiply base weights by target_vol / stock_vol_60d (clipped).

    No-op when ``VOL_ADJUSTED_WEIGHT['enabled']`` is False.
    """
    if not config.VOL_ADJUSTED_WEIGHT["enabled"] or ranking.empty:
        return ranking
    window = int(config.VOL_ADJUSTED_WEIGHT["target_vol_window"])
    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])
    ret = df.groupby("ticker")["close"].pct_change()
    df["ret"] = ret
    vol = (
        df.groupby("ticker")["ret"].apply(lambda s: s.tail(window).std()).rename("vol")
    )
    target = float(vol.mean())
    out = ranking.merge(vol.reset_index(), on="ticker", how="left")
    safe = out["vol"].replace(0.0, np.nan)
    factor = (target / safe).clip(lower=0.5, upper=1.5).fillna(1.0)
    out[weight_col] = out[weight_col] * factor
    return out.drop(columns="vol", errors="ignore")
