"""Mode-aware stop-loss rules per PRD section 8.2."""

from __future__ import annotations

import pandas as pd

from kap import config


def attach_stops(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Append stop_loss / trailing_stop / time_stop_days columns.

    Stops are computed relative to the current close (the PRD distinguishes
    between entry price vs current price; without entry-price history in
    Stage 1, we treat ``current_price`` as the reference).
    """
    cfg = config.MODES[mode]
    out = df.copy()

    def _hard(row: pd.Series) -> float:
        pct = (
            cfg["hard_stop_kospi"]
            if row.get("market") == "KOSPI"
            else cfg["hard_stop_kosdaq"]
        )
        price = float(row.get("current_price") or row.get("last_close") or 0.0)
        return round(price * (1.0 + pct), 2)

    out["stop_loss"] = out.apply(_hard, axis=1)
    out["trailing_stop"] = out.apply(
        lambda r: round(
            float(r.get("current_price") or r.get("last_close") or 0.0) * (1.0 + cfg["trailing_stop"]),
            2,
        ),
        axis=1,
    )
    out["time_stop_days"] = int(cfg["time_stop_days"])
    return out


def build_risk_alerts(positions: pd.DataFrame, mode: str) -> list[dict[str, object]]:
    """Generate simple stop-breach alerts on the latest snapshot."""
    cfg = config.MODES[mode]
    alerts: list[dict[str, object]] = []
    if positions.empty:
        return alerts
    for _, row in positions.iterrows():
        price = float(row.get("current_price") or row.get("last_close") or 0.0)
        stop = float(row.get("stop_loss", 0.0))
        if price > 0 and stop > 0 and price <= stop:
            alerts.append(
                {
                    "ticker": str(row["ticker"]),
                    "type": "hard_stop_breach",
                    "mode": mode,
                    "price": price,
                    "stop_loss": stop,
                    "hard_stop_pct": float(
                        cfg["hard_stop_kospi"]
                        if row.get("market") == "KOSPI"
                        else cfg["hard_stop_kosdaq"]
                    ),
                }
            )
    return alerts
