"""Stage 4 tests: scheduler / notify / paper-trading / retry / regime-history."""

from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest

from kap.ops import notify, paper_trading as paper, regime_history as hist
from kap.ops.retry import retry


def test_retry_succeeds_after_failures(tmp_path) -> None:  # noqa: ARG001
    attempts = {"n": 0}

    @retry(attempts=3, initial_delay=0.01)
    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("nope")
        return "ok"

    assert flaky() == "ok"
    assert attempts["n"] == 3


def test_retry_eventually_raises() -> None:
    @retry(attempts=2, initial_delay=0.01)
    def always_fail() -> None:
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError):
        always_fail()


def test_notify_dispatch_noop_without_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "KAP_SLACK_WEBHOOK",
        "KAP_SMTP_HOST",
        "KAP_SMTP_PORT",
        "KAP_SMTP_USER",
        "KAP_SMTP_PASSWORD",
        "KAP_SMTP_FROM",
        "KAP_SMTP_TO",
    ):
        monkeypatch.delenv(k, raising=False)
    # No exception should be raised even though no channels are configured.
    notify.dispatch("test")


def test_regime_change_message() -> None:
    assert notify.build_regime_change_message("risk_on", "risk_off", "cash") is not None
    assert notify.build_regime_change_message("risk_on", "risk_on", "marathon") is None
    assert notify.build_regime_change_message(None, "risk_on", "marathon") is None


def test_mode_mismatch_message_threshold() -> None:
    # Below threshold: no alert.
    assert notify.build_mode_mismatch_message("sprint", "marathon", days=1) is None
    # At/above threshold: alert.
    assert notify.build_mode_mismatch_message("sprint", "marathon", days=3) is not None
    # Matching pair: no alert.
    assert notify.build_mode_mismatch_message("sprint", "sprint", days=10) is None
    # Cash recommendation suppressed (regime forces flat anyway).
    assert notify.build_mode_mismatch_message("sprint", "cash", days=10) is None


def test_risk_alert_message_empty() -> None:
    assert notify.build_risk_alert_message([]) is None
    msg = notify.build_risk_alert_message(
        [{"ticker": "012450", "type": "hard_stop_breach", "price": 100.0, "stop_loss": 94.0, "mode": "sprint"}]
    )
    assert "012450" in msg
    assert "hard_stop_breach" in msg


def test_regime_history_resets_streak_on_match() -> None:
    state = hist.load()
    state = {
        "previous_regime_state": "risk_on",
        "mode_mismatch_streak": 5,
        "last_active_mode": "sprint",
        "last_recommended_mode": "marathon",
        "last_run_date": "2026-05-10",
    }
    new_state, prev, streak = hist.update(
        state,
        _dt.date(2026, 5, 11),
        current_regime_state="risk_on",
        active_mode="marathon",
        recommended_mode="marathon",
    )
    assert prev == "risk_on"
    assert streak == 0
    assert new_state["mode_mismatch_streak"] == 0


def test_regime_history_increments_streak_on_consistent_mismatch() -> None:
    state = {
        "previous_regime_state": "risk_on",
        "mode_mismatch_streak": 1,
        "last_active_mode": "sprint",
        "last_recommended_mode": "marathon",
        "last_run_date": "2026-05-10",
    }
    new_state, _, streak = hist.update(
        state,
        _dt.date(2026, 5, 11),
        current_regime_state="risk_on",
        active_mode="sprint",
        recommended_mode="marathon",
    )
    assert streak == 2
    assert new_state["mode_mismatch_streak"] == 2


def test_paper_trading_buys_then_liquidates() -> None:
    state = paper.load_state() if False else {
        "started_at": None,
        "cash": 10_000_000.0,
        "holdings": {},
        "nav_history": [],
        "trades": [],
    }
    day1 = pd.DataFrame(
        [
            {"ticker": "T1", "tier": "S", "weight": 0.10, "current_price": 100.0},
            {"ticker": "T2", "tier": "A", "weight": 0.05, "current_price": 200.0},
        ]
    )
    state = paper.rebalance(state, day1, "sprint", "2026-05-14", ["S", "A", "B"])
    assert "T1" in state["holdings"]
    assert "T2" in state["holdings"]
    assert state["nav_history"][-1]["nav"] > 0.0
    initial_cash = state["cash"]

    # Day 2: T2 drops out of ranking → must be liquidated.
    day2 = pd.DataFrame(
        [{"ticker": "T1", "tier": "S", "weight": 0.10, "current_price": 110.0}]
    )
    state = paper.rebalance(state, day2, "sprint", "2026-05-15", ["S", "A", "B"])
    assert "T2" not in state["holdings"]
    assert state["cash"] > initial_cash  # received liquidation proceeds


def test_paper_trading_holds_all_cash_when_no_allowed_tiers() -> None:
    state = {
        "started_at": None,
        "cash": 5_000_000.0,
        "holdings": {},
        "nav_history": [],
        "trades": [],
    }
    rank = pd.DataFrame(
        [{"ticker": "T1", "tier": "S", "weight": 0.10, "current_price": 100.0}]
    )
    state = paper.rebalance(state, rank, "sprint", "2026-05-14", [])
    assert state["holdings"] == {}
    assert state["cash"] == 5_000_000.0
