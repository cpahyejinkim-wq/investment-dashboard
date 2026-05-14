"""Persistent position book with Soft Migration per PRD section 2.3.

When the active Audition Mode is toggled, existing positions keep the rules
of the mode under which they were originally entered. Only fresh entries use
the rules of the newly-selected mode.

Position book is persisted as JSON at ``output/positions.json`` so the
dashboard and subsequent runs can read it.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from kap import config


POSITIONS_PATH: Path = config.OUTPUT_DIR / "positions.json"


def load_positions() -> dict[str, dict[str, Any]]:
    if not POSITIONS_PATH.exists():
        return {}
    raw = json.loads(POSITIONS_PATH.read_text())
    return {item["ticker"]: item for item in raw.get("positions", [])}


def save_positions(positions: dict[str, dict[str, Any]], as_of: str) -> Path:
    payload = {
        "as_of": as_of,
        "positions": list(positions.values()),
    }
    POSITIONS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return POSITIONS_PATH


def reconcile(
    book: dict[str, dict[str, Any]],
    ranked: pd.DataFrame,
    active_mode: str,
    regime_state: str,
    today: date,
    allowed_tiers: list[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Apply Soft Migration to existing book + admit new entries from ranking.

    Returns ``(updated_book, events)`` where events log entries / migrations.
    """
    events: list[dict[str, Any]] = []
    new_book = dict(book)

    rank_by_ticker: dict[str, dict[str, Any]] = (
        {row["ticker"]: row.to_dict() for _, row in ranked.iterrows()} if not ranked.empty else {}
    )

    # 1) Update existing positions with today's tier + current price; rules unchanged.
    for ticker, pos in list(new_book.items()):
        row = rank_by_ticker.get(ticker)
        if row is None:
            pos["tier_today"] = "D"
        else:
            pos["tier_today"] = row.get("tier", "D")
            pos["current_price"] = row.get("current_price", pos.get("current_price"))
        pos["last_update"] = today.isoformat()

    # 2) Block new entries when regime forbids it.
    if not allowed_tiers:
        return new_book, events

    # 3) Admit new entries from the ranking using the *active* mode's rules.
    for ticker, row in rank_by_ticker.items():
        if ticker in new_book:
            continue
        tier = row.get("tier", "D")
        if tier not in allowed_tiers:
            continue
        new_book[ticker] = {
            "ticker": ticker,
            "entry_mode": active_mode,
            "entry_tier": tier,
            "entry_date": today.isoformat(),
            "entry_price": float(row.get("current_price") or 0.0),
            "market": row.get("market"),
            "stop_loss": row.get("stop_loss"),
            "trailing_stop": row.get("trailing_stop"),
            "time_stop_days": row.get("time_stop_days"),
            "tier_today": tier,
            "current_price": row.get("current_price"),
            "last_update": today.isoformat(),
        }
        events.append(
            {
                "type": "entry",
                "ticker": ticker,
                "mode": active_mode,
                "tier": tier,
                "regime": regime_state,
                "as_of": today.isoformat(),
            }
        )

    return new_book, events


def soft_migration_check(
    book: dict[str, dict[str, Any]], active_mode: str
) -> list[dict[str, Any]]:
    """Return the subset of positions whose entry_mode differs from active_mode.

    These positions keep their original mode rules - this helper merely logs
    them so the dashboard can show a soft-migration notice.
    """
    return [p for p in book.values() if p.get("entry_mode") and p.get("entry_mode") != active_mode]
