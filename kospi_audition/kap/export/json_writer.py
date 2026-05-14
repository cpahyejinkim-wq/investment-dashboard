"""JSON exporters matching the v2.1 schema in PRD section 12."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from kap import config


def _safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return value
    return value


def _row_to_dict(row: pd.Series) -> dict[str, Any]:
    return {k: _safe(v) for k, v in row.to_dict().items()}


def write_json(payload: dict[str, Any], filename: str) -> Path:
    path = config.OUTPUT_DIR / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_safe))
    return path


def write_ranking(
    ranked: pd.DataFrame, mode: str, as_of: str, universe_size: int
) -> Path:
    tickers: list[dict[str, Any]] = []
    for _, row in ranked.iterrows():
        tickers.append(_row_to_dict(row))
    payload = {
        "mode": mode,
        "as_of": as_of,
        "universe_size": universe_size,
        "tickers": tickers,
    }
    return write_json(payload, f"ranking_{mode}.json")


def write_regime(regime: dict[str, Any]) -> Path:
    return write_json(regime, "regime_data.json")


def write_risk_alerts(alerts: list[dict[str, Any]], as_of: str) -> Path:
    return write_json({"as_of": as_of, "alerts": alerts}, "risk_alerts.json")


def write_new_leaders(leaders: pd.DataFrame, as_of: str) -> Path:
    rows = [_row_to_dict(r) for _, r in leaders.iterrows()] if not leaders.empty else []
    return write_json({"as_of": as_of, "new_leaders": rows}, "new_leaders.json")
