"""Regime Filter (PRD §5).

Computes Trend / Breadth / Volatility sub-scores → composite regime score
→ regime state → recommended Audition Mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
from loguru import logger

from kap.config import REGIME


@dataclass(frozen=True)
class RegimeResult:
    as_of: pd.Timestamp
    score: int
    state: str
    recommended_mode: str
    subscores: dict[str, int]
    indicators: dict[str, float]
    weight_multiplier: float
    allow_new_entry: bool
    allowed_tiers: list[str]
    history_30d: list[dict[str, object]]
    mode_unchanged_days: int


def _trend_subscore(kospi_close: pd.Series) -> tuple[int, dict[str, float]]:
    ma50 = kospi_close.rolling(50).mean()
    ma200 = kospi_close.rolling(200).mean()
    last_close = float(kospi_close.iloc[-1])
    last_ma200 = float(ma200.iloc[-1])
    last_ma50 = float(ma50.iloc[-1])

    score = 0
    if last_close > last_ma200:
        score += 1
    elif last_close < last_ma200:
        score -= 1

    # Golden / Death cross detection (recent crossover within 60 days)
    cross_window = 60
    diff = (ma50 - ma200).tail(cross_window)
    sign_change = np.sign(diff).diff().dropna()
    if (sign_change > 0).any():
        score += 1
    elif (sign_change < 0).any():
        score -= 1

    return score, {"kospi_close": last_close, "kospi_ma200": last_ma200, "kospi_ma50": last_ma50}


def _breadth_subscore(ohlcv: pd.DataFrame, as_of: pd.Timestamp) -> tuple[int, float]:
    """Share of universe trading above its 20-day MA."""
    recent = ohlcv[ohlcv["date"] <= as_of].copy()
    last20 = recent.sort_values("date").groupby("ticker").tail(20)
    ma20 = last20.groupby("ticker")["close"].mean()
    last_close = recent.sort_values("date").groupby("ticker").tail(1).set_index("ticker")["close"]
    aligned = last_close.reindex(ma20.index)
    above = (aligned > ma20).mean()
    breadth = float(above)

    strong = float(REGIME["breadth_strong"])  # type: ignore[arg-type]
    weak = float(REGIME["breadth_weak"])  # type: ignore[arg-type]
    if breadth >= strong:
        return 1, breadth
    if breadth < weak:
        return -1, breadth
    return 0, breadth


def _volatility_subscore(vkospi: pd.Series) -> tuple[int, float]:
    last = float(vkospi.iloc[-1])
    low = float(REGIME["vkospi_low"])  # type: ignore[arg-type]
    high = float(REGIME["vkospi_high"])  # type: ignore[arg-type]
    if last <= low:
        return 1, last
    if last >= high:
        return -1, last
    return 0, last


def _classify_state(score: int) -> str:
    if score >= 3:
        return "strong_risk_on"
    if score >= 1:
        return "risk_on"
    if score <= -2:
        return "risk_off"
    return "neutral"


def compute_regime(
    ohlcv: pd.DataFrame, index_df: pd.DataFrame, as_of: pd.Timestamp | None = None
) -> RegimeResult:
    as_of = as_of or pd.Timestamp(ohlcv["date"].max())
    idx = index_df[index_df["date"] <= as_of].sort_values("date").reset_index(drop=True)
    kospi_close = idx["kospi_close"]
    vkospi = idx["vkospi"]

    trend, trend_ind = _trend_subscore(kospi_close)
    breadth, breadth_val = _breadth_subscore(ohlcv, as_of)
    vol, vkospi_val = _volatility_subscore(vkospi)
    score = trend + breadth + vol
    state = _classify_state(score)

    mode_map = cast(dict[str, str], REGIME["recommended_mode_map"])
    recommended_mode = mode_map[state]
    mult_map = cast(dict[str, float], REGIME["weight_multiplier"])
    tiers_map = cast(dict[str, list[str]], REGIME["allowed_tiers"])

    # 30-day history of regime score
    history: list[dict[str, object]] = []
    for i in range(max(0, len(idx) - 30), len(idx)):
        d = idx["date"].iloc[i]
        h_kospi = idx["kospi_close"].iloc[: i + 1]
        h_vk = idx["vkospi"].iloc[: i + 1]
        if len(h_kospi) < 200:
            continue
        t_score, _ = _trend_subscore(h_kospi)
        b_score, _ = _breadth_subscore(ohlcv, pd.Timestamp(d))
        v_score, _ = _volatility_subscore(h_vk)
        hist_score = t_score + b_score + v_score
        history.append({
            "date": pd.Timestamp(d).strftime("%Y-%m-%d"),
            "score": int(hist_score),
            "state": _classify_state(hist_score),
        })

    # Mode unchanged days (from history)
    mode_unchanged = 1
    for h in reversed(history[:-1]):
        prev_state = h["state"]
        prev_mode = mode_map.get(str(prev_state), "cash")
        if prev_mode == recommended_mode:
            mode_unchanged += 1
        else:
            break

    result = RegimeResult(
        as_of=as_of,
        score=int(score),
        state=state,
        recommended_mode=recommended_mode,
        subscores={"trend": int(trend), "breadth": int(breadth), "volatility": int(vol)},
        indicators={
            **trend_ind,
            "breadth_above_ma20": round(breadth_val, 4),
            "vkospi": round(vkospi_val, 2),
        },
        weight_multiplier=float(mult_map[state]),
        allow_new_entry=state != "risk_off",
        allowed_tiers=list(tiers_map[state]),
        history_30d=history,
        mode_unchanged_days=mode_unchanged,
    )
    logger.info(
        "Regime: score={} state={} recommended={} (trend={}, breadth={}, vol={})",
        score, state, recommended_mode, trend, breadth, vol,
    )
    return result
