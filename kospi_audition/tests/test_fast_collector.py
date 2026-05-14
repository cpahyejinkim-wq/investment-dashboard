"""Tests for the date-based pykrx fast path + incremental cache.

A fake ``pykrx.stock`` is monkey-patched so the test exercises the real
collector code paths without touching the network.
"""

from __future__ import annotations

import datetime as _dt
import types
from pathlib import Path

import pandas as pd
import pytest

from kap import config
from kap.data import collector


def _fake_stock_module() -> types.SimpleNamespace:
    def get_market_ohlcv_by_ticker(date_str: str, market: str) -> pd.DataFrame:
        # Two synthetic rows per call so the merge logic is exercised.
        tickers = ["005930", "000660"] if market == "KOSPI" else ["035720"]
        rows = []
        for tk in tickers:
            base = 70_000 if tk == "005930" else (130_000 if tk == "000660" else 200_000)
            rows.append(
                {
                    "시가": base * 0.99,
                    "고가": base * 1.02,
                    "저가": base * 0.98,
                    "종가": base * 1.01,
                    "거래량": 1_000_000,
                    "거래대금": base * 1.01 * 1_000_000,
                }
            )
        df = pd.DataFrame(rows, index=tickers)
        df.index.name = "ticker"
        return df

    def get_market_cap_by_ticker(date_str: str, market: str) -> pd.DataFrame:
        tickers = ["005930", "000660"] if market == "KOSPI" else ["035720"]
        df = pd.DataFrame(
            {
                "시가총액": [4.5e14, 8.5e13, 1.2e14][: len(tickers)],
                "상장주식수": [5.97e9, 7.28e8, 4.85e8][: len(tickers)],
            },
            index=tickers,
        )
        df.index.name = "ticker"
        return df

    def get_market_ticker_list(date_str: str, market: str) -> list[str]:
        return ["005930", "000660"] if market == "KOSPI" else ["035720"]

    return types.SimpleNamespace(
        get_market_ohlcv_by_ticker=get_market_ohlcv_by_ticker,
        get_market_cap_by_ticker=get_market_cap_by_ticker,
        get_market_ticker_list=get_market_ticker_list,
    )


@pytest.fixture
def stub_pykrx(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    fake = _fake_stock_module()
    monkeypatch.setattr(collector, "_try_import_pykrx", lambda: fake)
    return fake


@pytest.fixture
def isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path)
    return tmp_path


def test_fast_path_fetches_all_business_days(stub_pykrx, isolated_cache: Path) -> None:
    end = _dt.date(2026, 5, 14)  # Thursday
    start = end - _dt.timedelta(days=4)
    window = collector.CollectionWindow(start=start, end=end)
    df = collector.fetch_ohlcv_fast(window, cache_name="t_ohlcv")
    assert not df.empty
    # All three tickers across both markets must show up.
    assert set(df["ticker"].unique()) == {"005930", "000660", "035720"}
    # Only business days (Mon-Fri).
    assert all(pd.Timestamp(d).weekday() < 5 for d in df["date"].unique())
    # Cache file written.
    assert (isolated_cache / "t_ohlcv.parquet").exists()


def test_fast_path_uses_cache_on_second_call(stub_pykrx, isolated_cache: Path) -> None:
    window = collector.CollectionWindow(
        start=_dt.date(2026, 5, 12), end=_dt.date(2026, 5, 14)
    )
    first = collector.fetch_ohlcv_fast(window, cache_name="t_ohlcv")
    n_first = len(first)

    calls: list[str] = []
    original = stub_pykrx.get_market_ohlcv_by_ticker

    def tracking(date_str: str, market: str) -> pd.DataFrame:
        calls.append(date_str)
        return original(date_str, market)

    stub_pykrx.get_market_ohlcv_by_ticker = tracking
    second = collector.fetch_ohlcv_fast(window, cache_name="t_ohlcv")
    assert len(second) == n_first
    # No new pykrx calls because all dates were cached.
    assert calls == []


def test_fast_path_falls_back_when_pykrx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector, "_try_import_pykrx", lambda: None)
    window = collector.CollectionWindow(
        start=_dt.date(2026, 5, 12), end=_dt.date(2026, 5, 14)
    )
    df = collector.fetch_ohlcv_fast(window, cache_name="t_ohlcv_missing")
    # Synthetic fallback still returns rows so the pipeline keeps running.
    assert not df.empty
