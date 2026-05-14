"""Universe filter per PRD section 4.1."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from kap import config


def build_universe(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Apply universe filter to OHLCV history.

    Returns a per-ticker latest-snapshot DataFrame with columns:
      ticker, market, last_date, last_close, market_cap, trade_value_20d,
      listing_days, included
    """
    if ohlcv.empty:
        return ohlcv

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])

    last_date = df["date"].max()
    grouped = df.sort_values("date").groupby("ticker", as_index=False, sort=False)

    rows: list[dict[str, object]] = []
    for ticker, g in grouped:
        last = g.iloc[-1]
        trade_value_20d = float(g["trade_value"].tail(20).mean())
        listing_days = int(g["date"].nunique())
        market = str(last["market"])
        # Keep market_cap as NaN if missing - the filter treats unknown as
        # "info absent" rather than "fails the cap test".
        market_cap = (
            float(last["market_cap"]) if pd.notna(last["market_cap"]) else float("nan")
        )
        rows.append(
            {
                "ticker": ticker,
                "market": market,
                "last_date": last["date"].date(),
                "last_close": float(last["close"]),
                "market_cap": market_cap,
                "trade_value_20d": trade_value_20d,
                "listing_days": listing_days,
            }
        )

    snap = pd.DataFrame(rows)
    snap["included"] = snap.apply(_passes_filter, axis=1)

    n_total, n_in = len(snap), int(snap["included"].sum())
    logger.info(
        "universe: {}/{} included (last_date={})", n_in, n_total, last_date.date()
    )
    return snap


def _passes_filter(row: pd.Series) -> bool:
    cfg = config.UNIVERSE
    min_cap = (
        cfg["min_market_cap_kospi"] if row["market"] == "KOSPI" else cfg["min_market_cap_kosdaq"]
    )
    # Only reject on market cap when we actually KNOW it. NaN means data
    # provider didn't include it (e.g. FDR per-ticker history); let it through
    # so subsequent liquidity / price / listing checks decide.
    if pd.notna(row["market_cap"]) and row["market_cap"] < min_cap:
        return False
    if row["trade_value_20d"] < cfg["min_trade_value_20d"]:
        return False
    if row["listing_days"] < cfg["min_listing_days"]:
        return False
    if row["last_close"] < cfg["min_price"]:
        return False
    return True
