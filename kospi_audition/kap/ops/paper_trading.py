"""Paper Trading book per PRD section 13.4.

Simulates portfolio evolution over time given daily ranking JSON. The PRD
recommends running this for 3 months before going live with real capital.

Inputs each day:
  - sprint/marathon ranking (with current_price + weight + tier)
  - regime weight_multiplier (already applied upstream)

State kept in ``output/paper_trading.json``:
  - cash, total_equity, NAV history, holdings (qty per ticker), trade log
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from kap import config

PAPER_PATH: Path = config.OUTPUT_DIR / "paper_trading.json"
INITIAL_CAPITAL: float = 100_000_000.0  # 1억원
SLIPPAGE_PCT: float = float(config.BACKTEST["slippage_pct"])
COMMISSION_PCT: float = float(config.BACKTEST["commission_pct"])


def load_state() -> dict[str, Any]:
    if PAPER_PATH.exists():
        return json.loads(PAPER_PATH.read_text())
    return {
        "started_at": None,
        "cash": INITIAL_CAPITAL,
        "holdings": {},          # ticker -> {qty, avg_price, entry_mode}
        "nav_history": [],       # [{date, nav}]
        "trades": [],            # last 200 trades
    }


def save_state(state: dict[str, Any]) -> Path:
    PAPER_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=_safe))
    return PAPER_PATH


def _safe(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:  # noqa: BLE001
            return v
    return v


def rebalance(
    state: dict[str, Any],
    ranked: pd.DataFrame,
    active_mode: str,
    as_of: str,
    allowed_tiers: list[str],
) -> dict[str, Any]:
    """Adjust paper holdings towards the active mode's target weights.

    Trades are simulated at the day's close * (1 +/- slippage), with a flat
    commission on notional. Holdings outside the new target list are
    liquidated to honour Hard Stops / Regime Stops.
    """
    if state["started_at"] is None:
        state["started_at"] = as_of

    invested = (
        ranked[ranked["tier"].isin(allowed_tiers)].copy() if not ranked.empty else pd.DataFrame()
    )

    # Mark-to-market current holdings.
    nav = float(state["cash"])
    price_map: dict[str, float] = {}
    if not ranked.empty:
        for _, r in ranked.iterrows():
            if r.get("current_price"):
                price_map[str(r["ticker"])] = float(r["current_price"])
    for ticker, pos in state["holdings"].items():
        p = price_map.get(ticker, float(pos.get("avg_price", 0.0)))
        nav += float(pos["qty"]) * p

    if nav <= 0:
        state["nav_history"].append({"date": as_of, "nav": 0.0})
        return state

    # Compute target notional per ticker.
    target_notional: dict[str, float] = {}
    if not invested.empty:
        for _, r in invested.iterrows():
            w = float(r.get("weight", 0.0) or 0.0)
            target_notional[str(r["ticker"])] = nav * w

    # 1) Liquidate positions that fall out of the target list.
    for ticker in list(state["holdings"].keys()):
        if ticker not in target_notional:
            _liquidate(state, ticker, price_map.get(ticker), as_of, "exit")

    # 2) Resize / open positions to match target notional.
    for ticker, target in target_notional.items():
        price = price_map.get(ticker)
        if price is None or price <= 0:
            continue
        current = state["holdings"].get(ticker)
        cur_notional = float(current["qty"]) * price if current else 0.0
        diff = target - cur_notional
        if abs(diff) < nav * 0.001:  # below 0.1% noise floor
            continue
        if diff > 0:
            _buy(state, ticker, price, diff, active_mode, as_of)
        else:
            _trim(state, ticker, price, -diff, as_of)

    # Final NAV snapshot.
    new_nav = float(state["cash"])
    for ticker, pos in state["holdings"].items():
        p = price_map.get(ticker, float(pos.get("avg_price", 0.0)))
        new_nav += float(pos["qty"]) * p
    state["nav_history"].append({"date": as_of, "nav": new_nav})
    state["nav_history"] = state["nav_history"][-365:]
    state["trades"] = state["trades"][-200:]
    return state


def _buy(state: dict[str, Any], ticker: str, price: float, notional: float, mode: str, as_of: str) -> None:
    fill_price = price * (1.0 + SLIPPAGE_PCT)
    qty = notional / fill_price
    cost = qty * fill_price * (1.0 + COMMISSION_PCT)
    if cost > state["cash"]:
        qty = max(0.0, (state["cash"] / (fill_price * (1.0 + COMMISSION_PCT))))
        cost = qty * fill_price * (1.0 + COMMISSION_PCT)
    if qty <= 0:
        return
    state["cash"] -= cost
    current = state["holdings"].get(ticker)
    if current:
        new_qty = current["qty"] + qty
        avg = (current["qty"] * current["avg_price"] + qty * fill_price) / new_qty
        current["qty"] = new_qty
        current["avg_price"] = avg
    else:
        state["holdings"][ticker] = {"qty": qty, "avg_price": fill_price, "entry_mode": mode}
    state["trades"].append(
        {"date": as_of, "side": "buy", "ticker": ticker, "qty": qty, "price": fill_price, "mode": mode}
    )


def _trim(state: dict[str, Any], ticker: str, price: float, notional: float, as_of: str) -> None:
    pos = state["holdings"].get(ticker)
    if not pos:
        return
    fill_price = price * (1.0 - SLIPPAGE_PCT)
    qty = min(pos["qty"], notional / fill_price)
    proceeds = qty * fill_price * (1.0 - COMMISSION_PCT)
    state["cash"] += proceeds
    pos["qty"] -= qty
    state["trades"].append(
        {"date": as_of, "side": "sell", "ticker": ticker, "qty": qty, "price": fill_price}
    )
    if pos["qty"] <= 1e-6:
        del state["holdings"][ticker]


def _liquidate(state: dict[str, Any], ticker: str, price: float | None, as_of: str, reason: str) -> None:
    pos = state["holdings"].get(ticker)
    if not pos:
        return
    if price is None:
        price = float(pos.get("avg_price", 0.0))
    if price <= 0:
        del state["holdings"][ticker]
        return
    fill_price = price * (1.0 - SLIPPAGE_PCT)
    proceeds = pos["qty"] * fill_price * (1.0 - COMMISSION_PCT)
    state["cash"] += proceeds
    state["trades"].append(
        {"date": as_of, "side": "sell", "ticker": ticker, "qty": pos["qty"], "price": fill_price, "reason": reason}
    )
    del state["holdings"][ticker]
