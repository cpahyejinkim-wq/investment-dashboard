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
from pathlib import Path

# Make the package importable when run from the scripts/ folder.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from kap.logging_setup import configure_logging  # noqa: E402

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


def check_raw_http() -> tuple[bool, bool]:
    """Probe the KRX endpoint that pykrx uses with a plain urllib request.

    Returns (reachable, body_ok):
      - reachable: TCP+TLS+HTTP got *any* response (including 403).
      - body_ok:   response body looked like real JSON.
    Distinguishing 403 (안티봇/헤더 부족) vs unreachable (방화벽) matters for
    the recommendation.
    """
    logger.info("=== Step 3: raw HTTPS to KRX endpoint pykrx uses ===")
    url = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    body = (
        "bld=dbms/MDC/STAT/standard/MDCSTAT01901&locale=ko_KR&mktId=STK&"
        "trdDd=" + KNOWN_GOOD_DATE.strftime("%Y%m%d") + "&share=1&money=1&csvxls_isNo=false"
    ).encode("ascii")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
            "Origin": "https://data.krx.co.kr",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
        status = resp.status
    except urllib.error.HTTPError as exc:
        logger.error(
            "  KRX endpoint reachable but rejected with HTTP {} ({}). "
            "이건 네트워크 차단이 아니라 KRX 의 anti-bot 가드입니다.", exc.code, exc.reason
        )
        return True, False
    except urllib.error.URLError as exc:
        logger.error("  KRX endpoint unreachable: {} - 방화벽/프록시/VPN 의심", exc)
        return False, False
    if not raw or len(raw.strip()) < 2:
        logger.error("  KRX endpoint returned empty body (HTTP {} {} bytes)", status, len(raw))
        return True, False
    snippet = raw[:120].decode("utf-8", errors="replace").replace("\n", " ")
    logger.info("  KRX endpoint OK (HTTP {}): {} bytes. preview: {}...", status, len(raw), snippet)
    return True, True


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


def recommend(
    network_ok: bool,
    raw_reachable: bool,
    raw_body_ok: bool,
    pykrx_ok: bool,
    fdr_ok: bool,
) -> None:
    logger.info("=== Recommendation ===")
    if pykrx_ok:
        logger.info("  ✅ pykrx 정상. verify_pykrx.py 가 실패한 건 일시적 이슈일 수 있습니다. 재시도해보세요.")
        return
    if fdr_ok:
        logger.warning("  ⚠ pykrx 는 깨졌지만 FinanceDataReader 는 정상 — 운영은 FDR 로 진행하세요.")
        logger.warning("     실행:  python run_analysis.py --collector fdr")
        logger.warning("     또는:  set KAP_COLLECTOR=fdr  (Windows)  &&  python run_analysis.py")
        return
    if not network_ok:
        logger.error("  ❌ KRX 호스트에 TCP 연결 자체가 안 됩니다. (방화벽 / VPN / DNS 의심)")
        return
    if raw_reachable and not raw_body_ok:
        logger.error("  ❌ KRX 에 닿긴 하지만 HTTP 레벨에서 거부당함 (anti-bot 가드).")
        logger.error("     - pykrx 최신 버전으로 업그레이드: pip install -U pykrx")
        logger.error("     - 그래도 안 되면 FDR 사용: pip install finance-datareader && python run_analysis.py --collector fdr")
        return
    logger.error("  ❌ 어떤 데이터 소스도 동작하지 않습니다. 네트워크/방화벽 문제일 가능성이 큽니다.")


def main() -> int:
    configure_logging("INFO")
    check_versions()
    net = check_dns_and_egress()
    if net:
        raw_reachable, raw_body_ok = check_raw_http()
    else:
        raw_reachable, raw_body_ok = False, False
    pkx = check_pykrx() if net else False
    fdr = check_finance_data_reader() if net else False
    recommend(net, raw_reachable, raw_body_ok, pkx, fdr)
    return 0 if pkx or fdr else 1


if __name__ == "__main__":
    sys.exit(main())
