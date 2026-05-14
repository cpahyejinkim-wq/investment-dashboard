"""Regime filter per PRD section 5.

Inputs:
  - index OHLCV (KOSPI, KOSDAQ, VKOSPI)
  - market-wide OHLCV (for breadth calculation)

Outputs a structured dict matching ``regime_data.json`` schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from kap import config


@dataclass
class RegimeResult:
    as_of: date
    score: int
    state: str
    recommended_mode: str
    subscores: dict[str, int]
    indicators: dict[str, float]
    weight_multiplier: float
    allow_new_entry: bool
    allowed_tiers: list[str]
    history_30d: list[dict[str, object]]

    def as_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "score": self.score,
            "state": self.state,
            "recommended_mode": self.recommended_mode,
            "subscores": self.subscores,
            "indicators": self.indicators,
            "weight_multiplier": self.weight_multiplier,
            "allow_new_entry": self.allow_new_entry,
            "allowed_tiers": self.allowed_tiers,
            "history_30d": self.history_30d,
        }


def _trend_subscore(kospi: pd.Series) -> tuple[int, dict[str, float]]:
    if len(kospi) < 200:
        return 0, {"kospi_close": float(kospi.iloc[-1]), "kospi_ma200": float("nan")}
    ma200 = kospi.rolling(200).mean().iloc[-1]
    ma50 = kospi.rolling(50).mean().iloc[-1]
    last_close = float(kospi.iloc[-1])
    above_200 = 1 if last_close > ma200 else -1
    # Golden / death cross: compare current 50/200 ordering vs ~30 days prior
    prev_ma50 = kospi.rolling(50).mean().iloc[-30] if len(kospi) > 230 else ma50
    prev_ma200 = kospi.rolling(200).mean().iloc[-30] if len(kospi) > 230 else ma200
    cross = 1 if (ma50 > ma200 and prev_ma50 <= prev_ma200) else (
        -1 if (ma50 < ma200 and prev_ma50 >= prev_ma200) else 0
    )
    sub = max(-1, min(1, above_200 + cross))
    return int(sub), {"kospi_close": last_close, "kospi_ma200": float(ma200)}


def _breadth_subscore(ohlcv: pd.DataFrame) -> tuple[int, float]:
    if ohlcv.empty:
        return 0, float("nan")
    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    last_date = df["date"].max()
    recent = df[df["date"] >= last_date - pd.Timedelta(days=40)]
    ma20 = (
        recent.sort_values("date")
        .groupby("ticker")["close"]
        .apply(lambda s: s.rolling(20).mean().iloc[-1] if len(s) >= 20 else np.nan)
    )
    last_close = recent.sort_values("date").groupby("ticker")["close"].last()
    aligned = pd.concat([last_close.rename("close"), ma20.rename("ma20")], axis=1).dropna()
    if aligned.empty:
        return 0, float("nan")
    ratio = float((aligned["close"] > aligned["ma20"]).mean())
    if ratio >= config.REGIME["breadth_strong"]:
        sub = 1
    elif ratio < config.REGIME["breadth_weak"]:
        sub = -1
    else:
        sub = 0
    return sub, ratio


def _vol_subscore(vkospi: pd.Series | None) -> tuple[int, float]:
    if vkospi is None or vkospi.empty:
        return 0, float("nan")
    last = float(vkospi.iloc[-1])
    if last <= config.REGIME["vkospi_low"]:
        return 1, last
    if last >= config.REGIME["vkospi_high"]:
        return -1, last
    return 0, last


def _classify(score: int) -> str:
    if score >= 3:
        return "strong_risk_on"
    if score >= config.REGIME["risk_on_threshold"]:
        return "risk_on"
    if score <= config.REGIME["risk_off_threshold"]:
        return "risk_off"
    return "neutral"


def compute_regime(
    index_df: pd.DataFrame,
    market_ohlcv: pd.DataFrame,
) -> RegimeResult:
    if index_df.empty:
        raise ValueError("index_df is empty - cannot compute regime")
    idx = index_df.copy()
    idx["date"] = pd.to_datetime(idx["date"])
    kospi = idx[idx["index_name"] == "KOSPI"].sort_values("date").set_index("date")["close"]
    vk = (
        idx[idx["index_name"] == "VKOSPI"].sort_values("date").set_index("date")["close"]
        if "VKOSPI" in idx["index_name"].unique()
        else None
    )

    trend_sub, trend_inds = _trend_subscore(kospi)
    breadth_sub, breadth_ratio = _breadth_subscore(market_ohlcv)
    vol_sub, vkospi_val = _vol_subscore(vk)

    score = int(trend_sub + breadth_sub + vol_sub)
    state = _classify(score)
    recommended_mode = config.REGIME["recommended_mode_map"][state]
    multiplier = float(config.REGIME["weight_multiplier_map"][state])
    allowed_tiers = list(config.REGIME["allowed_tiers_map"][state])
    allow_new = state != "risk_off"

    as_of = kospi.index[-1].date()

    history = _regime_history(kospi, market_ohlcv, vk, last_n=30)

    return RegimeResult(
        as_of=as_of,
        score=score,
        state=state,
        recommended_mode=recommended_mode,
        subscores={"trend": int(trend_sub), "breadth": int(breadth_sub), "volatility": int(vol_sub)},
        indicators={
            "kospi_close": trend_inds["kospi_close"],
            "kospi_ma200": trend_inds["kospi_ma200"],
            "breadth_above_ma20": float(breadth_ratio),
            "vkospi": float(vkospi_val),
        },
        weight_multiplier=multiplier,
        allow_new_entry=allow_new,
        allowed_tiers=allowed_tiers,
        history_30d=history,
    )


def _regime_history(
    kospi: pd.Series,
    market_ohlcv: pd.DataFrame,
    vkospi: pd.Series | None,
    last_n: int,
) -> list[dict[str, object]]:
    if len(kospi) < 200:
        return []
    out: list[dict[str, object]] = []
    dates = kospi.index[-last_n:]
    for d in dates:
        sub_kospi = kospi.loc[:d]
        trend_sub, _ = _trend_subscore(sub_kospi)
        sub_market = market_ohlcv[pd.to_datetime(market_ohlcv["date"]) <= d]
        breadth_sub, _ = _breadth_subscore(sub_market)
        sub_vk = vkospi.loc[:d] if vkospi is not None else None
        vol_sub, _ = _vol_subscore(sub_vk)
        s = int(trend_sub + breadth_sub + vol_sub)
        out.append({"date": d.date().isoformat(), "score": s, "state": _classify(s)})
    return out
