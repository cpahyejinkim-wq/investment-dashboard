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


def write_mode_compare(payload: dict[str, Any], as_of: str) -> Path:
    return write_json({**payload, "as_of": as_of}, "mode_compare.json")


def write_positions(book: dict[str, dict[str, Any]], events: list[dict[str, Any]], as_of: str) -> Path:
    return write_json(
        {
            "as_of": as_of,
            "positions": list(book.values()),
            "events": events,
        },
        "positions.json",
    )


def write_sector_power(
    sector_power: pd.DataFrame,
    top_tickers: dict[str, list[str]],
    as_of: str,
) -> Path:
    if sector_power.empty:
        rows: list[dict[str, Any]] = []
    else:
        rows = []
        for _, r in sector_power.iterrows():
            sector = str(r.get("sector"))
            rows.append(
                {
                    "sector": sector,
                    "sector_power": _safe(r.get("sector_power")),
                    "sector_rs_pct": _safe(r.get("sector_rs_pct")),
                    "new_leader_count": _safe(r.get("new_leader_count", 0)),
                    "new_leader_ratio": _safe(r.get("new_leader_ratio")),
                    "trading_amount_growth": _safe(r.get("trading_amount_growth")),
                    "top_tickers": top_tickers.get(sector, []),
                }
            )
    return write_json({"as_of": as_of, "sectors": rows}, "sector_power.json")


def write_backtest(results: dict[str, dict[str, Any]], as_of: str) -> Path:
    payload = {
        "as_of": as_of,
        "strategies": {
            name: {k: _safe(v) for k, v in metrics.items()}
            for name, metrics in results.items()
        },
    }
    return write_json(payload, "backtest_results.json")
