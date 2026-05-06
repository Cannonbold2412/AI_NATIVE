"""Validate editor patches before persisting (selectors, intent, destructive pairing)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.compiler.action_semantics import action_name
from app.compiler.destructive_semantics import destructive_compiler_step
from app.compiler.intent_access import get_effective_intent_from_skill_step
from app.compiler.patch import deep_merge
from app.compiler.selector_filters import selector_passes_filters
from app.compiler.wait_for_shape import destructive_wait_for_is_non_none
from app.editor.step_view import skill_step_for_destructive_check
from app.policy.intent_ontology import sanitize_intent_token


def _merge_step_shell(step: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(step)
    for key in (
        "target",
        "signals",
        "validation",
        "recovery",
        "confidence_protocol",
        "decision_policy",
    ):
        if key in patch and isinstance(patch[key], dict):
            base = out.get(key) or {}
            out[key] = deep_merge(dict(base), dict(patch[key]))
    if "action" in patch and isinstance(patch["action"], dict):
        current = out.get("action")
        base = dict(current) if isinstance(current, dict) else {"action": str(current or "")}
        out["action"] = deep_merge(base, dict(patch["action"]))
    if "intent" in patch and isinstance(patch["intent"], str):
        out["intent"] = str(patch["intent"]).strip()
        signals = dict(out.get("signals") or {})
        sem = dict(signals.get("semantic") or {})
        resolved = out["intent"]
        if resolved:
            sem["final_intent"] = resolved
            sem["llm_intent"] = resolved
        signals["semantic"] = sem
        out["signals"] = signals
    if "value" in patch:
        out["value"] = patch["value"]
    if "url" in patch and isinstance(patch["url"], str):
        out["url"] = str(patch["url"]).strip()
    return out


def _coerce_scroll_delta(raw: Any) -> int:
    if raw is None:
        raise ValueError("scroll_amount_required")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("scroll_amount_must_be_integer") from exc


def validate_editor_patch(step: dict[str, Any], patch: dict[str, Any], policy: dict[str, Any]) -> None:
    """Raise ValueError with a human-readable message if the patch is not allowed."""
    merged = _merge_step_shell(step, patch)

    if "intent" in patch:
        raw = str(patch.get("intent") or "").strip()
        if not raw:
            raise ValueError("intent_empty")
        if not sanitize_intent_token(raw, ""):
            raise ValueError("invalid_intent_slug")

    act = action_name(merged).lower()
    if act == "navigate":
        invalid_keys = sorted(set(patch) - {"intent", "action", "url", "validation", "recovery"})
        if invalid_keys:
            raise ValueError("navigate_step_allows_only_url_intent_validation_recovery")
        action_patch = patch.get("action")
        url = ""
        if isinstance(action_patch, dict):
            url = str(action_patch.get("url") or "").strip()
        url = url or str(patch.get("url") or merged.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("navigate_url_must_be_http_url")
        return
    if act == "scroll":
        invalid_keys = sorted(set(patch) - {"intent", "action"})
        if invalid_keys:
            raise ValueError("scroll_step_allows_only_intent_and_action")
        action_patch = patch.get("action")
        if not isinstance(action_patch, dict):
            raise ValueError("scroll_action_patch_required")
        if str(action_patch.get("action") or "scroll").strip().lower() != "scroll":
            raise ValueError("scroll_action_kind_invalid")
        selector = str(action_patch.get("selector") or "").strip()
        if selector:
            if not selector_passes_filters(selector):
                raise ValueError("scroll_selector_failed_quality_gates")
        else:
            delta = _coerce_scroll_delta(action_patch.get("delta"))
            if abs(delta) > 20000:
                raise ValueError("scroll_amount_out_of_range")
    if act != "scroll":
        eff = get_effective_intent_from_skill_step(merged) or str(merged.get("intent") or "").strip()
        if not eff.strip():
            raise ValueError("intent_required_for_non_scroll_step")

    tgt = merged.get("target") if isinstance(merged.get("target"), dict) else {}
    primary = str(tgt.get("primary_selector") or "").strip()
    if primary and not selector_passes_filters(primary):
        raise ValueError("primary_selector_failed_quality_gates")
    for fb in tgt.get("fallback_selectors") or []:
        s = str(fb).strip()
        if s and not selector_passes_filters(s):
            raise ValueError("fallback_selector_failed_quality_gates")

    if destructive_compiler_step(skill_step_for_destructive_check(merged), policy):
        wf = (merged.get("validation") or {}).get("wait_for") or {}
        wf_d = dict(wf) if isinstance(wf, dict) else {}
        if not destructive_wait_for_is_non_none(wf_d):
            raise ValueError("destructive_step_requires_non_none_wait_for")
        anchors = (merged.get("signals") or {}).get("anchors") or []
        if not anchors:
            raise ValueError("destructive_step_requires_signals_anchors")
