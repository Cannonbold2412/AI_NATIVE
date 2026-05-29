"""Shared step action / commit / editable-target semantics (single source for v3 + validation_planner)."""

from __future__ import annotations

from typing import Any

from app.compiler.intent_access import get_effective_intent

Step = dict[str, Any]


def action_name(step: Step) -> str:
    action = step.get("action") or {}
    if isinstance(action, dict):
        return str(action.get("action") or "")
    return str(action)


def is_editable_target(step: Step) -> bool:
    target = step.get("target") or {}
    tag = str(target.get("tag") or "").lower()
    return tag in {"input", "textarea", "select"}


def is_editable_field_click(step: Step) -> bool:
    if action_name(step).lower() != "click":
        return False
    return is_editable_target(step)


def looks_like_submit(step: Step, policy: dict[str, Any]) -> bool:
    """Policy-driven primary-action / submit control detection."""
    wf = policy.get("workflow") if isinstance(policy.get("workflow"), dict) else {}
    text_tokens = [str(t).lower() for t in (wf.get("submit_text_tokens") or [])]
    intent_sub = [str(t).lower() for t in (wf.get("submit_intent_substrings") or ["submit"])]
    btn_types = {str(x).lower() for x in (wf.get("submit_button_types") or ["submit", "button"])}
    semantic = step.get("semantic") or {}
    target = step.get("target") or {}
    llm_intent = get_effective_intent(semantic).lower()
    if any(sub in llm_intent for sub in intent_sub):
        return True
    if action_name(step).lower() != "click":
        return False
    text = " ".join(
        [
            str(semantic.get("normalized_text") or ""),
            str(target.get("inner_text") or ""),
            str(target.get("name") or ""),
            str(target.get("aria_label") or ""),
        ]
    ).lower()
    if text_tokens and any(token in text for token in text_tokens):
        return True
    tag = str(target.get("tag") or "").lower()
    typ = str(target.get("type") or "").lower()
    role = str(target.get("role") or semantic.get("role") or "").lower()
    if typ == "submit":
        return True
    if tag == "button" and (typ in btn_types or role == "button") and text.strip():
        return bool(text_tokens) and any(token in text for token in text_tokens)
    return False


def commit_intent_hit(step: Step, policy: dict[str, Any]) -> bool:
    """Whether effective intent + submit heuristics indicate a commit / primary action."""
    wf = policy.get("workflow") if isinstance(policy.get("workflow"), dict) else {}
    subs = [str(s).lower() for s in (wf.get("commit_intent_substrings") or ["submit", "confirm"])]
    intent = get_effective_intent(step.get("semantic") or {}).lower()
    if any(sub in intent for sub in subs):
        return True
    return looks_like_submit(step, policy)
