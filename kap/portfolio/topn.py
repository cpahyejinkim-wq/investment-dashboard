"""Top-N momentum portfolio construction.

Alternative to PRD's tiered pyramiding. Picks the top N tickers by mode score,
allocates 100% across them (score-/tier-/equal-weighted), and on each rebalance
identifies new vs surviving vs dropped names.

State is persisted to `output/portfolio_state.json` so the next cycle can
diff against the prior holdings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

import pandas as pd
from loguru import logger

from kap.config import OUTPUT_DIR, PORTFOLIO, REGIME

Weighting = Literal["score", "tier", "equal"]


@dataclass(frozen=True)
class Holding:
    ticker: str
    name: str
    market: str
    sector: str
    tier: str
    mode_score_pct: float
    weight: float
    entry_mode: str
    status: str  # "new" | "kept" | "dropped"


@dataclass
class TopNResult:
    mode: str
    as_of: str
    n_target: int
    n_actual: int
    regime_state: str
    regime_multiplier: float
    invested_pct: float
    holdings: list[Holding] = field(default_factory=list)
    dropped: list[Holding] = field(default_factory=list)


def _load_prior_state(mode: str) -> set[str]:
    """Tickers held in the previous run (for diff display)."""
    p = OUTPUT_DIR / "portfolio_state.json"
    if not p.exists():
        return set()
    try:
        prev = json.loads(p.read_text())
        if prev.get("mode") != mode:
            return set()
        return {h["ticker"] for h in prev.get("holdings", [])}
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to load prior state: {}", e)
        return set()


def _save_state(result: TopNResult) -> None:
    p = OUTPUT_DIR / "portfolio_state.json"
    payload = {
        "mode": result.mode,
        "as_of": result.as_of,
        "n_target": result.n_target,
        "regime_state": result.regime_state,
        "holdings": [asdict(h) for h in result.holdings],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info("Saved portfolio state to {}", p)


def _score_weights(scores: pd.Series) -> pd.Series:
    s = scores.clip(lower=0.0)
    total = s.sum()
    if total <= 0:
        return pd.Series(1.0 / len(s), index=s.index)
    return s / total


def _tier_weights(tiers: pd.Series) -> pd.Series:
    mult_map = {"S": 2.0, "A": 1.5, "B": 1.0, "C": 0.7, "D": 0.5}
    raw = tiers.map(mult_map).fillna(0.5)
    return raw / raw.sum()


def _equal_weights(n: int, index: pd.Index) -> pd.Series:
    return pd.Series(1.0 / n, index=index)


def build_topn_portfolio(
    scored: pd.DataFrame,
    mode: str,
    regime_state: str,
    score_col: str | None = None,
) -> TopNResult:
    """`scored` must contain ticker/name/market/sector/tier/<score>_pct columns,
    sorted by score descending."""
    cfg = cast(dict, PORTFOLIO["topn"])
    n_target = int(cfg["n"])
    weighting: Weighting = cast(Weighting, cfg["weighting"])
    force_full = bool(cfg["force_full_deployment"])
    min_regime_mult = float(cfg["min_regime_multiplier"])

    score_col = score_col or f"{mode}_score_pct"
    mult_map = cast(dict[str, float], REGIME["weight_multiplier"])
    regime_mult = float(mult_map.get(regime_state, 0.0))

    # Risk-Off → no entry at all (PRD §5)
    if regime_state == "risk_off":
        logger.info("Risk-Off: Top-N portfolio empty (allow_new_entry=False)")
        result = TopNResult(
            mode=mode, as_of=datetime.now().isoformat(timespec="seconds"),
            n_target=n_target, n_actual=0, regime_state=regime_state,
            regime_multiplier=0.0, invested_pct=0.0,
        )
        # Mark prior holdings as "dropped" so user sees the liquidation
        prior = _load_prior_state(mode)
        # We don't have their metadata anymore — just record tickers
        for tk in prior:
            result.dropped.append(Holding(
                ticker=tk, name="", market="", sector="", tier="-",
                mode_score_pct=0.0, weight=0.0, entry_mode=mode, status="dropped",
            ))
        _save_state(result)
        return result

    # Effective deployment level
    if force_full:
        deployment = 1.0
    else:
        deployment = max(min_regime_mult, regime_mult)

    # Pick Top N from the ranked list — restrict to allowed tiers per Regime
    allowed_tiers_map = cast(dict[str, list[str]], REGIME["allowed_tiers"])
    allowed = set(allowed_tiers_map.get(regime_state, []))
    candidates = scored[scored["tier"].isin(allowed)].sort_values(score_col, ascending=False)
    top = candidates.head(n_target).copy()
    n_actual = len(top)

    if n_actual == 0:
        logger.warning("Top-N: no eligible candidates under regime={}", regime_state)
        result = TopNResult(
            mode=mode, as_of=datetime.now().isoformat(timespec="seconds"),
            n_target=n_target, n_actual=0, regime_state=regime_state,
            regime_multiplier=regime_mult, invested_pct=0.0,
        )
        _save_state(result)
        return result

    # Weight computation
    if weighting == "score":
        w = _score_weights(top[score_col])
    elif weighting == "tier":
        w = _tier_weights(top["tier"])
    else:
        w = _equal_weights(n_actual, top.index)
    top["weight"] = (w * deployment).values

    # Diff against prior holdings
    prior = _load_prior_state(mode)
    current_set = set(top["ticker"])
    dropped_tickers = prior - current_set

    holdings: list[Holding] = []
    for _, r in top.iterrows():
        status = "kept" if r["ticker"] in prior else "new"
        holdings.append(Holding(
            ticker=r["ticker"],
            name=str(r.get("name", "")),
            market=str(r.get("market", "")),
            sector=str(r.get("sector", "")),
            tier=str(r["tier"]),
            mode_score_pct=float(r[score_col]),
            weight=float(r["weight"]),
            entry_mode=mode,
            status=status,
        ))
    dropped_list: list[Holding] = [
        Holding(ticker=tk, name="", market="", sector="", tier="-",
                mode_score_pct=0.0, weight=0.0, entry_mode=mode, status="dropped")
        for tk in dropped_tickers
    ]

    invested = float(top["weight"].sum())
    logger.info(
        "Top-N portfolio: mode={} n={}/{} weighting={} invested={:.1%} "
        "(new={}, kept={}, dropped={})",
        mode, n_actual, n_target, weighting, invested,
        sum(1 for h in holdings if h.status == "new"),
        sum(1 for h in holdings if h.status == "kept"),
        len(dropped_list),
    )

    result = TopNResult(
        mode=mode,
        as_of=datetime.now().isoformat(timespec="seconds"),
        n_target=n_target,
        n_actual=n_actual,
        regime_state=regime_state,
        regime_multiplier=regime_mult,
        invested_pct=invested,
        holdings=holdings,
        dropped=dropped_list,
    )
    _save_state(result)
    return result


def export_portfolio_json(result: TopNResult, mode: str) -> Path:
    """Write `output/portfolio_<mode>.json` for the dashboard."""
    payload = {
        "mode": result.mode,
        "as_of": result.as_of,
        "strategy": "topn",
        "n_target": result.n_target,
        "n_actual": result.n_actual,
        "regime_state": result.regime_state,
        "regime_multiplier": result.regime_multiplier,
        "invested_pct": result.invested_pct,
        "cash_pct": max(0.0, 1.0 - result.invested_pct),
        "holdings": [asdict(h) for h in result.holdings],
        "dropped": [asdict(h) for h in result.dropped],
    }
    p = OUTPUT_DIR / f"portfolio_{mode}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info("Wrote {}", p)
    return p
