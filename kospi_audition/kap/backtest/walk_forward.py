"""Walk-Forward + Out-of-Sample harness per PRD section 10.3.

Train  : 24 months
Test   : 6 months
Step   : 3 months
OOS    : 2023-01-01 onwards

The harness reports per-window test metrics for each strategy plus a
combined OOS run for the dynamic strategy.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd

from kap import config
from kap.backtest import engine


def walk_forward_windows(
    start: pd.Timestamp, end: pd.Timestamp,
    train_months: int | None = None,
    test_months: int | None = None,
    step_months: int | None = None,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Yield (train_start, test_start, test_end) tuples."""
    cfg = config.BACKTEST
    train_months = train_months or int(cfg["walk_forward_train_months"])
    test_months = test_months or int(cfg["walk_forward_test_months"])
    step_months = step_months or int(cfg["walk_forward_step_months"])
    out: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    cur = start
    while True:
        train_start = cur
        test_start = cur + pd.DateOffset(months=train_months)
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_end > end:
            break
        out.append((train_start, test_start, test_end))
        cur = cur + pd.DateOffset(months=step_months)
    return out


def run_walk_forward(
    ohlcv: pd.DataFrame, index_df: pd.DataFrame
) -> list[dict[str, object]]:
    if ohlcv.empty:
        return []
    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    start, end = df["date"].min(), df["date"].max()
    windows = walk_forward_windows(start, end)
    rows: list[dict[str, object]] = []
    for train_s, test_s, test_e in windows:
        ohlcv_test = df[(df["date"] >= test_s) & (df["date"] <= test_e)]
        idx_test = index_df.copy()
        idx_test["date"] = pd.to_datetime(idx_test["date"])
        idx_test = idx_test[(idx_test["date"] >= test_s) & (idx_test["date"] <= test_e)]
        if ohlcv_test.empty or idx_test.empty:
            continue
        results = engine.run_all(ohlcv_test, idx_test)
        for name, res in results.items():
            metrics = res.metrics(
                config.BACKTEST["commission_pct"], config.BACKTEST["slippage_pct"]
            )
            rows.append(
                {
                    "strategy": name,
                    "train_start": train_s.date().isoformat(),
                    "test_start": test_s.date().isoformat(),
                    "test_end": test_e.date().isoformat(),
                    **metrics,
                }
            )
    return rows


def run_oos(
    ohlcv: pd.DataFrame,
    index_df: pd.DataFrame,
    oos_start: _dt.date | None = None,
) -> dict[str, dict[str, float]]:
    """Out-of-sample run starting at ``oos_start`` (PRD default 2023-01-01)."""
    if ohlcv.empty:
        return {}
    cfg_start = oos_start or _dt.date.fromisoformat(config.BACKTEST["oos_start_date"])
    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    idx = index_df.copy()
    idx["date"] = pd.to_datetime(idx["date"])
    cutoff = pd.Timestamp(cfg_start)
    ohlcv_oos = df[df["date"] >= cutoff]
    idx_oos = idx[idx["date"] >= cutoff]
    if ohlcv_oos.empty:
        return {}
    results = engine.run_all(ohlcv_oos, idx_oos)
    return {
        name: res.metrics(
            config.BACKTEST["commission_pct"], config.BACKTEST["slippage_pct"]
        )
        for name, res in results.items()
    }
