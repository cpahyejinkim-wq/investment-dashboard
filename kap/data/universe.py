"""Universe filter (PRD §4.1).

Filters by market cap, average trade value, listing age, and price.
Excludes managed/halted/ETF/ETN/SPAC/preferred/REIT names — for the synthetic
dataset there are none of those, but the structure supports real KRX exclusion lists.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from kap.config import UNIVERSE


def build_universe(
    ohlcv: pd.DataFrame, metadata: pd.DataFrame, as_of: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Return a metadata-shaped DataFrame restricted to qualifying tickers."""
    as_of = as_of or pd.Timestamp(ohlcv["date"].max())

    df = ohlcv[ohlcv["date"] <= as_of].copy()
    last = df.sort_values("date").groupby("ticker").tail(1)

    # 20-day average trade value
    last20 = (
        df.sort_values("date").groupby("ticker").tail(20)
        .groupby("ticker")["trade_value"].mean().rename("avg_trade_value_20d")
    )

    # Listing days
    first_seen = df.groupby("ticker")["date"].min().rename("first_seen")

    snap = last.merge(last20, on="ticker").merge(first_seen, on="ticker")
    # ohlcv already carries `market`; bring `name`/`sector`/`listing_date` from metadata
    snap = snap.merge(metadata[["ticker", "name", "sector", "listing_date"]], on="ticker", how="left")

    snap["listing_days"] = (as_of - pd.to_datetime(snap["listing_date"])).dt.days

    min_cap_kospi = int(UNIVERSE["min_market_cap_kospi"])
    min_cap_kosdaq = int(UNIVERSE["min_market_cap_kosdaq"])

    cap_ok = (
        ((snap["market"] == "KOSPI") & (snap["market_cap"] >= min_cap_kospi))
        | ((snap["market"] == "KOSDAQ") & (snap["market_cap"] >= min_cap_kosdaq))
    )
    tv_ok = snap["avg_trade_value_20d"] >= int(UNIVERSE["min_trade_value_20d"])
    listing_ok = snap["listing_days"] >= int(UNIVERSE["min_listing_days"])
    price_ok = snap["close"] >= int(UNIVERSE["min_price"])

    mask = cap_ok & tv_ok & listing_ok & price_ok
    out = snap[mask][["ticker", "name", "market", "sector", "market_cap", "close",
                      "avg_trade_value_20d", "listing_days"]].reset_index(drop=True)
    logger.info(
        "Universe filter: {} → {} (cap={}, tv={}, listing={}, price={})",
        len(snap), len(out), cap_ok.sum(), tv_ok.sum(), listing_ok.sum(), price_ok.sum(),
    )
    return out
