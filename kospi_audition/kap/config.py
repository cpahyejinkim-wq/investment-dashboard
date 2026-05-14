"""Central configuration for KOSPI Audition Pyramid v2.1.

All magic numbers live here so behavior is reproducible and tunable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RANDOM_SEED: int = 20260514

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_RAW: Path = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED: Path = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
CHART_DATA_DIR: Path = OUTPUT_DIR / "chart_data"
DUCKDB_PATH: Path = DATA_PROCESSED / "market.duckdb"

for _p in (DATA_RAW, DATA_PROCESSED, OUTPUT_DIR, CHART_DATA_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Universe filter
# ---------------------------------------------------------------------------
UNIVERSE: dict[str, Any] = {
    "min_market_cap_kospi": 300_000_000_000,
    "min_market_cap_kosdaq": 100_000_000_000,
    "min_trade_value_20d": 3_000_000_000,
    "min_listing_days": 120,
    "min_price": 1_000,
    "exclude_keywords": ["스팩", "리츠", "우B", "우C", "우(", "우 "],
}

# ---------------------------------------------------------------------------
# Regime filter
# ---------------------------------------------------------------------------
REGIME: dict[str, Any] = {
    "breadth_strong": 0.60,
    "breadth_weak": 0.40,
    "vkospi_low": 18.0,
    "vkospi_high": 25.0,
    "risk_on_threshold": 1,
    "risk_off_threshold": -2,
    "recovery_days": 3,
    "recommended_mode_map": {
        "strong_risk_on": "sprint",
        "risk_on": "marathon",
        "neutral": "marathon",
        "risk_off": "cash",
    },
    "weight_multiplier_map": {
        "strong_risk_on": 1.0,
        "risk_on": 0.8,
        "neutral": 0.5,
        "risk_off": 0.0,
    },
    "allowed_tiers_map": {
        "strong_risk_on": ["S", "A", "B", "C"],
        "risk_on": ["S", "A", "B"],
        "neutral": ["S", "A"],
        "risk_off": [],
    },
}

# ---------------------------------------------------------------------------
# Audition Modes (v2.1 dual horizon)
# ---------------------------------------------------------------------------
MODES: dict[str, dict[str, Any]] = {
    "sprint": {
        "weights": {
            "rs_20d": 0.35,
            "rs_60d": 0.20,
            "rs_120d": 0.05,
            "acceleration": 0.20,
            "rank_velocity": 0.10,
            "volume": 0.05,
            "flow": 0.05,
        },
        "tier_thresholds": {"S": 97, "A": 92, "B": 82, "C": 65},
        "tier_max_count": {"S": 8, "A": 15, "B": 25},
        "base_weights": {"S": 0.06, "A": 0.03, "B": 0.015, "C": 0.004},
        "min_cash": 0.10,
        "hard_stop_kospi": -0.06,
        "hard_stop_kosdaq": -0.08,
        "trailing_stop": -0.10,
        "atr_multiplier": 1.5,
        "time_stop_days": 10,
        "promotion_days": 2,
        "demotion_days": 1,
        "quality_required_tiers": ["A"],
    },
    "marathon": {
        "weights": {
            "rs_20d": 0.10,
            "rs_60d": 0.20,
            "rs_120d": 0.20,
            "rs_252d": 0.15,
            "acceleration": 0.05,
            "rank_velocity": 0.05,
            "volume": 0.10,
            "flow": 0.10,
            "earnings_drift": 0.05,
        },
        "tier_thresholds": {"S": 98, "A": 93, "B": 85, "C": 70},
        "tier_max_count": {"S": 5, "A": 10, "B": 20},
        "base_weights": {"S": 0.10, "A": 0.05, "B": 0.02, "C": 0.005},
        "min_cash": 0.05,
        "hard_stop_kospi": -0.10,
        "hard_stop_kosdaq": -0.12,
        "trailing_stop": -0.18,
        "atr_multiplier": 2.5,
        "time_stop_days": 30,
        "promotion_days": 3,
        "demotion_days": 2,
        "quality_required_tiers": ["S", "A"],
    },
}

# ---------------------------------------------------------------------------
# Mode transition policy
# ---------------------------------------------------------------------------
MODE_TRANSITION: dict[str, Any] = {
    "min_hold_days": 5,
    "soft_migration": True,
    "alert_mismatch_days": 3,
}

# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------
RISK: dict[str, Any] = {
    "sector_cap_gics": 0.30,
    "sector_cap_krx": 0.25,
    "correlation_threshold": 0.80,
}

# ---------------------------------------------------------------------------
# Volatility-Adjusted Weight
# ---------------------------------------------------------------------------
VOL_ADJUSTED_WEIGHT: dict[str, Any] = {
    "enabled": False,
    "target_vol_window": 60,
}

# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
BACKTEST: dict[str, Any] = {
    "start_date": "2015-01-01",
    "walk_forward_train_months": 24,
    "walk_forward_test_months": 6,
    "walk_forward_step_months": 3,
    "oos_start_date": "2023-01-01",
    "commission_pct": 0.00015,
    "slippage_pct": 0.001,
}

# ---------------------------------------------------------------------------
# Factor configuration
# ---------------------------------------------------------------------------
RS_WINDOWS: tuple[int, ...] = (5, 20, 60, 120, 252)
RANK_VELOCITY_LOOKBACK: int = 5
RANK_VELOCITY_RANK_CUTOFF: int = 200
ACCELERATION_VOLUME_WINDOWS: tuple[int, int] = (5, 20)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FORMAT: str = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)
