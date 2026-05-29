"""Policy + pattern-driven wait_for rules from FINAL_INTENT (facets + builtins; no site-specific flows)."""

from __future__ import annotations

from typing import Any

from app.compiler.action_semantics import action_name
from app.compiler.decision_layer import intent_primary_validation_enabled
from app.compiler.intent_access import get_effective_intent
from app.compiler.destructive_semantics import destructive_compiler_step
from app.compiler.selector_filters import selector_passes_filters

Step = dict[str, Any]

VALID_WAIT_TYPES = frozenset({"url_change", "intent_outcome", "element_appear", "element_disappear", "none"})


def _normalize_facet_wait_type(wt: str) -> str:
    """Legacy policies used dom_change; runtime validation uses intent_outcome + mapped selectors."""
    w = str(wt or "").strip().lower()
    if w == "dom_change":
        return "intent_outcome"
    return w


def selector_wait_target_from_step(step: Step) -> str:
    """First passing selector string for element_appear / element_disappear (deterministic order)."""
    selectors = step.get("selectors") if isinstance(step.get("selectors"), dict) else {}
    for key in ("text_based", "aria", "xpath", "css"):
        raw = str(selectors.get(key) or "").strip()
        if raw and selector_passes_filters(raw):
            return raw[:480]
    return ""


def intent_validation_facets_from_policy(policy: dict[str, Any]) -> list[dict[str, Any]]:
    dl = policy.get("decision_layer") if isinstance(policy.get("decision_layer"), dict) else {}
    raw = dl.get("intent_validation_facets")
    if not isinstance(raw, list):
        return []
    return [f for f in raw if isinstance(f, dict)]


def try_intent_validation_facets(
    step: Step,
    policy: dict[str, Any],
    *,
    is_commit: bool,
    timeout: int,
    submit_min: int,
    nav_min: int,
) -> dict[str, Any] | None:
    """Policy-defined intent_substrings + wait_for_type."""
    if not intent_primary_validation_enabled(policy):
        return None
    intent_l = get_effective_intent(step.get("semantic") or {}).lower()
    if not intent_l:
        return None
    action = action_name(step).lower()
    for facet in intent_validation_facets_from_policy(policy):
        actions = [str(a).lower() for a in (facet.get("actions") or ["click"])]
        if action not in actions:
            continue
        subs = [str(s).lower() for s in (facet.get("intent_substrings") or []) if s]
        if not subs or not any(s in intent_l for s in subs):
            continue
        if bool(facet.get("require_commit", False)) and not is_commit:
            continue
        if bool(facet.get("skip_when_commit", False)) and is_commit:
            continue
        wt = _normalize_facet_wait_type(str(facet.get("wait_for_type") or "").strip().lower())
        if wt not in VALID_WAIT_TYPES:
            continue
        extra_ms = int(facet.get("min_timeout_ms") or 0)
        if is_commit:
            t_floor = max(timeout, submit_min, extra_ms)
        elif wt == "url_change":
            t_floor = max(timeout, nav_min, extra_ms)
        else:
            t_floor = max(timeout, extra_ms) if extra_ms else timeout
        tgt = ""
        if wt in {"element_appear", "element_disappear"}:
            tgt = selector_wait_target_from_step(step)
            if not tgt:
                continue
        return {"type": wt, "target": tgt, "timeout": t_floor}
    return None


def disclosure_roles(step: Step) -> set[str]:
    """Roles / ARIA hints suggesting open/select disclosure (pattern-based)."""
    semantic = step.get("semantic") or {}
    target = step.get("target") or {}
    role = str(semantic.get("role") or target.get("role") or "").lower()
    out = {role} if role else set()
    aria = str((step.get("selectors") or {}).get("aria") or "").lower()
    if "haspopup" in aria or "expanded" in aria or "controls" in aria:
        out.add("disclosure")
    return out


def try_open_select_wait_rule(
    step: Step,
    policy: dict[str, Any],
    *,
    is_commit: bool,
    timeout: int,
    nav_min: int,
) -> dict[str, Any] | None:
    """Non-commit clicks on disclosure controls → element_appear when selector target exists."""
    if not intent_primary_validation_enabled(policy):
        return None
    val = policy.get("validation") if isinstance(policy.get("validation"), dict) else {}
    if not bool(val.get("infer_element_appear_for_disclosure_roles", True)):
        return None
    if is_commit:
        return None
    action = str((step.get("action") or {}).get("action") or "").lower()
    if action != "click":
        return None
    roles = disclosure_roles(step)
    wanted = {str(x).lower() for x in (val.get("disclosure_roles_for_element_appear") or ["combobox", "listbox", "menu", "disclosure"])}
    if not roles & wanted:
        return None
    tgt = selector_wait_target_from_step(step)
    if not tgt:
        return None
    extra_ms = int(val.get("disclosure_appear_min_timeout_ms") or 0)
    t_floor = max(timeout, nav_min, extra_ms) if nav_min else max(timeout, extra_ms)
    return {"type": "element_appear", "target": tgt, "timeout": t_floor}


def try_destructive_confirmation_wait(
    step: Step,
    policy: dict[str, Any],
    *,
    is_commit: bool,
    timeout: int,
    submit_min: int,
    nav_min: int,
) -> dict[str, Any] | None:
    """Destructive clicks: prefer waiting for confirmation UI (element_appear) when policy enabled."""
    val = policy.get("validation") if isinstance(policy.get("validation"), dict) else {}
    if not bool(val.get("destructive_require_confirmation_wait", True)):
        return None
    if is_commit or not destructive_compiler_step(step, policy):
        return None
    tgt = selector_wait_target_from_step(step)
    wt = _normalize_facet_wait_type(str(val.get("destructive_wait_for_type") or "element_appear").strip().lower())
    if wt not in VALID_WAIT_TYPES:
        wt = "element_appear"
    extra_ms = int(val.get("destructive_min_timeout_ms") or 0)
    t_floor = max(timeout, submit_min, nav_min, extra_ms)
    if wt == "element_appear":
        if not tgt:
            wt = "intent_outcome"
            tgt = ""
            t_floor = max(timeout, submit_min, extra_ms)
        return {"type": wt, "target": tgt, "timeout": t_floor}
    return {"type": wt, "target": "", "timeout": t_floor}
