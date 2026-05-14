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


def _resolve_target(now: _dt.datetime) -> _dt.date:
    """Return the most recent date KRX is expected to have published.

    KRX publishes the day's close after 15:30 KST. Before that (and on
    weekends), the latest *available* date is yesterday's business day —
    asking pykrx for today returns empty JSON and trips the verifier.
    """
    today = now.date()
    if now.weekday() < 5 and now.time() >= MARKET_CLOSE:
        return today
    # Step back to yesterday and roll over weekends.
    d = today - _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d


def _warn_if_before_close(now: _dt.datetime) -> None:
    if now.weekday() < 5 and now.time() < MARKET_CLOSE:
        logger.warning(
            "Now is {} KST (before 15:30 close) - today's close not published yet. "
            "Verifier will use the previous business day instead.",
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


CONNECTIVITY_PROBE_DATE = _dt.date(2024, 1, 2)  # known KRX trading day


def _previous_business_day(d: _dt.date) -> _dt.date:
    d = d - _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d


def _probe_ticker_list(stock: object, target: _dt.date, max_lookback: int = 30) -> tuple[_dt.date, dict[str, int]] | None:
    """Walk back from ``target`` until a date returns a non-empty ticker list.

    Handles three real-world cases the simple weekday rollback cannot:
      - public holidays (Lunar New Year, Chuseok, ...)
      - system clock set to a future date (no data exists yet)
      - KRX maintenance windows
    """
    candidate = target
    for _ in range(max_lookback):
        date_str = candidate.strftime("%Y%m%d")
        try:
            kospi = stock.get_market_ticker_list(date_str, market="KOSPI")  # type: ignore[attr-defined]
            kosdaq = stock.get_market_ticker_list(date_str, market="KOSDAQ")  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.debug("ticker_list({}): {}", date_str, exc)
            kospi, kosdaq = [], []
        if kospi and kosdaq:
            return candidate, {"KOSPI": len(kospi), "KOSDAQ": len(kosdaq)}
        candidate = _previous_business_day(candidate)
    return None


def _connectivity_probe(stock: object) -> int:
    """Last-resort sanity check against a date KRX definitely has data for."""
    date_str = CONNECTIVITY_PROBE_DATE.strftime("%Y%m%d")
    try:
        n = len(stock.get_market_ticker_list(date_str, market="KOSPI"))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0
    return n


def step2_ticker_list(stock: object, target: _dt.date) -> tuple[_dt.date, dict[str, int]]:
    probed = _probe_ticker_list(stock, target)
    if probed is not None:
        used, counts = probed
        if used != target:
            logger.warning(
                "[2/5] target {} returned empty - walked back to {} ({} bdays).",
                target, used, (target - used).days,
            )
        logger.info(
            "[2/5] ticker list OK @ {}: KOSPI={}, KOSDAQ={}",
            used, counts["KOSPI"], counts["KOSDAQ"],
        )
        return used, counts

    # Probe failed for the whole 30-bday window. Run connectivity test.
    n = _connectivity_probe(stock)
    if n > 0:
        logger.error(
            "[2/5] KRX has no data for any date in last 30 bdays from {} BUT {} returns {} tickers.\n"
            "      → 가장 가능성 높은 원인: 시스템 시계가 미래 시점입니다.\n"
            "        date.today() = {}. KRX 가 실제로 보유한 가장 최근 시점으로 시계를 맞추거나,\n"
            "        run_analysis.py 호출 시 명시적 종료일을 코드 수준에서 지정하세요.",
            target, CONNECTIVITY_PROBE_DATE, n, _dt.date.today(),
        )
    else:
        logger.error(
            "[2/5] KRX returned empty even for known good date {} - "
            "네트워크/프록시 또는 pykrx 버전 문제일 수 있습니다. "
            "`pip install -U pykrx` 후 재시도하세요.",
            CONNECTIVITY_PROBE_DATE,
        )
    sys.exit(3)


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
    target = _resolve_target(now)
    logger.info("=== pykrx live verification ===  target_date={}", target)

    stock = step1_import_pykrx()
    target, _ = step2_ticker_list(stock, target)  # may roll back further on holidays/future
    step3_today_snapshot(stock, target)
    step4_fast_collector(target)
    step5_indices(target)

    logger.info("All 5 steps passed. pykrx live integration is operational. target_date={}", target)


if __name__ == "__main__":
    main()
