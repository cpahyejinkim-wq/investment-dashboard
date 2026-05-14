"""Verify the active data source actually delivers a recent KRX close.

How it works:

  1. Pick the data source from --collector (or env KAP_COLLECTOR, default
     pykrx). Try pykrx first; if it fails, try FDR.
  2. Walk *backward* one business day at a time from today (KST) — never
     asking for a hard-coded ancient date — until a probe call succeeds.
  3. Report the latest available date + a 3-ticker sample close so the user
     can eyeball it against 네이버 금융.

Exit codes:
  0 — at least one source returned data for a recent (<=30 bday) date.
  2 — no data source returned data within the lookback window.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from kap.data.calendar import find_latest_trading_day  # noqa: E402
from kap.logging_setup import configure_logging  # noqa: E402

KST = zoneinfo.ZoneInfo("Asia/Seoul")
MARKET_CLOSE = _dt.time(15, 30)
MAX_LOOKBACK = 30


# ---------------------------------------------------------------------------
# Helpers shared by both probes
# ---------------------------------------------------------------------------


def _hint_date(now: _dt.datetime) -> _dt.date:
    """Walk back from today if it's a weekend or before market close."""
    today = now.date()
    if now.weekday() < 5 and now.time() >= MARKET_CLOSE:
        return today
    d = today - _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# pykrx probe
# ---------------------------------------------------------------------------


def _try_pykrx() -> object | None:
    try:
        import pykrx.stock as stock  # type: ignore[import-not-found]
        return stock
    except Exception as exc:  # noqa: BLE001
        logger.warning("pykrx import failed: {}", exc)
        return None


def _pykrx_probe(stock: object, d: _dt.date) -> bool:
    try:
        tickers = stock.get_market_ticker_list(d.strftime("%Y%m%d"), market="KOSPI")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False
    return bool(tickers)


def _pykrx_sample(stock: object, d: _dt.date) -> int:
    """Return KOSPI ticker count + log 3-sample close."""
    date_str = d.strftime("%Y%m%d")
    df = stock.get_market_ohlcv_by_ticker(date_str, market="KOSPI")  # type: ignore[attr-defined]
    if df is None or df.empty:
        return 0
    sample = df.head(3)
    for ticker, row in sample.iterrows():
        logger.info(
            "    {} close={:,} volume={:,}",
            ticker,
            int(row.get("종가", row.get("close", 0))),
            int(row.get("거래량", row.get("volume", 0))),
        )
    return len(df)


def verify_via_pykrx(hint: _dt.date) -> _dt.date | None:
    stock = _try_pykrx()
    if stock is None:
        return None
    found = find_latest_trading_day(lambda d: _pykrx_probe(stock, d), hint, MAX_LOOKBACK)
    if not found:
        logger.error(
            "  pykrx returned empty for every business day from {} back to {} bdays. "
            "pykrx 가 KRX anti-bot 에 막혀 있을 가능성이 높습니다.",
            hint, MAX_LOOKBACK,
        )
        return None
    if found != hint:
        logger.warning("  pykrx: target {} empty - walked back to {}", hint, found)
    logger.info("  pykrx latest available date: {}", found)
    n = _pykrx_sample(stock, found)
    logger.info("  pykrx sample on {}: {} KOSPI tickers (top 3 above)", found, n)
    return found


# ---------------------------------------------------------------------------
# FDR probe
# ---------------------------------------------------------------------------


def _try_fdr() -> object | None:
    try:
        import FinanceDataReader as fdr  # type: ignore[import-not-found]
        return fdr
    except Exception as exc:  # noqa: BLE001
        logger.warning("FinanceDataReader import failed: {}", exc)
        return None


def _fdr_probe(fdr: object, d: _dt.date) -> bool:
    """Probe a single date by fetching a bellwether stock (Samsung 005930)."""
    try:
        df = fdr.DataReader("005930", d, d)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False
    return df is not None and not df.empty


def _fdr_sample(fdr: object, d: _dt.date) -> None:
    samples = [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("035720", "카카오")]
    for tk, name in samples:
        try:
            df = fdr.DataReader(tk, d, d)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("    {} ({}): fetch raised {}", tk, name, exc)
            continue
        if df is None or df.empty:
            logger.warning("    {} ({}): empty for {}", tk, name, d)
            continue
        close = float(df["Close"].iloc[-1])
        volume = int(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0
        logger.info("    {} ({}) close={:,.0f} volume={:,}", tk, name, close, volume)


def verify_via_fdr(hint: _dt.date) -> _dt.date | None:
    fdr = _try_fdr()
    if fdr is None:
        logger.warning("  FDR not installed (pip install finance-datareader)")
        return None
    found = find_latest_trading_day(lambda d: _fdr_probe(fdr, d), hint, MAX_LOOKBACK)
    if not found:
        logger.error(
            "  FDR returned empty for every business day from {} back to {} bdays.",
            hint, MAX_LOOKBACK,
        )
        return None
    if found != hint:
        logger.warning("  FDR: target {} empty - walked back to {}", hint, found)
    logger.info("  FDR latest available date: {}", found)
    _fdr_sample(fdr, found)
    return found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--collector",
        choices=["pykrx", "fdr", "auto"],
        default=os.environ.get("KAP_COLLECTOR", "auto"),
        help="Which data source to verify. 'auto' tries pykrx then FDR.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    configure_logging("INFO")
    now = _dt.datetime.now(tz=KST)
    if now.weekday() < 5 and now.time() < MARKET_CLOSE:
        logger.warning(
            "Now is {} KST (before 15:30 close) - today's close not published yet. "
            "Walking back from yesterday.",
            now.strftime("%H:%M"),
        )
    hint = _hint_date(now)
    logger.info("=== KRX live verification ===  system_today={}  hint_date={}", now.date(), hint)

    pykrx_date: _dt.date | None = None
    fdr_date: _dt.date | None = None

    if args.collector in ("pykrx", "auto"):
        logger.info("--- pykrx probe ---")
        pykrx_date = verify_via_pykrx(hint)
    if args.collector in ("fdr", "auto"):
        logger.info("--- FDR probe ---")
        fdr_date = verify_via_fdr(hint)

    logger.info("=== Summary ===")
    logger.info("  pykrx latest date: {}", pykrx_date or "FAILED")
    logger.info("  FDR   latest date: {}", fdr_date or "FAILED")

    if pykrx_date:
        logger.info("✅ pykrx is operational. Run:  python run_analysis.py")
        return 0
    if fdr_date:
        logger.warning(
            "⚠ pykrx unavailable but FDR is operational. Run:  "
            "python run_analysis.py --collector fdr"
        )
        return 0
    logger.error(
        "❌ Neither source returned data within {} business days of {}. "
        "Run scripts/diagnose_data_source.py for a deeper breakdown.",
        MAX_LOOKBACK, hint,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
