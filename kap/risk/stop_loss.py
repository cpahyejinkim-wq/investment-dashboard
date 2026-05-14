"""Mode-aware Stop Loss rules (PRD §8.2).

Each position keeps the rules of the mode it was *entered* with (Soft Migration,
PRD §2.3). Computes hard stop, trailing stop, and time stop for current holdings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from loguru import logger

from kap.config import MODES

Market = Literal["KOSPI", "KOSDAQ"]


@dataclass(frozen=True)
class StopLossLevels:
    ticker: str
    entry_mode: str
    entry_price: float
    high_since_entry: float
    current_price: float
    hard_stop_price: float
    trailing_stop_price: float
    time_stop_days_remaining: int
    triggered: list[str]


def compute_stops(
    ticker: str,
    market: Market,
    entry_mode: str,
    entry_price: float,
    high_since_entry: float,
    current_price: float,
    days_since_last_new_high: int,
) -> StopLossLevels:
    cfg = MODES[entry_mode]
    hard_pct = float(cfg["hard_stop_kospi"]) if market == "KOSPI" else float(cfg["hard_stop_kosdaq"])
    trail_pct = float(cfg["trailing_stop"])
    time_limit = int(cfg["time_stop_days"])

    hard_stop_price = entry_price * (1.0 + hard_pct)
    trailing_stop_price = high_since_entry * (1.0 + trail_pct)
    days_remaining = max(0, time_limit - days_since_last_new_high)

    triggered: list[str] = []
    if current_price <= hard_stop_price:
        triggered.append("hard_stop")
    if current_price <= trailing_stop_price:
        triggered.append("trailing_stop")
    if days_since_last_new_high >= time_limit:
        triggered.append("time_stop")

    return StopLossLevels(
        ticker=ticker,
        entry_mode=entry_mode,
        entry_price=entry_price,
        high_since_entry=high_since_entry,
        current_price=current_price,
        hard_stop_price=hard_stop_price,
        trailing_stop_price=trailing_stop_price,
        time_stop_days_remaining=days_remaining,
        triggered=triggered,
    )


def compute_stops_for_holdings(holdings: pd.DataFrame, ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Given a holdings DataFrame [ticker, market, entry_mode, entry_price, entry_date],
    join with current OHLCV to compute stops + identify any triggers.
    """
    if holdings.empty:
        return pd.DataFrame()

    out_rows = []
    px = ohlcv.sort_values(["ticker", "date"])
    last_close = px.groupby("ticker").tail(1).set_index("ticker")[["close", "date"]]
    last_close.columns = ["current_price", "current_date"]

    for _, h in holdings.iterrows():
        ticker = h["ticker"]
        if ticker not in last_close.index:
            continue
        entry_date = pd.Timestamp(h["entry_date"])
        post_entry = px[(px["ticker"] == ticker) & (px["date"] >= entry_date)]
        if post_entry.empty:
            continue
        high_since = float(post_entry["high"].max())
        # Days since last new high
        idx_max = post_entry["high"].idxmax()
        last_new_high_date = post_entry.loc[idx_max, "date"]
        days_since_high = int((post_entry["date"].max() - last_new_high_date).days)

        stops = compute_stops(
            ticker=ticker,
            market=h["market"],
            entry_mode=h["entry_mode"],
            entry_price=float(h["entry_price"]),
            high_since_entry=high_since,
            current_price=float(last_close.loc[ticker, "current_price"]),
            days_since_last_new_high=days_since_high,
        )
        out_rows.append({
            "ticker": stops.ticker,
            "entry_mode": stops.entry_mode,
            "entry_price": stops.entry_price,
            "current_price": stops.current_price,
            "high_since_entry": stops.high_since_entry,
            "hard_stop_price": stops.hard_stop_price,
            "trailing_stop_price": stops.trailing_stop_price,
            "time_stop_days_remaining": stops.time_stop_days_remaining,
            "triggered": stops.triggered,
        })

    out = pd.DataFrame(out_rows)
    if not out.empty:
        n_trig = int((out["triggered"].str.len() > 0).sum())
        logger.info("Stops computed for {} holdings, {} triggered", len(out), n_trig)
    return out


def compute_initial_stops_for_candidates(candidates: pd.DataFrame, mode: str) -> pd.DataFrame:
    """For new entry candidates, pre-compute the hard/trailing stops that would
    apply on entry at the current close. Used by the dashboard preview."""
    if candidates.empty:
        return candidates
    cfg = MODES[mode]
    out = candidates.copy()
    is_kospi = out["market"] == "KOSPI"
    hard_pct_kospi = float(cfg["hard_stop_kospi"])
    hard_pct_kosdaq = float(cfg["hard_stop_kosdaq"])
    trail_pct = float(cfg["trailing_stop"])
    entry_price = out["close"].astype(float)
    out["hard_stop_price"] = np.where(is_kospi, entry_price * (1 + hard_pct_kospi), entry_price * (1 + hard_pct_kosdaq))
    out["trailing_stop_price"] = entry_price * (1 + trail_pct)
    out["entry_mode"] = mode
    return out
