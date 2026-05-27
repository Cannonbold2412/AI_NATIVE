"""High-level LLM abstraction for selector generation + runtime recovery.

Wraps app.llm.client.call_llm with task-specific helpers.
call_llm internally uses the multi-provider router (if available) or falls back to single-endpoint config.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.llm.client import call_llm


class SelectorCandidate:
    """One LLM-generated selector candidate with rank + rationale."""

    __slots__ = ("selector", "rank", "rationale", "intent")

    def __init__(self, selector: str, rank: int, rationale: str = "", intent: str = ""):
        self.selector = selector
        self.rank = rank
        self.rationale = rationale
        self.intent = intent

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "rank": self.rank,
            "rationale": self.rationale,
            "intent": self.intent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectorCandidate":
        return cls(
            selector=str(data.get("selector") or ""),
            rank=int(data.get("rank") or 0),
            rationale=str(data.get("rationale") or ""),
            intent=str(data.get("intent") or ""),
        )


def generate_selector_candidates(
    *,
    dom_snippet: str,
    element_bbox: dict[str, int],
    element_ancestors: list[dict[str, Any]],
    surrounding_text: str,
    action_type: str,
    target_dom: dict[str, Any] | None = None,
    candidates_wanted: int | None = None,
    model: str | None = None,
    error_detail: list[str] | None = None,
) -> list[SelectorCandidate]:
    """Generate Playwright CSS selector candidates for one element.

    Returns empty list on LLM failure. Caller should validate candidates against
    the recorded DOM snapshot before accepting them.
    """
    n = candidates_wanted or settings.llm_selector_candidates
    payload = {
        "task": "selector_generation",
        "model": model,
        "input": {
            "dom_snippet": dom_snippet,
            "element_bbox": element_bbox,
            "ancestors": element_ancestors,
            "surrounding_text": surrounding_text,
            "action_type": action_type,
            "target_dom": target_dom or {},
            "candidates_wanted": n,
        },
    }
    data = call_llm(
        "selector_generation",
        payload,
        settings.llm_selector_timeout_ms,
        error_detail=error_detail,
    )
    if data is None:
        return []

    raw_candidates = data.get("candidates")
    if not isinstance(raw_candidates, list):
        return []

    out: list[SelectorCandidate] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        sel = str(item.get("selector") or "").strip()
        if not sel:
            continue
        out.append(SelectorCandidate.from_dict(item))
    return out


def resolve_element_recovery(
    *,
    semantic_description: str,
    original_bbox: dict[str, int] | None,
    original_ancestors: list[dict[str, Any]] | None,
    current_dom_snippet: str,
    action_type: str,
    model: str | None = None,
    error_detail: list[str] | None = None,
) -> dict[str, Any] | None:
    """Runtime Tier 3 recovery: locate an element on the current DOM via LLM.

    Returns {selector, confidence, reason} or None on failure.
    """
    payload = {
        "task": "recovery_resolve",
        "model": model,
        "input": {
            "semantic_description": semantic_description,
            "original_bbox": original_bbox or {},
            "original_ancestors": original_ancestors or [],
            "current_dom_snippet": current_dom_snippet,
            "action_type": action_type,
        },
    }
    data = call_llm(
        "recovery_resolve",
        payload,
        settings.llm_selector_timeout_ms,
        error_detail=error_detail,
    )
    if data is None:
        return None
    sel = str(data.get("selector") or "").strip()
    if not sel:
        return None
    return {
        "selector": sel,
        "confidence": float(data.get("confidence") or 0.0),
        "reason": str(data.get("reason") or ""),
    }


def infer_workflow_intent(
    *,
    steps_summary: list[dict[str, Any]],
    page_urls: list[str],
    model: str | None = None,
    error_detail: list[str] | None = None,
) -> dict[str, Any] | None:
    """Single LLM call to build workflow intent graph (Claude Browser-style)."""
    payload = {
        "task": "workflow_intent",
        "model": model,
        "input": {
            "steps": steps_summary,
            "page_urls": page_urls,
        },
    }
    data = call_llm(
        "workflow_intent",
        payload,
        settings.llm_selector_timeout_ms,
        error_detail=error_detail,
    )
    if data is None:
        return None
    return {
        "goal": str(data.get("goal") or ""),
        "steps": list(data.get("steps") or []),
        "decision_points": list(data.get("decision_points") or []),
        "expected_end_state": dict(data.get("expected_end_state") or {}),
    }
