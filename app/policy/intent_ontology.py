"""Deterministic intent normalization and ontology checks (LLM output validated here)."""

from __future__ import annotations

import re
from typing import Any

_INTENT_RE = re.compile(r"^[a-z][a-z0-9_]{2,80}$")


def generic_intents(policy: dict[str, Any]) -> set[str]:
    intent_sec = policy.get("intent") if isinstance(policy, dict) else {}
    raw = intent_sec.get("generic_intents") if isinstance(intent_sec, dict) else None
    if isinstance(raw, list):
        return {str(x).strip().lower() for x in raw}
    return {
        "",
        "interact",
        "perform_action",
        "provide_input",
        "advance_ui_flow",
        "enter_form_value",
        "activate_control",
        "focus_input",
        "click_button",
        "click_input",
        "focus_button",
        "focus_input",
    }


_TAG_ONLY_HINTS = frozenset(
    {
        "button",
        "input",
        "textarea",
        "select",
        "a",
        "div",
        "span",
        "target",
        "form",
        "label",
        "link",
        "path",
        "svg",
        "g",
    }
)

_STRUCTURE_CLICK_INTENTS = frozenset({"click_path", "click_span", "click_div", "click_svg", "click_g"})


def sanitize_intent_token(value: str, fallback: str) -> str:
    intent = "_".join(value.strip().lower().split())
    if intent == "perform_action":
        return fallback
    if not _INTENT_RE.match(intent):
        return fallback
    return intent


def _visible_text_for_intent(ev: dict[str, Any]) -> str:
    target = ev.get("target") or {}
    semantic = ev.get("semantic") or {}
    return str(target.get("inner_text") or semantic.get("normalized_text") or "").strip()


def _upgrade_tag_only_action_intent(ev: dict[str, Any], intent: str, action: str, policy: dict[str, Any]) -> str:
    """Replace click_/focus_ + bare tag hints with text-derived slugs when visible copy exists."""
    intent_sec = policy.get("intent") if isinstance(policy, dict) else {}
    if not bool(intent_sec.get("collapse_tag_only_action_intents", True)):
        return intent
    if action not in {"click", "focus"}:
        return intent
    lowered = intent.lower()
    for prefix in ("click_", "focus_"):
        if not lowered.startswith(prefix):
            continue
        hint = lowered[len(prefix) :]
        if hint not in _TAG_ONLY_HINTS:
            return intent
        raw_text = _visible_text_for_intent(ev)
        if len(raw_text) < 2:
            return intent
        et = str((ev.get("target") or {}).get("tag") or (ev.get("semantic") or {}).get("role") or "element")
        slug, _conf = semantic_slug_from_text(et, raw_text, policy)
        if not slug or slug in generic_intents(policy):
            return intent
        if prefix == "focus_" and slug.startswith("activate_control_"):
            body = slug[len("activate_control_") :]
            candidate = sanitize_intent_token(f"focus_{body}", intent)
        elif prefix == "focus_" and slug.startswith("provide_input_"):
            body = slug[len("provide_input_") :]
            candidate = sanitize_intent_token(f"focus_{body}", intent)
        else:
            candidate = sanitize_intent_token(slug, intent)
        if candidate == intent or not candidate:
            return intent
        return candidate
    return intent


def intent_specificity_score(intent: str, policy: dict[str, Any]) -> float:
    """Heuristic 0..1: longer multi-token non-generic intents score higher (for gates / audit)."""
    fin = str(intent or "").strip().lower()
    if not fin or fin in generic_intents(policy):
        return 0.0
    parts = [p for p in fin.replace("-", "_").split("_") if len(p) >= 2]
    score = 0.35 + 0.11 * min(len(parts), 6)
    if any(len(p) >= 6 for p in parts):
        score += 0.12
    if fin.startswith(("click_", "focus_")) and len(parts) >= 2 and parts[-1] not in _TAG_ONLY_HINTS:
        score += 0.1
    return round(min(1.0, score), 3)


def normalize_compiler_intent(ev: dict[str, Any], llm_intent: str, policy: dict[str, Any]) -> str:
    """Prefer specific LLM intent; otherwise derive deterministic slug from element context."""
    action = str((ev.get("action") or {}).get("action") or "").lower()
    normalized = str(llm_intent or "").strip().lower().replace(" ", "_")
    if normalized in _STRUCTURE_CLICK_INTENTS:
        normalized = ""
    generics = generic_intents(policy)
    if normalized and normalized not in generics and "_" in normalized:
        base = sanitize_intent_token(normalized, _derive_fallback_intent_slug(ev, action, policy))
        refined = _refine_intent_for_action_semantics(ev, base, policy)
        return _upgrade_tag_only_action_intent(ev, refined, action, policy)
    base = _derive_fallback_intent_slug(ev, action, policy)
    refined = _refine_intent_for_action_semantics(ev, base, policy)
    return _upgrade_tag_only_action_intent(ev, refined, action, policy)


