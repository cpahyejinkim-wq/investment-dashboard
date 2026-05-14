"""KRX trading-day helpers.

A single primitive — ``find_latest_trading_day(probe_fn, hint, max_lookback)`` —
walks backward one business day at a time from ``hint`` until ``probe_fn``
returns truthy (= data exists). Used by:

  - verify_pykrx.py             — to find the most-recent date the active
                                  collector can serve, instead of asking for
                                  a stale hard-coded date.
  - kap/data/fdr_collector.py   — index helpers fall back gracefully when
                                  the requested window is partly in the future.

Lookback default 30 business days, which covers Lunar New Year (~7d) +
Chuseok (~5d) + a couple of system-clock drift days. Bump higher if you run
on machines whose clock is set far ahead.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

DEFAULT_LOOKBACK = 30


def previous_business_day(d: _dt.date) -> _dt.date:
    d = d - _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d


def find_latest_trading_day(
    probe_fn: Callable[[_dt.date], bool],
    hint: _dt.date,
    max_lookback: int = DEFAULT_LOOKBACK,
) -> _dt.date | None:
    """Return the most recent date <= ``hint`` for which ``probe_fn`` is truthy.

    Walks weekdays only (probe_fn is never invoked on a Sat/Sun). Returns
    None if no truthy probe is found within ``max_lookback`` attempts.
    """
    candidate = hint
    while candidate.weekday() >= 5:
        candidate -= _dt.timedelta(days=1)
    for _ in range(max_lookback):
        if probe_fn(candidate):
            return candidate
        candidate = previous_business_day(candidate)
    return None
