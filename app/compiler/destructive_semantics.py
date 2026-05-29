"""Compile-time destructive intent detection (shared tokens with confidence audit; policy-extensible)."""

from __future__ import annotations

from typing import Any

from app.compiler.action_semantics import action_name
from app.compiler.intent_access import get_effective_intent
from app.confidence.uncertainty import DESTRUCTIVE_TOKENS

Step = dict[str, Any]


def destructive_intent_tokens(policy: dict[str, Any]) -> tuple[str, ...]:
    val = policy.get("validation") if isinstance(policy.get("validation"), dict) else {}
    extra = val.get("destructive_intent_substrings")
    if isinstance(extra, list):
        merged = list(DESTRUCTIVE_TOKENS) + [str(x).lower() for x in extra if x]
        return tuple(dict.fromkeys(merged))
    return DESTRUCTIVE_TOKENS


def step_has_destructive_intent(step: Step, policy: dict[str, Any]) -> bool:
    semantic = step.get("semantic") or {}
    if semantic.get("is_destructive") is True:
        return True
    intent = get_effective_intent(semantic).lower()
    if not intent:
        return False
    for tok in destructive_intent_tokens(policy):
        if tok and tok in intent:
            return True
    return False


def destructive_compiler_step(step: Step, policy: dict[str, Any]) -> bool:
    """True when step is an actionable click under destructive intent (compiler record shape)."""
    if action_name(step).lower() != "click":
        return False
    return step_has_destructive_intent(step, policy)