def _target_is_editable_control(ev: dict[str, Any]) -> bool:
    target = ev.get("target") or {}
    tag = str(target.get("tag") or "").lower()
    return tag in {"input", "textarea", "select"}


def _refine_intent_for_action_semantics(ev: dict[str, Any], intent: str, policy: dict[str, Any]) -> str:
    """Map action-centric intents to purpose when action implies focus, not activation (policy-gated)."""
    intent_sec = policy.get("intent") if isinstance(policy.get("intent"), dict) else {}
    if not bool(intent_sec.get("rewrite_click_on_editable_to_focus", True)):
        return intent
    action = str((ev.get("action") or {}).get("action") or "").lower()
    if action not in {"click", "focus"}:
        return intent
    if not _target_is_editable_control(ev):
        return intent
    it = str((ev.get("semantic") or {}).get("input_type") or "").lower()
    if it == "submit":
        return intent
    lowered = intent.lower()
    if lowered.startswith("click_"):
        return sanitize_intent_token("focus_" + lowered[len("click_") :], intent)
    return intent


def _target_has_actionable_semantics(target: dict[str, Any], semantic: dict[str, Any]) -> bool:
    role = str(semantic.get("role") or target.get("role") or "").lower()
    if role in {"button", "link", "checkbox", "menuitem", "tab", "switch", "combobox", "textbox"}:
        return True
    if str(target.get("aria_label") or "").strip():
        return True
    if str(target.get("name") or "").strip():
        return True
    if len(str(target.get("inner_text") or "").strip()) >= 2:
        return True
    return False


def _derive_fallback_intent_slug(ev: dict[str, Any], action: str, policy: dict[str, Any]) -> str:
    target = ev.get("target") or {}
    semantic = ev.get("semantic") or {}
    tag_l = str(target.get("tag") or "").lower()
    if tag_l in {"path", "svg", "g"} or (tag_l in {"div", "span"} and not _target_has_actionable_semantics(target, semantic)):
        ih = str(semantic.get("intent_hint") or "").strip().lower()
        vis = _visible_text_for_intent(ev)
        if ih == "commit_form":
            return "submit_form_action"
        if ih == "navigate" or tag_l == "a":
            if len(vis) >= 2:
                slug_t, _c = semantic_slug_from_text("link", vis, policy)
                return sanitize_intent_token(slug_t, "navigate_link_target")
            return "navigate_link_target"
        if ih == "activate_control" and len(vis) >= 2:
            slug_t, _c = semantic_slug_from_text("button", vis, policy)
            return sanitize_intent_token(slug_t, "activate_control")
        if ih == "provide_input" and len(vis) >= 2:
            slug_t, _c = semantic_slug_from_text("input", vis, policy)
            return sanitize_intent_token(slug_t, "provide_input")
        if ih == "choose_option":
            return "choose_option"
        if len(vis) >= 2:
            slug_t, _c = semantic_slug_from_text(str(target.get("tag") or "element"), vis, policy)
            return sanitize_intent_token(slug_t, "advance_ui_flow")
        return "advance_ui_flow"
    raw_hint = (
        str(target.get("name") or "")
        or str(target.get("aria_label") or "")
        or str(target.get("placeholder") or "")
        or str(target.get("tag") or "")
        or str(semantic.get("role") or "")
        or "target"
    ).strip().lower()
    hint = "".join(ch if ch.isalnum() else "_" for ch in raw_hint).strip("_") or "target"
    if action == "focus":
        return f"focus_{hint}"
    if action in {"type", "fill"}:
        return f"enter_{hint}_value"
    if action == "click":
        return f"click_{hint}"
    if action == "scroll":
        return "scroll_viewport"
    if action in {"navigate", "open", "go_to"}:
        return "navigate_to_page"
    return "advance_ui_flow"


def semantic_slug_from_text(element_type: str, raw_text: str, policy: dict[str, Any]) -> tuple[str, float]:
    """Generic intent label from visible text + element type (no domain-specific login mapping)."""
    text = " ".join(raw_text.lower().split())
    conf_sec = policy.get("intent", {}) if isinstance(policy, dict) else {}
    conf_map = conf_sec.get("semantic_fallback_confidence") if isinstance(conf_sec, dict) else {}
    default_c = float(conf_map.get("default", 0.6)) if isinstance(conf_map, dict) else 0.6
    btn_c = float(conf_map.get("button_submit_like", 0.82)) if isinstance(conf_map, dict) else 0.82
    field_c = float(conf_map.get("field_token", 0.78)) if isinstance(conf_map, dict) else 0.78
    input_c = float(conf_map.get("input_generic", 0.7)) if isinstance(conf_map, dict) else 0.7

    et = (element_type or "").lower()
    slug_base = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")[:48] or "element"

    if et == "button" and text:
        return f"activate_control_{slug_base}", btn_c
    if et == "input" and text:
        return f"provide_input_{slug_base}", field_c
    if et == "input":
        return "provide_input", input_c
    if text:
        return f"interact_{slug_base}", default_c
    return "interact", default_c
