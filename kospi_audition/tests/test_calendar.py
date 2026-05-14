"""Unit tests for the trading-day walk-back primitive."""

from __future__ import annotations

import datetime as _dt

from kap.data.calendar import find_latest_trading_day, previous_business_day


def test_previous_business_day_skips_weekend() -> None:
    # 2026-05-18 is a Monday → prev = Friday 2026-05-15
    assert previous_business_day(_dt.date(2026, 5, 18)) == _dt.date(2026, 5, 15)


def test_find_latest_returns_first_truthy() -> None:
    seen: list[_dt.date] = []

    def probe(d: _dt.date) -> bool:
        seen.append(d)
        return d == _dt.date(2026, 5, 12)

    result = find_latest_trading_day(probe, _dt.date(2026, 5, 15))
    assert result == _dt.date(2026, 5, 12)
    # Should have probed: 5/15 (Fri), 5/14 (Thu), 5/13 (Wed), 5/12 (Tue).
    assert seen == [
        _dt.date(2026, 5, 15),
        _dt.date(2026, 5, 14),
        _dt.date(2026, 5, 13),
        _dt.date(2026, 5, 12),
    ]


def test_find_latest_returns_none_when_max_lookback_exhausted() -> None:
    calls: list[_dt.date] = []

    def probe(d: _dt.date) -> bool:
        calls.append(d)
        return False

    result = find_latest_trading_day(probe, _dt.date(2026, 5, 15), max_lookback=3)
    assert result is None
    assert len(calls) == 3


def test_find_latest_starts_from_friday_when_hint_is_sunday() -> None:
    seen: list[_dt.date] = []

    def probe(d: _dt.date) -> bool:
        seen.append(d)
        return True

    # Sun 2026-05-17 → first probe should be Fri 2026-05-15
    result = find_latest_trading_day(probe, _dt.date(2026, 5, 17))
    assert result == _dt.date(2026, 5, 15)
    assert seen[0] == _dt.date(2026, 5, 15)
