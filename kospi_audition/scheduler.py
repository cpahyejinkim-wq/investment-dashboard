"""Daily scheduler per PRD §13.4.

Two ways to run:

  1) Crontab (recommended for production):
       30 15 * * 1-5  cd /path/to/kospi_audition && python scheduler.py once

  2) Long-running watcher (single process):
       python scheduler.py loop --time 15:30

The watcher sleeps until the next KRX close (Asia/Seoul 15:30 on weekdays),
runs ``run_analysis.py`` plus paper-trading, and dispatches alerts. The
implementation deliberately keeps dependencies minimal — no APScheduler,
just stdlib + zoneinfo so it runs anywhere Python 3.11+ does.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import subprocess
import sys
import time
import zoneinfo
from pathlib import Path

from loguru import logger

from kap.logging_setup import configure_logging

ROOT = Path(__file__).resolve().parent
KST = zoneinfo.ZoneInfo("Asia/Seoul")


def _next_close_dt(now_kst: _dt.datetime, hh: int, mm: int) -> _dt.datetime:
    target = now_kst.replace(hour=hh, minute=mm, second=0, microsecond=0)
    # Past today's window → tomorrow.
    if target <= now_kst:
        target = target + _dt.timedelta(days=1)
    # Roll forward weekends.
    while target.weekday() >= 5:
        target = target + _dt.timedelta(days=1)
    return target


def run_once(args: argparse.Namespace) -> int:
    """Run analysis once and return the subprocess exit code."""
    cmd = [sys.executable, str(ROOT / "run_analysis.py")]
    if args.with_backtest:
        cmd.append("--with-backtest")
    if args.paper_trading:
        cmd.append("--paper-trading")
    logger.info("scheduler: invoking {}", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, check=False)
    logger.info("scheduler: exit={}", proc.returncode)
    return proc.returncode


def run_loop(args: argparse.Namespace) -> None:
    hh, mm = (int(p) for p in args.time.split(":"))
    while True:
        now = _dt.datetime.now(tz=KST)
        nxt = _next_close_dt(now, hh, mm)
        secs = max(1.0, (nxt - now).total_seconds())
        logger.info("scheduler: sleeping {:.0f}s until next run at {}", secs, nxt.isoformat())
        time.sleep(secs)
        try:
            run_once(args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("scheduler: run_once raised: {}", exc)
        # Avoid double-firing within the same minute.
        time.sleep(60)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["once", "loop"], help="once = run immediately, loop = wait for close daily")
    p.add_argument("--time", default="15:30", help="KRX close (KST), default 15:30")
    p.add_argument("--with-backtest", action="store_true")
    p.add_argument("--paper-trading", action="store_true")
    args = p.parse_args()
    configure_logging("INFO")
    if args.mode == "once":
        sys.exit(run_once(args))
    run_loop(args)


if __name__ == "__main__":
    main()
