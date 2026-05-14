"""Isolate where KRX data fetching is failing.

When ``verify_pykrx.py`` reports that even a known-good past date returns
empty, the problem is one of:

  A. Network egress blocked     (firewall / proxy / corporate VPN)
  B. pykrx version incompatible with current KRX site
  C. KRX added anti-bot guard (User-Agent / cookie) that pykrx doesn't pass
  D. FinanceDataReader (alternative source) also broken → really a network issue

This script tries each layer separately so the user knows exactly which
fix to apply.

Run::

    python scripts/diagnose_data_source.py
"""

from __future__ import annotations

import datetime as _dt
import importlib.metadata as _meta
import socket
import sys
import urllib.error
import urllib.request

from loguru import logger

from kap.logging_setup import configure_logging

KNOWN_GOOD_DATE = _dt.date(2024, 1, 2)  # KRX trading day, far in the past


def _version(pkg: str) -> str:
    try:
        return _meta.version(pkg)
    except Exception:  # noqa: BLE001
        return "NOT INSTALLED"


def check_versions() -> None:
    logger.info("=== Step 1: package versions ===")
    for pkg in ("pykrx", "FinanceDataReader", "pandas", "requests"):
        logger.info("  {:<22} {}", pkg, _version(pkg))


def check_dns_and_egress() -> bool:
    """Plain TCP/HTTPS reachability test."""
    logger.info("=== Step 2: network egress to KRX ===")
    targets = [
        ("data.krx.co.kr", 443),         # used by pykrx
        ("www.krx.co.kr", 443),
    ]
    ok = True
    for host, port in targets:
        try:
            socket.gethostbyname(host)
        except Exception as exc:  # noqa: BLE001
            logger.error("  DNS resolve FAILED for {} ({}). Check DNS / VPN.", host, exc)
            ok = False
            continue
        try:
            with socket.create_connection((host, port), timeout=5) as _:
                logger.info("  TCP {}:{} reachable", host, port)
        except Exception as exc:  # noqa: BLE001
            logger.error("  TCP connect FAILED for {}:{} ({}). Firewall / proxy?", host, port, exc)
            ok = False
    return ok


def check_raw_http() -> bool:
    """Pull the KRX endpoint that pykrx uses with a plain urllib request."""
    logger.info("=== Step 3: raw HTTPS to KRX endpoint pykrx uses ===")
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    body = (
        "bld=dbms/MDC/STAT/standard/MDCSTAT01901&locale=ko_KR&mktId=STK&"
        "trdDd=" + KNOWN_GOOD_DATE.strftime("%Y%m%d") + "&share=1&money=1&csvxls_isNo=false"
    ).encode("ascii")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
    except urllib.error.URLError as exc:
        logger.error("  KRX endpoint unreachable: {}", exc)
        return False
    if not raw or len(raw.strip()) < 2:
        logger.error("  KRX endpoint returned empty body ({} bytes) - 안티봇 또는 endpoint deprecation 의심", len(raw))
        return False
    snippet = raw[:120].decode("utf-8", errors="replace").replace("\n", " ")
    logger.info("  KRX endpoint OK: {} bytes. preview: {}...", len(raw), snippet)
    return True


def check_pykrx() -> bool:
    logger.info("=== Step 4: pykrx live call ===")
    try:
        import pykrx.stock as stock  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        logger.error("  pykrx import failed: {}", exc)
        return False
    date_str = KNOWN_GOOD_DATE.strftime("%Y%m%d")
    try:
        tickers = stock.get_market_ticker_list(date_str, market="KOSPI")
    except Exception as exc:  # noqa: BLE001
        logger.error("  pykrx call raised: {}", exc)
        return False
    if not tickers:
        logger.error("  pykrx returned empty list for known good date {} - pykrx 버전이 KRX 변경에 못 맞춰진 상태", KNOWN_GOOD_DATE)
        logger.error("  → 시도: pip install -U pykrx  (현재 버전: {})", _version("pykrx"))
        return False
    logger.info("  pykrx OK: {} KOSPI tickers for {}", len(tickers), KNOWN_GOOD_DATE)
    return True


def check_finance_data_reader() -> bool:
    """Alternative source - if pykrx is broken, FDR usually still works."""
    logger.info("=== Step 5: FinanceDataReader (alternative source) ===")
    try:
        import FinanceDataReader as fdr  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        logger.warning("  FinanceDataReader not installed. To use it as a backup:")
        logger.warning("    pip install finance-datareader")
        return False
    try:
        df = fdr.DataReader("005930", "2024-01-02", "2024-01-05")
    except Exception as exc:  # noqa: BLE001
        logger.error("  FDR call raised: {}", exc)
        return False
    if df is None or df.empty:
        logger.error("  FDR returned empty frame")
        return False
    last_close = float(df["Close"].iloc[-1])
    logger.info("  FDR OK: 005930 close near 2024-01-02 = {:,.0f}", last_close)
    return True


def recommend(network_ok: bool, raw_ok: bool, pykrx_ok: bool, fdr_ok: bool) -> None:
    logger.info("=== Recommendation ===")
    if pykrx_ok:
        logger.info("  ✅ pykrx 가 정상 동작합니다. verify_pykrx.py 가 실패한 건 일시적 이슈일 수 있습니다. 재시도해보세요.")
        return
    if not network_ok or not raw_ok:
        logger.error("  ❌ KRX 자체에 접속이 안 됩니다. (방화벽 / 사내 프록시 / VPN 의심)")
        logger.error("     - 회사 네트워크라면 IT 담당자에게 data.krx.co.kr 허용 요청")
        logger.error("     - 개인 네트워크라면 백신/방화벽 일시 해제 후 재시도")
        return
    if fdr_ok:
        logger.warning("  ⚠ pykrx 는 깨졌지만 FinanceDataReader 는 정상. FDR 기반 collector 로 전환을 권장합니다.")
        logger.warning("     - 추후 추가될 `--collector fdr` 옵션이 활성화되면 그것을 사용")
        logger.warning("     - 또는 pip install -U pykrx 한 번 더 시도")
        return
    logger.error("  ❌ 어떤 데이터 소스도 동작하지 않습니다. 네트워크/방화벽 문제일 가능성이 매우 큽니다.")


def main() -> int:
    configure_logging("INFO")
    check_versions()
    net = check_dns_and_egress()
    raw = check_raw_http() if net else False
    pkx = check_pykrx() if net else False
    fdr = check_finance_data_reader() if net else False
    recommend(net, raw, pkx, fdr)
    return 0 if pkx or fdr else 1


if __name__ == "__main__":
    sys.exit(main())
