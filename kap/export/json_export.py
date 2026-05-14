"""JSON Exporter (PRD §12).

Writes regime_data.json, ranking_sprint.json, ranking_marathon.json,
new_leaders.json, sector_data.json, sector_power.json (stub for Stage 1).
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from kap.config import OUTPUT_DIR
from kap.regime.filter import RegimeResult

KST = timezone(timedelta(hours=9))


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o) if not np.isnan(o) else None
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if is_dataclass(o):
        return asdict(o)
    raise TypeError(f"Not serializable: {type(o)}")


def _now_kst_iso() -> str:
    return datetime.now(tz=KST).isoformat(timespec="seconds")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)
    logger.info("Wrote {}", path)


def export_regime(result: RegimeResult, current_mode: str | None = None) -> Path:
    d = {
        "as_of": _now_kst_iso(),
        "data_as_of": result.as_of.strftime("%Y-%m-%d"),
        "score": result.score,
        "state": result.state,
        "recommended_mode": result.recommended_mode,
        "current_mode": current_mode or result.recommended_mode,
        "mode_unchanged_days": result.mode_unchanged_days,
        "subscores": result.subscores,
        "indicators": result.indicators,
        "weight_multiplier": result.weight_multiplier,
        "allow_new_entry": result.allow_new_entry,
        "allowed_tiers": result.allowed_tiers,
        "history_30d": result.history_30d,
    }
    path = OUTPUT_DIR / "regime_data.json"
    write_json(path, d)
    return path


def export_ranking(df: pd.DataFrame, mode: str, regime_state: str, universe_size: int) -> Path:
    """Mode-specific ranking file (PRD §12.2)."""
    tickers = []
    for _, r in df.iterrows():
        rec = {
            "ticker": r["ticker"],
            "name": r.get("name", ""),
            "market": r["market"],
            "sector": r.get("sector", ""),
            "tier": r["tier"],
            "tier_prev": r.get("tier_prev", r["tier"]),
            "tier_changed": bool(r.get("tier_changed", False)),
            "mode_score": float(r[f"{mode}_score"]),
            "mode_score_pct": float(r[f"{mode}_score_pct"]),
            "rs_20d": float(r.get("rs_20d", float("nan"))),
            "rs_60d": float(r.get("rs_60d", float("nan"))),
            "rs_120d": float(r.get("rs_120d", float("nan"))),
            "rs_252d": float(r.get("rs_252d", float("nan"))) if "rs_252d" in df.columns else None,
            "acceleration": float(r.get("acceleration_pct", float("nan"))),
            "rank_velocity_5d": float(r.get("rank_velocity", 0.0)),
            "rank_velocity_pct": float(r.get("rank_velocity_pct", 50.0)),
            "volume_score": float(r.get("volume_pct", float("nan"))),
            "flow_score": float(r.get("flow_pct", float("nan"))),
            "quality_pass": bool(r.get("quality_pass", True)),
            "leader_score": float(r.get("leader_score", float("nan"))),
            "survival_days": int(r.get("survival_days", 0)),
            "weight": float(r.get("weight", 0.0)),
            "weight_target": float(r.get("weight_target", 0.0)),
            "entry_signal": r.get("entry_signal", "n/a"),
            "entry_mode": mode,
            "current_price": float(r["close"]),
            "stop_loss": float(r.get("hard_stop_price", float("nan"))),
            "trailing_stop": float(r.get("trailing_stop_price", float("nan"))),
        }
        # Drop NaN-ish None-equivalents
        rec = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in rec.items()}
        tickers.append(rec)

    payload = {
        "mode": mode,
        "as_of": _now_kst_iso(),
        "regime_state": regime_state,
        "universe_size": int(universe_size),
        "tickers": tickers,
    }
    path = OUTPUT_DIR / f"ranking_{mode}.json"
    write_json(path, payload)
    return path


def export_new_leaders(df: pd.DataFrame, mode: str) -> Path:
    """Top rank-velocity tickers (PRD §12.4)."""
    leaders = df.sort_values("rank_velocity", ascending=False).head(20)
    items = []
    for _, r in leaders.iterrows():
        items.append({
            "ticker": r["ticker"],
            "name": r.get("name", ""),
            "rank_velocity_5d": float(r.get("rank_velocity", 0.0)),
            "rank_today": float(r.get("rank_today", float("nan"))),
            "rank_5d_ago": float(r.get("rank_window_ago", float("nan"))),
            "acceleration": float(r.get("acceleration_pct", float("nan"))),
            "tier_change": f"{r.get('tier_prev','D')} → {r.get('tier','D')}",
            "sector": r.get("sector", ""),
        })
    payload = {"as_of": _now_kst_iso(), "mode": mode, "new_leaders": items}
    path = OUTPUT_DIR / "new_leaders.json"
    write_json(path, payload)
    return path


def export_sector_summary(df: pd.DataFrame, mode: str) -> Path:
    """Lightweight sector summary (Stage 1 stub; Stage 3 will add full Sector Power)."""
    if df.empty:
        write_json(OUTPUT_DIR / "sector_data.json", {"as_of": _now_kst_iso(), "sectors": []})
        return OUTPUT_DIR / "sector_data.json"

    grp = df.groupby("sector")
    rows = []
    for sector, g in grp:
        rows.append({
            "sector": sector,
            "n_tickers": int(len(g)),
            "n_top_tier": int(((g["tier"] == "S") | (g["tier"] == "A")).sum()),
            "avg_mode_score": float(g[f"{mode}_score"].mean()),
            "avg_rs_60d_pct": float(g.get("rs_60d_pct", pd.Series([float("nan")])).mean()),
            "total_weight": float(g["weight"].sum()),
        })
    rows.sort(key=lambda r: r["avg_mode_score"], reverse=True)
    payload = {"as_of": _now_kst_iso(), "mode": mode, "sectors": rows}
    path = OUTPUT_DIR / "sector_data.json"
    write_json(path, payload)
    return path


def export_risk_alerts(triggered: pd.DataFrame) -> Path:
    items: list[dict[str, Any]] = []
    if triggered is not None and not triggered.empty:
        flag_rows = triggered[triggered["triggered"].str.len() > 0]
        for _, r in flag_rows.iterrows():
            items.append({
                "ticker": r["ticker"],
                "entry_mode": r["entry_mode"],
                "entry_price": float(r["entry_price"]),
                "current_price": float(r["current_price"]),
                "triggered": list(r["triggered"]),
                "hard_stop_price": float(r["hard_stop_price"]),
                "trailing_stop_price": float(r["trailing_stop_price"]),
            })
    payload = {"as_of": _now_kst_iso(), "alerts": items}
    path = OUTPUT_DIR / "risk_alerts.json"
    write_json(path, payload)
    return path
