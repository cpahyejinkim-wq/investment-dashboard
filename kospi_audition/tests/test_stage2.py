"""Stage 2 tests: volume/flow/marathon/entry-signal/sector-cap/soft-migration."""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import pytest

from kap import config
from kap.data import collector
from kap.factors import acceleration, flow, rank_velocity, rs, volume
from kap.modes import marathon, sprint
from kap.portfolio import positions
from kap.ranking import mode_compare, tier
from kap.risk import entry_signal, sector_cap, stops


@pytest.fixture(scope="module")
def synth() -> tuple[pd.DataFrame, pd.DataFrame]:
    end = _dt.date(2026, 5, 14)
    start = end - _dt.timedelta(days=400)
    win = collector.CollectionWindow(start=start, end=end)
    return collector._synthetic_ohlcv(win), collector._synthetic_index(win)


def test_volume_score(synth: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, _ = synth
    out = volume.compute_volume_score(ohlcv)
    assert {"ticker", "volume_score", "volume_pct"}.issubset(out.columns)
    assert out["volume_pct"].between(0, 100).all()


def test_flow_score_uses_synthetic_data(synth: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, _ = synth
    raw = flow.synthetic_flow(ohlcv)
    out = flow.compute_flow_score(raw)
    assert "flow_score" in out.columns
    assert "flow_pct" in out.columns
    assert {"foreign_streak_5d", "inst_streak_5d"}.issubset(out.columns)


def test_marathon_score_pipeline(synth: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, idx = synth
    kospi = idx[idx["index_name"] == "KOSPI"].set_index(
        pd.to_datetime(idx[idx["index_name"] == "KOSPI"]["date"])
    )["close"]
    rs_df = rs.compute_rs(ohlcv, kospi)
    accel = acceleration.compute_acceleration(ohlcv, kospi)
    # simple 1-day score history is enough for rank_velocity to return rows
    score_hist = pd.DataFrame(np.random.default_rng(0).normal(size=(10, len(rs_df))),
                              index=pd.date_range("2026-05-01", periods=10),
                              columns=rs_df["ticker"].values)
    rv = rank_velocity.compute_rank_velocity(score_hist)
    vol = volume.compute_volume_score(ohlcv)
    fl = flow.compute_flow_score(flow.synthetic_flow(ohlcv))

    sprint_scored = sprint.compute_sprint_score(rs_df, accel, rv, volume=vol, flow=fl)
    marathon_scored = marathon.compute_marathon_score(rs_df, accel, rv, volume=vol, flow=fl)
    assert "sprint_score" in sprint_scored.columns
    assert "marathon_score" in marathon_scored.columns
    # Top-10 lists should diverge (different weighting profile).
    sprint_top = set(sprint_scored.nlargest(10, "sprint_score_pct")["ticker"])
    marathon_top = set(marathon_scored.nlargest(10, "marathon_score_pct")["ticker"])
    assert sprint_top != marathon_top


def test_entry_signal_returns_known_types(synth: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    ohlcv, _ = synth
    out = entry_signal.compute_entry_signals(ohlcv)
    if not out.empty:
        assert set(out["entry_signal"].unique()).issubset({"breakout", "vcp", "pullback"})


def test_sector_cap_downscales_overweight_group() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["A1", "A2", "A3", "B1"],
            "sector": ["A", "A", "A", "B"],
            "weight": [0.20, 0.20, 0.20, 0.05],
        }
    )
    capped = sector_cap.enforce_sector_cap(df, cap=0.25)
    total_a = float(capped.loc[capped["sector"] == "A", "weight"].sum())
    assert total_a == pytest.approx(0.25, rel=1e-6)
    assert float(capped.loc[capped["sector"] == "B", "weight"].iloc[0]) == pytest.approx(0.05)


def test_correlation_cluster_groups_perfect_correlation() -> None:
    # Construct 3 tickers where A and B have identical returns and C is random.
    dates = pd.date_range("2026-01-01", periods=80, freq="B")
    rng = np.random.default_rng(0)
    base = np.cumprod(1 + rng.normal(0.001, 0.01, size=80)) * 1000
    other = np.cumprod(1 + rng.normal(0.001, 0.01, size=80)) * 1000
    rows = []
    for date, p in zip(dates, base, strict=True):
        rows.append({"ticker": "A", "date": date, "close": p, "trade_value": 1.0, "volume": 1.0, "high": p, "low": p, "open": p})
        rows.append({"ticker": "B", "date": date, "close": p, "trade_value": 1.0, "volume": 1.0, "high": p, "low": p, "open": p})
    for date, p in zip(dates, other, strict=True):
        rows.append({"ticker": "C", "date": date, "close": p, "trade_value": 1.0, "volume": 1.0, "high": p, "low": p, "open": p})
    ohlcv = pd.DataFrame(rows)
    clusters = sector_cap.correlation_clusters(ohlcv, ["A", "B", "C"], threshold=0.8)
    assert clusters["A"] == clusters["B"]
    assert clusters["C"] != clusters["A"]


def test_mode_compare_health_bands() -> None:
    sprint_df = pd.DataFrame({"ticker": [f"S{i}" for i in range(10)]})
    marathon_df = pd.DataFrame({"ticker": [f"M{i}" for i in range(10)]})
    out = mode_compare.compare_modes(sprint_df, marathon_df, top_n=10)
    assert out["overlap_ratio"] == 0.0
    assert out["health"] == "diverged"


def test_soft_migration_keeps_entry_mode() -> None:
    # Existing book has a Sprint position; toggle to Marathon should not rewrite it.
    book = {
        "012450": {
            "ticker": "012450",
            "entry_mode": "sprint",
            "entry_tier": "S",
            "entry_date": "2026-05-01",
            "entry_price": 100000.0,
            "stop_loss": 94000.0,
            "trailing_stop": 90000.0,
            "time_stop_days": 10,
            "tier_today": "S",
            "current_price": 105000.0,
        }
    }
    new_ranking = pd.DataFrame(
        [
            {
                "ticker": "012450",
                "tier": "A",
                "market": "KOSPI",
                "current_price": 110000.0,
                "stop_loss": 99000.0,   # Marathon-style stop -10%
                "trailing_stop": 90200.0,
                "time_stop_days": 30,
            }
        ]
    )
    updated, _events = positions.reconcile(
        book,
        new_ranking,
        active_mode="marathon",
        regime_state="risk_on",
        today=_dt.date(2026, 5, 14),
        allowed_tiers=["S", "A", "B"],
    )
    pos = updated["012450"]
    # Entry mode + stops must be preserved (Soft Migration).
    assert pos["entry_mode"] == "sprint"
    assert pos["stop_loss"] == 94000.0
    assert pos["time_stop_days"] == 10
    # Tier is refreshed today.
    assert pos["tier_today"] == "A"


def test_soft_migration_blocks_new_entries_in_risk_off() -> None:
    ranking = pd.DataFrame(
        [
            {
                "ticker": "000001",
                "tier": "S",
                "market": "KOSPI",
                "current_price": 50000.0,
                "stop_loss": 47000.0,
            }
        ]
    )
    updated, _ = positions.reconcile(
        {},
        ranking,
        active_mode="sprint",
        regime_state="risk_off",
        today=_dt.date(2026, 5, 14),
        allowed_tiers=[],
    )
    assert updated == {}


def test_marathon_stops_loosen_versus_sprint() -> None:
    df = pd.DataFrame(
        {"ticker": ["X", "Y"], "market": ["KOSPI", "KOSDAQ"], "current_price": [10_000.0, 5_000.0]}
    )
    s = stops.attach_stops(df, mode="sprint")
    m = stops.attach_stops(df, mode="marathon")
    # Marathon time stop is longer.
    assert int(m["time_stop_days"].iloc[0]) == config.MODES["marathon"]["time_stop_days"]
    assert int(s["time_stop_days"].iloc[0]) == config.MODES["sprint"]["time_stop_days"]
    # Marathon hard-stop floor is lower (more room).
    assert m["stop_loss"].iloc[0] < s["stop_loss"].iloc[0]
