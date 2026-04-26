"""Deterministic human-readable step descriptions for the editor UI."""

from __future__ import annotations

from typing import Any

from app.compiler.action_semantics import action_name
from app.compiler.intent_access import get_effective_intent_from_skill_step


def _visible_label(step: dict[str, Any]) -> str:
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    dom = signals.get("dom") if isinstance(signals.get("dom"), dict) else {}
    target = step.get("target") if isinstance(step.get("target"), dict) else {}
    semantic = signals.get("semantic") if isinstance(signals.get("semantic"), dict) else {}
    text = str(dom.get("inner_text") or target.get("inner_text") or semantic.get("normalized_text") or "").strip()
    if len(text) > 72:
        return text[:69] + "…"
    return text


def describe_step(step: dict[str, Any], step_index: int) -> str:
    n = step_index + 1
    act = action_name(step).lower()
    intent = get_effective_intent_from_skill_step(step) or str(step.get("intent") or "").strip()
    label = _visible_label(step)
    sel = str((step.get("target") or {}).get("primary_selector") or "").strip()

    if act == "scroll":
        return f"Step {n}: Scroll the page"
    if act == "navigate" or act == "goto":
        ctx = (step.get("signals") or {}).get("context") or {}
        url = str(ctx.get("page_url") or "").strip()
        if url:
            return f"Step {n}: Go to {url[:80]}{'…' if len(url) > 80 else ''}"
        return f"Step {n}: Navigate"
    if act == "fill":
        v = step.get("value")
        tail = f' "{label}"' if label else ""
        if v is not None and str(v):
            return f"Step {n}: Fill{tail} with value"
        return f"Step {n}: Fill{tail}"
    if act == "click":
        quoted = f'"{label}"' if label else ""
        intent_part = f" ({intent})" if intent else ""
        if quoted:
            return f"Step {n}: Click on {quoted}{intent_part}".strip()
        if sel:
            return f"Step {n}: Click target {sel}{intent_part}".strip()
        return f"Step {n}: Click{intent_part}".strip()
    if act:
        extra = f" — {intent}" if intent else ""
        return f"Step {n}: {act}{extra}".strip()
    return f"Step {n}: {intent or 'Recorded action'}".strip()
