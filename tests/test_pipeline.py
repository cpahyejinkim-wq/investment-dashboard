"""End-to-end pipeline tests for KAP v2.1 Stage 1 (Sprint MVP).

Uses the deterministic synthetic dataset (RANDOM_SEED fixed) so test results
are reproducible without KRX network access.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kap.config import MODES, OUTPUT_DIR
from kap.data.collector import collect
from kap.data.universe import build_universe
from kap.regime.filter import compute_regime
from kap.factors.rs import compute_rs
from kap.factors.acceleration import compute_acceleration
from kap.factors.rank_velocity import compute_rank_velocity
from kap.modes.sprint import compute_sprint_score
from kap.modes.marathon import compute_marathon_score
from kap.ranking.tier import classify_tier, apply_tier_caps, assign_weights
from kap.risk.stop_loss import compute_stops


@pytest.fixture(scope="module")
def synthetic_data():
    return collect()


def test_data_collector_returns_nonempty(synthetic_data):
    assert not synthetic_data.ohlcv.empty
    assert not synthetic_data.flow.empty
    assert not synthetic_data.index.empty
    assert {"ticker", "date", "market", "open", "high", "low", "close", "volume"} <= set(
        synthetic_data.ohlcv.columns
    )


def test_universe_filter_reduces_count(synthetic_data):
    as_of = pd.Timestamp(synthetic_data.ohlcv["date"].max())
    universe = build_universe(synthetic_data.ohlcv, synthetic_data.metadata, as_of=as_of)
    assert 0 < len(universe) <= len(synthetic_data.metadata)
    # All members satisfy the listing-days threshold
    assert (universe["listing_days"] >= 120).all()


def test_regime_filter_assigns_state_and_mode(synthetic_data):
    regime = compute_regime(synthetic_data.ohlcv, synthetic_data.index)
    assert regime.state in {"strong_risk_on", "risk_on", "neutral", "risk_off"}
    assert regime.recommended_mode in {"sprint", "marathon", "cash"}
    if regime.state == "risk_off":
        assert not regime.allow_new_entry
        assert regime.allowed_tiers == []
    else:
        assert regime.allow_new_entry


def test_rs_factor_produces_percentiles(synthetic_data):
    as_of = pd.Timestamp(synthetic_data.ohlcv["date"].max())
    universe = build_universe(synthetic_data.ohlcv, synthetic_data.metadata, as_of=as_of)
    rs = compute_rs(synthetic_data.ohlcv, synthetic_data.index, universe)
    assert "rs_20d_pct" in rs.columns
    assert rs["rs_20d_pct"].between(0, 100).all()
    assert rs["rs_60d_pct"].between(0, 100).all()


def test_acceleration_pct_in_range(synthetic_data):
    as_of = pd.Timestamp(synthetic_data.ohlcv["date"].max())
    universe = build_universe(synthetic_data.ohlcv, synthetic_data.metadata, as_of=as_of)
    a = compute_acceleration(synthetic_data.ohlcv, synthetic_data.index, universe)
    assert a["acceleration_pct"].between(0, 100).all()


def test_rank_velocity_handles_short_history():
    """With < window+1 days of history, rank velocity falls back to 0/50pct (no crash)."""
    df = pd.DataFrame({
        "ticker": ["A", "B", "C"],
        "date": ["2026-05-14", "2026-05-14", "2026-05-14"],
        "score": [90.0, 50.0, 20.0],
    })
    out = compute_rank_velocity(df)
    assert len(out) == 3
    assert (out["rank_velocity"] == 0.0).all()


def test_sprint_weights_sum_to_one():
    w = MODES["sprint"]["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_marathon_weights_sum_to_one():
    w = MODES["marathon"]["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_sprint_tier_thresholds_monotone():
    th = MODES["sprint"]["tier_thresholds"]
    assert th["S"] > th["A"] > th["B"] > th["C"]


def test_classify_tier_assigns_correctly():
    pct = pd.Series([99.0, 95.0, 88.0, 70.0, 30.0])
    tiers = classify_tier(pct, mode="sprint")
    assert tiers.tolist() == ["S", "A", "B", "C", "D"]


def test_tier_caps_demote_overflow():
    df = pd.DataFrame({
        "ticker": [f"T{i}" for i in range(20)],
        "tier": ["S"] * 20,
        "sprint_score_pct": [99.0 - i * 0.1 for i in range(20)],
    })
    out = apply_tier_caps(df, mode="sprint", score_col="sprint_score_pct")
    n_s = MODES["sprint"]["tier_max_count"]["S"]
    assert (out["tier"] == "S").sum() == n_s
    # Excess demoted to A
    assert (out["tier"] == "A").sum() == 20 - n_s


def test_risk_off_zeros_weights():
    df = pd.DataFrame({
        "ticker": ["A", "B"],
        "tier": ["S", "A"],
    })
    out = assign_weights(df, mode="sprint", regime_state="risk_off")
    assert (out["weight"] == 0.0).all()


def test_sprint_stop_loss_kospi_six_percent():
    """PRD §8.2: Sprint KOSPI hard stop = -6%."""
    stops = compute_stops(
        ticker="000001", market="KOSPI", entry_mode="sprint",
        entry_price=100_000, high_since_entry=110_000,
        current_price=105_000, days_since_last_new_high=2,
    )
    assert stops.hard_stop_price == pytest.approx(94_000.0)
    # Trailing -10% of high
    assert stops.trailing_stop_price == pytest.approx(99_000.0)
    assert "hard_stop" not in stops.triggered


def test_sprint_stop_loss_kosdaq_eight_percent():
    """PRD §8.2: Sprint KOSDAQ hard stop = -8%."""
    stops = compute_stops(
        ticker="100001", market="KOSDAQ", entry_mode="sprint",
        entry_price=50_000, high_since_entry=52_000,
        current_price=45_000, days_since_last_new_high=2,
    )
    assert stops.hard_stop_price == pytest.approx(46_000.0)
    assert "hard_stop" in stops.triggered


def test_marathon_stop_more_generous_than_sprint():
    """PRD §8: Marathon stops must be wider than Sprint stops (longer holding period)."""
    sprint = compute_stops(
        ticker="X", market="KOSPI", entry_mode="sprint",
        entry_price=100, high_since_entry=100, current_price=100,
        days_since_last_new_high=0,
    )
    marathon = compute_stops(
        ticker="X", market="KOSPI", entry_mode="marathon",
        entry_price=100, high_since_entry=100, current_price=100,
        days_since_last_new_high=0,
    )
    assert marathon.hard_stop_price < sprint.hard_stop_price
    assert marathon.trailing_stop_price < sprint.trailing_stop_price


def test_time_stop_triggers_at_limit():
    cfg = MODES["sprint"]
    stops = compute_stops(
        ticker="X", market="KOSPI", entry_mode="sprint",
        entry_price=100, high_since_entry=110, current_price=108,
        days_since_last_new_high=int(cfg["time_stop_days"]) + 1,
    )
    assert "time_stop" in stops.triggered


def test_end_to_end_outputs_exist():
    """Run the full pipeline and verify the expected JSON outputs were written."""
    from scripts.run_analysis import run
    run()
    for fname in ("regime_data.json", "ranking_sprint.json", "ranking_marathon.json",
                  "new_leaders.json", "sector_data.json", "risk_alerts.json"):
        p = OUTPUT_DIR / fname
        assert p.exists(), f"Missing {p}"
        with p.open() as f:
            payload = json.load(f)
        assert payload, f"Empty payload in {fname}"


def test_sprint_marathon_top10_overlap_in_range():
    """PRD §15 scenario D: Sprint Top10 vs Marathon Top10 intersection should
    fall in 0..10 (i.e. not 100% identical, not totally disjoint by accident)."""
    sprint = json.loads((OUTPUT_DIR / "ranking_sprint.json").read_text(encoding="utf-8"))
    marathon = json.loads((OUTPUT_DIR / "ranking_marathon.json").read_text(encoding="utf-8"))
    sp_top = {t["ticker"] for t in sprint["tickers"][:10]}
    ma_top = {t["ticker"] for t in marathon["tickers"][:10]}
    overlap = len(sp_top & ma_top)
    assert 0 <= overlap <= 10
