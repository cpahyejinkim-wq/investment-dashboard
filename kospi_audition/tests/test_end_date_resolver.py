"""Verify the pre-close / weekend rollback in run_analysis._resolve_end_date.

KRX publishes the day's close after 15:30 KST. Before that (or on Sat/Sun)
the pipeline must point at the previous business day, otherwise pykrx
returns empty JSON for ``today``.
"""

from __future__ import annotations

import datetime as _dt
import importlib

import pytest


def _patch_now(monkeypatch: pytest.MonkeyPatch, now: _dt.datetime) -> object:
    """Install a fake datetime.now and reload run_analysis to pick it up."""
    import run_analysis

    class _FakeDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(run_analysis._dt, "datetime", _FakeDateTime)
    return run_analysis


def test_weekday_before_close_rolls_back_to_yesterday(monkeypatch: pytest.MonkeyPatch) -> None:
    # Friday 04:45 KST - before market close.
    ra = _patch_now(
        monkeypatch,
        _dt.datetime(2026, 5, 15, 4, 45, tzinfo=ra_kst()),
    )
    assert ra._resolve_end_date() == _dt.date(2026, 5, 14)  # Thursday


def test_weekday_after_close_uses_today(monkeypatch: pytest.MonkeyPatch) -> None:
    # Friday 15:35 KST - after close.
    ra = _patch_now(
        monkeypatch,
        _dt.datetime(2026, 5, 15, 15, 35, tzinfo=ra_kst()),
    )
    assert ra._resolve_end_date() == _dt.date(2026, 5, 15)


def test_saturday_rolls_back_to_friday(monkeypatch: pytest.MonkeyPatch) -> None:
    ra = _patch_now(
        monkeypatch,
        _dt.datetime(2026, 5, 16, 9, 0, tzinfo=ra_kst()),
    )
    assert ra._resolve_end_date() == _dt.date(2026, 5, 15)


def test_sunday_rolls_back_to_friday(monkeypatch: pytest.MonkeyPatch) -> None:
    ra = _patch_now(
        monkeypatch,
        _dt.datetime(2026, 5, 17, 20, 0, tzinfo=ra_kst()),
    )
    assert ra._resolve_end_date() == _dt.date(2026, 5, 15)


def test_monday_before_close_rolls_back_to_friday(monkeypatch: pytest.MonkeyPatch) -> None:
    ra = _patch_now(
        monkeypatch,
        _dt.datetime(2026, 5, 18, 9, 0, tzinfo=ra_kst()),
    )
    assert ra._resolve_end_date() == _dt.date(2026, 5, 15)


def ra_kst() -> _dt.tzinfo:
    import zoneinfo
    return zoneinfo.ZoneInfo("Asia/Seoul")
