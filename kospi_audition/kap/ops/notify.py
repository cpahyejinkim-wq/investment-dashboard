"""Slack + Email notifications (opt-in via env vars).

  KAP_SLACK_WEBHOOK : if set, send to this incoming-webhook URL.
  KAP_SMTP_HOST/PORT/USER/PASSWORD/FROM/TO : if all set, send email.

The dispatcher decides what to alert on:
  - Hard stop breaches (always)
  - Regime state transitions (compare with previous run via regime_history)
  - Mode mismatch lasting >= MODE_TRANSITION['alert_mismatch_days']
"""

from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any

from loguru import logger

from kap import config
from kap.ops.retry import retry


@dataclass
class AlertChannels:
    slack_webhook: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_user: str | None
    smtp_password: str | None
    smtp_from: str | None
    smtp_to: str | None

    @classmethod
    def from_env(cls) -> "AlertChannels":
        return cls(
            slack_webhook=os.environ.get("KAP_SLACK_WEBHOOK") or None,
            smtp_host=os.environ.get("KAP_SMTP_HOST") or None,
            smtp_port=int(os.environ["KAP_SMTP_PORT"]) if os.environ.get("KAP_SMTP_PORT") else None,
            smtp_user=os.environ.get("KAP_SMTP_USER") or None,
            smtp_password=os.environ.get("KAP_SMTP_PASSWORD") or None,
            smtp_from=os.environ.get("KAP_SMTP_FROM") or None,
            smtp_to=os.environ.get("KAP_SMTP_TO") or None,
        )

    @property
    def has_slack(self) -> bool:
        return bool(self.slack_webhook)

    @property
    def has_email(self) -> bool:
        return all([self.smtp_host, self.smtp_port, self.smtp_from, self.smtp_to])


@retry(attempts=3, initial_delay=1.5)
def _post_slack(webhook: str, text: str) -> None:
    req = urllib.request.Request(
        webhook,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"slack post failed: {exc}") from exc


@retry(attempts=3, initial_delay=1.5)
def _send_email(channels: AlertChannels, subject: str, body: str) -> None:
    assert channels.smtp_host and channels.smtp_port
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = channels.smtp_from or ""
    msg["To"] = channels.smtp_to or ""
    with smtplib.SMTP(channels.smtp_host, channels.smtp_port, timeout=15) as smtp:
        if channels.smtp_user and channels.smtp_password:
            smtp.starttls()
            smtp.login(channels.smtp_user, channels.smtp_password)
        smtp.send_message(msg)


def dispatch(text: str, subject: str = "[KAP] alert", channels: AlertChannels | None = None) -> None:
    """Best-effort dispatch — never raises so the scheduler keeps running."""
    ch = channels or AlertChannels.from_env()
    sent = False
    if ch.has_slack:
        try:
            _post_slack(ch.slack_webhook, text)  # type: ignore[arg-type]
            sent = True
        except Exception as exc:  # noqa: BLE001
            logger.error("slack dispatch failed: {}", exc)
    if ch.has_email:
        try:
            _send_email(ch, subject, text)
            sent = True
        except Exception as exc:  # noqa: BLE001
            logger.error("email dispatch failed: {}", exc)
    if not sent:
        logger.info("[no-op alert | no channels configured] {}", text)


# ---------------------------------------------------------------------------
# Domain alerts
# ---------------------------------------------------------------------------


def build_risk_alert_message(alerts: list[dict[str, Any]]) -> str | None:
    if not alerts:
        return None
    lines = [f"⚠ Risk alerts ({len(alerts)})"]
    for a in alerts[:20]:
        lines.append(
            f"  - {a['ticker']} {a['type']} price={a['price']} stop={a['stop_loss']} mode={a['mode']}"
        )
    return "\n".join(lines)


def build_regime_change_message(
    prev_state: str | None, current_state: str, recommended_mode: str
) -> str | None:
    if prev_state is None or prev_state == current_state:
        return None
    return (
        f"🌐 Regime transition: {prev_state} → {current_state}. "
        f"권장 Mode: {recommended_mode}."
    )


def build_mode_mismatch_message(active_mode: str, recommended_mode: str, days: int) -> str | None:
    threshold = int(config.MODE_TRANSITION["alert_mismatch_days"])
    if recommended_mode in (None, "cash") or active_mode == recommended_mode:
        return None
    if days < threshold:
        return None
    return (
        f"🔁 Mode mismatch: 현재 {active_mode}, 권장 {recommended_mode} ({days}일 연속). "
        f"전환을 고려하세요. (Soft Migration: 기존 포지션은 진입 모드 룰 유지)"
    )
