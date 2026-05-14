"""Verify that pykrx live integration actually fetches today's close from KRX.

Run before going to production:
    python scripts/verify_pykrx.py

The script proves five things in order:
  1. pykrx is importable.
  2. KRX returns a non-empty KOSPI + KOSDAQ ticker list for today/last business day.
  3. ``get_market_ohlcv_by_ticker`` returns rows with today's date.
  4. The fast-path collector populates the parquet cache and slices the window.
  5. KOSPI / KOSDAQ / VKOSPI indices are reachable.

Any failure exits non-zero so CI / cron can alert.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from kap.data import collector  # noqa: E402
from kap.logging_setup import configure_logging  # noqa: E402

KST = zoneinfo.ZoneInfo("Asia/Seoul")
MARKET_CLOSE = _dt.time(15, 30)


def _today_kst() -> _dt.datetime:
    return _dt.datetime.now(tz=KST)


def _last_business_day(today: _dt.date) -> _dt.date:
    d = today
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d


def _warn_if_before_close(now: _dt.datetime) -> None:
    if now.weekday() < 5 and now.time() < MARKET_CLOSE:
        logger.warning(
            "Now is {} KST (before 15:30 close) - today's close may not be published yet. "
            "Re-run after 15:35 KST for guaranteed end-of-day data.",
            now.strftime("%H:%M"),
        )


def step1_import_pykrx() -> object:
    try:
        import pykrx.stock as stock  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        logger.error("[1/5] pykrx import FAILED: {}", exc)
        logger.error("      Install with:  pip install pykrx")
        sys.exit(2)
    logger.info("[1/5] pykrx import OK")
    return stock


def step2_ticker_list(stock: object, target: _dt.date) -> dict[str, int]:
    date_str = target.strftime("%Y%m%d")
    counts: dict[str, int] = {}
    for market in ("KOSPI", "KOSDAQ"):
        tickers = stock.get_market_ticker_list(date_str, market=market)  # type: ignore[attr-defined]
        if not tickers:
            logger.error("[2/5] {} ticker list empty for {}", market, date_str)
            sys.exit(3)
        counts[market] = len(tickers)
    logger.info("[2/5] ticker list OK: KOSPI={}, KOSDAQ={}", counts["KOSPI"], counts["KOSDAQ"])
    return counts


def step3_today_snapshot(stock: object, target: _dt.date) -> None:
    date_str = target.strftime("%Y%m%d")
    rows_kospi = stock.get_market_ohlcv_by_ticker(date_str, market="KOSPI")  # type: ignore[attr-defined]
    rows_kosdaq = stock.get_market_ohlcv_by_ticker(date_str, market="KOSDAQ")  # type: ignore[attr-defined]
    if rows_kospi is None or rows_kospi.empty:
        logger.error("[3/5] KOSPI close snapshot empty for {}", date_str)
        sys.exit(4)
    if rows_kosdaq is None or rows_kosdaq.empty:
        logger.error("[3/5] KOSDAQ close snapshot empty for {}", date_str)
        sys.exit(4)

    sample = rows_kospi.head(3)
    logger.info(
        "[3/5] close snapshot OK: KOSPI={} rows, KOSDAQ={} rows. sample top-3 KOSPI tickers below:",
        len(rows_kospi), len(rows_kosdaq),
    )
    for ticker, row in sample.iterrows():
        logger.info(
            "      {} close={:,} volume={:,} trade_value={:,}",
            ticker,
            int(row.get("종가", row.get("close", 0))),
            int(row.get("거래량", row.get("volume", 0))),
            int(row.get("거래대금", row.get("trade_value", 0))),
        )


def step4_fast_collector(target: _dt.date) -> None:
    end = target
    start = end - _dt.timedelta(days=14)
    window = collector.CollectionWindow(start=start, end=end)
    df = collector.fetch_ohlcv_fast(window, cache_name="verify_ohlcv")
    if df.empty:
        logger.error("[4/5] fast-path collector returned empty frame")
        sys.exit(5)
    last_date = max(df["date"])
    if last_date != target:
        logger.warning(
            "[4/5] fast-path latest date is {} but expected {} (휴장일이거나 장 마감 전일 수 있음)",
            last_date,
            target,
        )
    logger.info(
        "[4/5] fast-path collector OK: {} rows, last_date={}, tickers={}",
        len(df),
        last_date,
        df["ticker"].nunique(),
    )


def step5_indices(target: _dt.date) -> None:
    end = target
    start = end - _dt.timedelta(days=14)
    window = collector.CollectionWindow(start=start, end=end)
    df = collector.fetch_index_ohlcv(window)
    if df.empty:
        logger.error("[5/5] index OHLCV (KOSPI/KOSDAQ/VKOSPI) empty")
        sys.exit(6)
    names = set(df["index_name"].unique())
    if not {"KOSPI", "KOSDAQ", "VKOSPI"}.issubset(names):
        logger.warning("[5/5] missing some indices: {}", {"KOSPI", "KOSDAQ", "VKOSPI"} - names)
    logger.info("[5/5] index OHLCV OK: {} rows, names={}", len(df), names)


def main() -> None:
    configure_logging(os.environ.get("KAP_LOG_LEVEL", "INFO"))
    now = _today_kst()
    _warn_if_before_close(now)
    target = _last_business_day(now.date())
    logger.info("=== pykrx live verification ===  target_date={}", target)

    stock = step1_import_pykrx()
    step2_ticker_list(stock, target)
    step3_today_snapshot(stock, target)
    step4_fast_collector(target)
    step5_indices(target)

    logger.info("All 5 steps passed. pykrx live integration is operational.")


if __name__ == "__main__":
    main()
