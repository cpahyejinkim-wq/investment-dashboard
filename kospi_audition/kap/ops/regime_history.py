"""Track regime state + active mode across runs.

State persisted at ``output/run_history.json``:
  - last regime state + mode_unchanged_days
  - active mode mismatch streak (for alerting at >= alert_mismatch_days)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from kap import config

HIST_PATH: Path = config.OUTPUT_DIR / "run_history.json"


def load() -> dict[str, Any]:
    if HIST_PATH.exists():
        return json.loads(HIST_PATH.read_text())
    return {
        "previous_regime_state": None,
        "mode_mismatch_streak": 0,
        "last_active_mode": None,
        "last_recommended_mode": None,
        "last_run_date": None,
    }


def save(state: dict[str, Any]) -> Path:
    HIST_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return HIST_PATH


def update(
    state: dict[str, Any],
    today: date,
    current_regime_state: str,
    active_mode: str,
    recommended_mode: str,
) -> tuple[dict[str, Any], str | None, int]:
    """Return ``(new_state, previous_regime_state, mismatch_streak)``."""
    prev_state = state.get("previous_regime_state")

    if active_mode == recommended_mode or recommended_mode == "cash":
        streak = 0
    else:
        same_pair = (
            state.get("last_active_mode") == active_mode
            and state.get("last_recommended_mode") == recommended_mode
        )
        streak = int(state.get("mode_mismatch_streak", 0)) + 1 if same_pair else 1

    new_state: dict[str, Any] = {
        "previous_regime_state": current_regime_state,
        "mode_mismatch_streak": streak,
        "last_active_mode": active_mode,
        "last_recommended_mode": recommended_mode,
        "last_run_date": today.isoformat(),
    }
    return new_state, prev_state, streak
