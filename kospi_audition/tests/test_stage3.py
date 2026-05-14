"""Stage 3 tests: DART fallback, quality gate, PEAD, sector power, leader, vol-adj, backtest."""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from kap import config
from kap.backtest import engine as bt_engine
from kap.backtest import walk_forward as wf
from kap.data import collector
from kap.data import fundamentals as fund_mod
from kap.factors import earnings, quality
from kap.portfolio import vol_weight
from kap.ranking import leader_score, sector_power


@pytest.fixture(scope="module")
def synth() -> tuple[pd.DataFrame, pd.DataFrame]:
    end = _dt.date(2026, 5, 14)
    start = end - _dt.timedelta(days=400)
    win = collector.CollectionWindow(start=start, end=end)
    return collector._synthetic_ohlcv(win), collector._synthetic_index(win)


def test_synthetic_fundamentals_schema() -> None:
    f = fund_mod.synthetic_fundamentals(["000001", "000002"], _dt.date(2026, 5, 14))
    needed = {
        "ticker", "fiscal_quarter", "revenue", "operating_profit", "net_profit",
        "roe", "debt_ratio", "announcement_date",
    }
    assert needed.issubset(f.columns)
    assert len(f) >= 8  # 2 tickers * 8 quarters


def test_quality_gate_marathon_demotes_weak_s() -> None:
    fund = pd.DataFrame(
        [
            {"ticker": "T1", "fiscal_quarter": "2026Q1", "revenue": 100, "operating_profit": -10,
             "net_profit": -8, "roe": -0.05, "debt_ratio": 400, "announcement_date": _dt.date(2026, 3, 15)},
            {"ticker": "T2", "fiscal_quarter": "2026Q1", "revenue": 100, "operating_profit": 20,
             "net_profit": 15, "roe": 0.15, "debt_ratio": 80, "announcement_date": _dt.date(2026, 3, 15)},
        ]
    )
    q = quality.evaluate_quality(fund)
    ranking = pd.DataFrame(
        [
            {"ticker": "T1", "tier": "S"},
            {"ticker": "T2", "tier": "S"},
        ]
    )
    gated = quality.apply_quality_gate(ranking, q, mode="marathon")
    # T1 must be demoted (negative op profit + high debt).
    assert gated.loc[gated["ticker"] == "T1", "tier"].iloc[0] == "B"
    assert gated.loc[gated["ticker"] == "T2", "tier"].iloc[0] == "S"


def test_quality_gate_sprint_lenient_on_s() -> None:
    fund = pd.DataFrame(
        [
            {"ticker": "T1", "fiscal_quarter": "2026Q1", "revenue": 100, "operating_profit": -10,
             "net_profit": -8, "roe": -0.05, "debt_ratio": 80, "announcement_date": _dt.date(2026, 3, 15)},
        ]
    )
    q = quality.evaluate_quality(fund)
    ranking = pd.DataFrame([{"ticker": "T1", "tier": "S"}])
    gated = quality.apply_quality_gate(ranking, q, mode="sprint")
    # Sprint S bypasses op-profit check per PRD §6.5.
    assert gated.loc[gated["ticker"] == "T1", "tier"].iloc[0] == "S"


def test_earnings_drift_returns_pct(synth: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, idx = synth
    kospi = idx[idx["index_name"] == "KOSPI"].set_index(
        pd.to_datetime(idx[idx["index_name"] == "KOSPI"]["date"])
    )["close"]
    fund = fund_mod.synthetic_fundamentals(list(ohlcv["ticker"].unique())[:50], _dt.date(2026, 5, 14))
    out = earnings.compute_earnings_drift(ohlcv, kospi, fund)
    if not out.empty:
        assert "earnings_drift_pct" in out.columns
        assert out["earnings_drift_pct"].between(0, 100).all()


def test_sector_power_ranking() -> None:
    ranking = pd.DataFrame(
        {
            "ticker": [f"T{i:03d}" for i in range(8)],
            "sector": ["A", "A", "A", "B", "B", "C", "C", "C"],
            "tier": ["S", "A", "B", "S", "C", "A", "B", "D"],
            "mode_score_pct": [99, 95, 80, 98, 60, 92, 75, 30],
        }
    )
    dates = pd.date_range("2026-01-01", periods=80, freq="B")
    rows = []
    for tk in ranking["ticker"]:
        for d in dates:
            rows.append({"ticker": tk, "date": d, "trade_value": float(np.random.default_rng(0).random())})
    ohlcv = pd.DataFrame(rows)
    sp = sector_power.compute_sector_power(ranking, ohlcv)
    assert {"sector_power", "sector_rs_pct", "new_leader_count"}.issubset(sp.columns)
    # Sector A and B should have non-trivial power (both contain S/A tiers).
    assert sp["sector_power"].max() > 0


def test_leader_score_no_history_defaults_to_score_only() -> None:
    ranking = pd.DataFrame({"ticker": ["T1", "T2"], "mode_score_pct": [80.0, 40.0]})
    out = leader_score.compute_leader_score(ranking, tier_history=None)
    # With no history, survival_weighted_pct collapses to neutral 50.
    assert "leader_score" in out.columns
    # Ranking by leader_score must agree with mode_score_pct ordering.
    sorted_tickers = out.sort_values("leader_score", ascending=False)["ticker"].tolist()
    assert sorted_tickers == ["T1", "T2"]


def test_vol_adjusted_weight_noop_when_disabled() -> None:
    ranking = pd.DataFrame({"ticker": ["T1"], "weight": [0.05]})
    ohlcv = pd.DataFrame({"ticker": ["T1"] * 5, "date": pd.date_range("2026-01-01", periods=5), "close": [100, 101, 99, 102, 103]})
    out = vol_weight.adjust_weights(ranking, ohlcv)
    assert float(out["weight"].iloc[0]) == 0.05


def test_backtest_buy_and_hold_metrics(synth: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    _, idx = synth
    res = bt_engine.buy_and_hold(idx, "KOSPI")
    metrics = res.metrics(
        config.BACKTEST["commission_pct"], config.BACKTEST["slippage_pct"]
    )
    assert {"cagr", "mdd", "sharpe", "monthly_win_rate", "annual_turnover"}.issubset(metrics.keys())
    # KOSPI buy-and-hold has zero turnover.
    assert metrics["annual_turnover"] == 0.0


def test_walk_forward_window_generation() -> None:
    start = pd.Timestamp("2020-01-01")
    end = pd.Timestamp("2024-06-30")
    wins = wf.walk_forward_windows(start, end, train_months=12, test_months=6, step_months=3)
    assert len(wins) > 0
    for train_s, test_s, test_e in wins:
        assert (test_s - train_s).days >= 360
        assert (test_e - test_s).days >= 175
