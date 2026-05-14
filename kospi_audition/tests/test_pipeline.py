"""Smoke + correctness tests for Stage 1 MVP."""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from kap import config
from kap.data import collector, universe
from kap.factors import acceleration, rank_velocity, rs
from kap.modes import sprint
from kap.ranking import tier
from kap.regime import compute_regime
from kap.risk import stops


@pytest.fixture(scope="module")
def synthetic_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    end = _dt.date(2026, 5, 14)
    start = end - _dt.timedelta(days=400)
    win = collector.CollectionWindow(start=start, end=end)
    ohlcv = collector._synthetic_ohlcv(win)
    index_df = collector._synthetic_index(win)
    return ohlcv, index_df


def test_synthetic_universe_nonempty(synthetic_data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, _ = synthetic_data
    snap = universe.build_universe(ohlcv)
    assert not snap.empty
    # At least some tickers should pass the filter on synthetic data.
    assert snap["included"].sum() > 0


def test_regime_recommends_known_state(synthetic_data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, idx = synthetic_data
    result = compute_regime(idx, ohlcv)
    assert result.state in {"strong_risk_on", "risk_on", "neutral", "risk_off"}
    assert result.recommended_mode in {"sprint", "marathon", "cash"}
    assert -4 <= result.score <= 4
    # Subscores must be in {-1, 0, 1}
    for v in result.subscores.values():
        assert v in {-1, 0, 1}


def test_rs_factor_columns(synthetic_data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, idx = synthetic_data
    kospi = idx[idx["index_name"] == "KOSPI"].set_index(
        pd.to_datetime(idx[idx["index_name"] == "KOSPI"]["date"])
    )["close"]
    df = rs.compute_rs(ohlcv, kospi)
    for n in config.RS_WINDOWS:
        assert f"rs_{n}d" in df.columns
        assert f"rs_{n}d_pct" in df.columns


def test_acceleration_returns_percentiles(synthetic_data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, idx = synthetic_data
    kospi = idx[idx["index_name"] == "KOSPI"].set_index(
        pd.to_datetime(idx[idx["index_name"] == "KOSPI"]["date"])
    )["close"]
    df = acceleration.compute_acceleration(ohlcv, kospi)
    assert "acceleration_pct" in df.columns
    # percentile should fall in [0, 100] (ignoring NaN)
    series = df["acceleration_pct"].dropna()
    assert series.between(0, 100).all()


def test_rank_velocity_basic() -> None:
    # 4 tickers across 10 days with known monotonic rank reshuffle.
    rng = np.random.default_rng(0)
    dates = pd.date_range("2026-05-01", periods=10)
    scores = pd.DataFrame(
        rng.normal(size=(10, 4)),
        index=dates,
        columns=["A", "B", "C", "D"],
    )
    out = rank_velocity.compute_rank_velocity(scores)
    assert {"ticker", "rank_velocity_5d", "rank_velocity_pct"}.issubset(out.columns)
    assert len(out) == 4


def test_sprint_score_weights_sum_to_one() -> None:
    s = sum(config.MODES["sprint"]["weights"].values())
    assert abs(s - 1.0) < 1e-9


def test_marathon_score_weights_sum_to_one() -> None:
    s = sum(config.MODES["marathon"]["weights"].values())
    assert abs(s - 1.0) < 1e-9


def test_tier_assignment_respects_caps() -> None:
    df = pd.DataFrame(
        {
            "ticker": [f"T{i:03d}" for i in range(50)],
            "sprint_score_pct": np.linspace(0, 100, 50),
        }
    )
    tiered = tier.assign_tiers(df, mode="sprint", score_pct_col="sprint_score_pct")
    counts = tiered["tier"].value_counts().to_dict()
    caps = config.MODES["sprint"]["tier_max_count"]
    assert counts.get("S", 0) <= caps["S"]
    assert counts.get("A", 0) <= caps["A"]
    assert counts.get("B", 0) <= caps["B"]


def test_tier_weight_respects_min_cash() -> None:
    df = pd.DataFrame(
        {
            "ticker": [f"T{i:03d}" for i in range(20)],
            "sprint_score_pct": np.linspace(50, 100, 20),
        }
    )
    tiered = tier.assign_tiers(df, mode="sprint", score_pct_col="sprint_score_pct")
    weighted = tier.assign_weights(
        tiered,
        mode="sprint",
        regime_multiplier=1.0,
        allowed_tiers=["S", "A", "B", "C"],
    )
    invested = float(weighted["weight"].sum())
    assert invested <= 1.0 - config.MODES["sprint"]["min_cash"] + 1e-9


def test_regime_blocks_entry_when_risk_off() -> None:
    # When state is risk_off, allowed_tiers should be empty and multiplier 0.
    state = "risk_off"
    assert config.REGIME["weight_multiplier_map"][state] == 0.0
    assert config.REGIME["allowed_tiers_map"][state] == []


def test_universe_filter_passes_when_market_cap_is_nan() -> None:
    """FDR per-ticker history doesn't include market cap. The universe filter
    must treat NaN as 'unknown' rather than 'too small' so FDR-only runs work.
    """
    rows: list[dict[str, object]] = []
    for d in pd.date_range("2025-01-01", periods=130):
        rows.append({
            "ticker": "T1", "date": d.date(), "market": "KOSPI",
            "open": 50_000.0, "high": 51_000.0, "low": 49_000.0, "close": 50_500.0,
            "volume": 1_000_000, "trade_value": 50_500_000_000.0,
            "market_cap": float("nan"), "shares": float("nan"),
        })
    snap = universe.build_universe(pd.DataFrame(rows))
    assert int(snap["included"].sum()) == 1


def test_stops_are_mode_aware() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["X1", "X2"],
            "market": ["KOSPI", "KOSDAQ"],
            "current_price": [10_000.0, 20_000.0],
        }
    )
    sprint_stops = stops.attach_stops(df, mode="sprint")
    marathon_stops = stops.attach_stops(df, mode="marathon")
    # Sprint stop must be tighter (i.e. closer to price) than Marathon stop.
    assert sprint_stops.loc[0, "stop_loss"] > marathon_stops.loc[0, "stop_loss"]
    assert sprint_stops.loc[1, "stop_loss"] > marathon_stops.loc[1, "stop_loss"]
    # And differ between KOSPI vs KOSDAQ in Sprint mode (-6% vs -8%).
    assert sprint_stops.loc[0, "stop_loss"] / 10_000.0 == pytest.approx(0.94, rel=1e-3)
    assert sprint_stops.loc[1, "stop_loss"] / 20_000.0 == pytest.approx(0.92, rel=1e-3)
