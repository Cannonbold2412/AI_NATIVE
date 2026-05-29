"""Resolve per-action timing from policy + settings (replaces single wait_for for all events)."""

from __future__ import annotations

from typing import Any

from app.config import settings


def resolve_event_timing(action_name: str, policy: dict[str, Any]) -> dict[str, str | int]:
    table = policy.get("timing_by_action") if isinstance(policy, dict) else {}
    if not isinstance(table, dict):
        table = {}
    row = table.get((action_name or "").lower()) or table.get("default") or {}
    if not isinstance(row, dict):
        row = {}
    wait_for = str(row.get("wait_for") or "load")
    timeout_ms = row.get("timeout_ms")
    if timeout_ms is None:
        timeout_ms = int(settings.default_action_timeout_ms)
    return {"wait_for": wait_for, "timeout": int(timeout_ms)}
