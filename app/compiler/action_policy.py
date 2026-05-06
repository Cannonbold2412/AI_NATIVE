"""Shared action-gated recovery and retry policy."""

from __future__ import annotations

from typing import Any


RECOVERY_ACTION_TYPES = frozenset({"type", "fill", "click", "select", "focus"})
NO_RECOVERY_ACTION_TYPES = frozenset({"navigate", "goto", "go_to", "open", "check", "scroll"})
ELEMENT_ACTION_TOTAL_ATTEMPTS = 2
NAVIGATE_CHECK_TOTAL_ATTEMPTS = 3
SCROLL_MODES = frozenset({"scroll_only", "scroll_to_locate"})


def normalize_action_kind(action: Any) -> str:
    if isinstance(action, dict):
        raw = action.get("action")
    else:
        raw = action
    kind = str(raw or "").strip().lower().replace("-", "_")
    if kind in {"goto", "go_to", "open"}:
        return "navigate"
    return kind


def action_kind_from_step(step: dict[str, Any]) -> str:
    return normalize_action_kind(step.get("action") if isinstance(step, dict) else "")


def recovery_enabled_for_action(action: Any) -> bool:
    return normalize_action_kind(action) in RECOVERY_ACTION_TYPES


def total_attempts_for_action(action: Any) -> int:
    kind = normalize_action_kind(action)
    if kind in {"navigate", "check"}:
        return NAVIGATE_CHECK_TOTAL_ATTEMPTS
    if kind in RECOVERY_ACTION_TYPES:
        return ELEMENT_ACTION_TOTAL_ATTEMPTS
    return 1


def no_recovery_block(intent: str = "") -> dict[str, Any]:
    fin = str(intent or "").strip()
    return {
        "intent": fin,
        "final_intent": fin,
        "anchors": [],
        "strategies": [],
        "confidence_threshold": 0.85,
        "max_attempts": 0,
        "require_diverse_attempts": False,
    }
