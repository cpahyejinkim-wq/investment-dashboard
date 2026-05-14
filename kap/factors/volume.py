"""Volume Score (PRD §6.4).

A lightweight Sprint-mode version that captures trade-value diffusion plus
up/down volume ratio. Marathon-tier full version with OBV slope is added in
Stage 2 — the structure here is forward-compatible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger


def _percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def compute_volume(ohlcv: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    tickers = set(universe["ticker"])
    df = ohlcv[ohlcv["ticker"].isin(tickers)].copy()
    df = df.sort_values(["ticker", "date"])

    # Diffusion: TV_20 / TV_60
    tv = df.pivot(index="date", columns="ticker", values="trade_value").sort_index()
    if len(tv) >= 60:
        diffusion = (tv.tail(20).mean() / tv.tail(60).mean()).replace([np.inf, -np.inf], np.nan)
    else:
        diffusion = pd.Series(1.0, index=tv.columns)

    # Up/Down volume ratio (last 50 trading days)
    close = df.pivot(index="date", columns="ticker", values="close").sort_index()
    vol = df.pivot(index="date", columns="ticker", values="volume").sort_index()
    rets = close.pct_change()
    last50 = rets.tail(50)
    last50_vol = vol.tail(50)
    up_vol = (last50_vol.where(last50 > 0, 0)).sum()
    down_vol = (last50_vol.where(last50 < 0, 0)).sum()
    udr = (up_vol / (down_vol + 1.0)).astype(float)

    diff_pct = _percentile_rank(diffusion)
    udr_pct = _percentile_rank(udr)

    score = diff_pct * 0.4 + udr_pct * 0.6
    out = pd.DataFrame({
        "ticker": diffusion.index,
        "volume_diffusion": diffusion.values,
        "up_down_ratio": udr.reindex(diffusion.index).values,
        "volume_score": score.values,
        "volume_pct": _percentile_rank(score).values,
    }).reset_index(drop=True)
    logger.info("Volume score computed for {} tickers", len(out))
    return out
