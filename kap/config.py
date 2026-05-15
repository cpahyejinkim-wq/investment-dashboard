"""Central configuration for the KOSPI Audition Pyramid Dashboard v2.1.

All magic numbers, weights, thresholds, and policy parameters live here.
Reproducibility: change here, propagate everywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, TypedDict

# ===== Paths =====
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
RAW_DIR: Final[Path] = DATA_DIR / "raw"
PROCESSED_DIR: Final[Path] = DATA_DIR / "processed"
OUTPUT_DIR: Final[Path] = PROJECT_ROOT / "output"
DASHBOARD_DIR: Final[Path] = PROJECT_ROOT / "dashboard"
DUCKDB_PATH: Final[Path] = DATA_DIR / "market.duckdb"

for _p in (RAW_DIR, PROCESSED_DIR, OUTPUT_DIR, OUTPUT_DIR / "chart_data"):
    _p.mkdir(parents=True, exist_ok=True)

# ===== Reproducibility =====
RANDOM_SEED: Final[int] = 20260514

# ===== Universe Filter (PRD §4.1) =====
UNIVERSE: Final[dict[str, int]] = {
    "min_market_cap_kospi": 300_000_000_000,
    "min_market_cap_kosdaq": 100_000_000_000,
    "min_trade_value_20d": 3_000_000_000,
    "min_listing_days": 120,
    "min_price": 1_000,
}

# ===== Regime Filter (PRD §5) =====
REGIME: Final[dict[str, object]] = {
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
    "weight_multiplier": {
        "strong_risk_on": 1.0,
        "risk_on": 0.8,
        "neutral": 0.5,
        "risk_off": 0.0,
    },
    "allowed_tiers": {
        "strong_risk_on": ["S", "A", "B", "C"],
        "risk_on": ["S", "A", "B"],
        "neutral": ["S", "A"],
        "risk_off": [],
    },
}


class ModeConfig(TypedDict):
    weights: dict[str, float]
    tier_thresholds: dict[str, float]
    tier_max_count: dict[str, int]
    base_weights: dict[str, float]
    min_cash: float
    hard_stop_kospi: float
    hard_stop_kosdaq: float
    trailing_stop: float
    atr_multiplier: float
    time_stop_days: int
    promotion_days: int
    demotion_days: int
    quality_required_tiers: list[str]


# ===== Audition Modes (PRD §2, §7, §14) =====
MODES: Final[dict[str, ModeConfig]] = {
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
        "tier_thresholds": {"S": 97.0, "A": 92.0, "B": 82.0, "C": 65.0},
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
        "tier_thresholds": {"S": 98.0, "A": 93.0, "B": 85.0, "C": 70.0},
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

# ===== Mode Transition (PRD §2.3) =====
MODE_TRANSITION: Final[dict[str, object]] = {
    "min_hold_days": 5,
    "soft_migration": True,
    "alert_mismatch_days": 3,
}

# ===== Risk (PRD §7.4) =====
RISK: Final[dict[str, float]] = {
    "sector_cap_gics": 0.30,
    "sector_cap_krx": 0.25,
    "correlation_threshold": 0.80,
}

# ===== Volatility-Adjusted Weight (PRD §7.3) =====
VOL_ADJUSTED_WEIGHT: Final[dict[str, object]] = {
    "enabled": False,
    "target_vol_window": 60,
}

# ===== Portfolio Construction Strategy =====
# "pyramid" — PRD default: tiered base weights × pyramid_first × regime multiplier,
#             min_cash 유보. 검증 후 추가매수로 weight_target까지 도달.
# "topn"    — Top-N momentum: 매 사이클 mode_score 상위 N개를 골라 100% 배분.
#             탈락 종목은 매도, 신규 편입 종목은 매수. 현금 보유 없음.
PORTFOLIO: Final[dict[str, object]] = {
    "strategy": "topn",          # "pyramid" or "topn"
    "topn": {
        "n": 10,                  # 보유 종목 수 (고정)
        "weighting": "score",     # "score" | "tier" | "equal"
        "force_full_deployment": True,  # 현금 0%, 합계 100%
        "min_regime_multiplier": 0.3,   # Risk-Off가 아니면 최소 30%는 투자
    },
}

# ===== Backtest (PRD §10) =====
BACKTEST: Final[dict[str, object]] = {
    "start_date": "2015-01-01",
    "walk_forward_train_months": 24,
    "walk_forward_test_months": 6,
    "walk_forward_step_months": 3,
    "oos_start_date": "2023-01-01",
    "commission_pct": 0.00015,
    "slippage_pct": 0.001,
}

# ===== Data fetch =====
DATA_FETCH: Final[dict[str, object]] = {
    "use_synthetic_fallback": True,
    "synthetic_n_kospi": 120,
    "synthetic_n_kosdaq": 80,
    "synthetic_history_days": 400,
}
