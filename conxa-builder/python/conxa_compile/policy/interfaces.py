"""Typed interfaces for policy-driven replacement of former hardcoded sites."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class PolicyDict(TypedDict, total=False):
    """Subset shape for policy sections passed into pure functions."""

    version: str
    confidence: dict[str, Any]
    uncertainty: dict[str, Any]
    workflow: dict[str, Any]
    anchors: dict[str, Any]
    selectors: dict[str, Any]
    validation: dict[str, Any]
    recovery_defaults: dict[str, Any]
    intent: dict[str, Any]
    signals: dict[str, Any]
    capture_profile: dict[str, Any]
    scroll_defaults: dict[str, Any]
    timing_by_action: dict[str, Any]


class ReplacementTarget:
    """Catalog keys for migration tracking."""

    WORKFLOW_ORDERING = "workflow_ordering"
    SUBMIT_DETECTION = "submit_detection"
    SELECTOR_PRIORITY = "selector_priority"
    VALIDATION_STATIC = "validation_static"
    INTENT_RULES = "intent_rules"
    STATE_URL_LOGIN = "state_url_login"
    SIGNAL_CAPTURE = "signal_capture"
    RECOVERY_FIXED = "recovery_fixed"
    CONFIDENCE_THRESHOLDS = "confidence_thresholds"


class PolicyLoader(Protocol):
    def as_dict(self) -> dict[str, Any]: ...
