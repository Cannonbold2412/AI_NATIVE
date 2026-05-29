"""Validate editor patches before persisting (selectors, intent, destructive pairing)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from conxa_compile.compiler.action_semantics import action_name
from conxa_compile.compiler.destructive_semantics import destructive_compiler_step
from conxa_compile.compiler.intent_access import get_effective_intent_from_skill_step
from conxa_compile.compiler.patch import deep_merge
from conxa_compile.compiler.selector_filters import selector_passes_filters
from conxa_compile.compiler.wait_for_shape import destructive_wait_for_is_non_none
from conxa_compile.editor.action_registry import action_spec, is_supported_action
from conxa_compile.editor.step_view import skill_step_for_destructive_check
from conxa_compile.policy.intent_ontology import sanitize_intent_token


def _merge_step_shell(step: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(step)
    for key in (
        "target",
        "signals",
        "frame",
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


def _validate_frame_patch(raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("frame_must_be_object")
    chain = raw.get("chain")
    if chain in (None, []):
        return
    if not isinstance(chain, list):
        raise ValueError("frame_chain_must_be_array")
    for index, item in enumerate(chain):
        if not isinstance(item, dict):
            raise ValueError(f"frame_chain_{index}_must_be_object")
        selector = str(item.get("selector") or "").strip()
        if not selector:
            raise ValueError(f"frame_chain_{index}_selector_required")
        lowered = selector.lower()
        if lowered.startswith(("/", "./", "//")) or "xpath" in lowered:
            raise ValueError(f"frame_chain_{index}_selector_must_not_be_xpath")
        fallbacks = item.get("fallback_selectors") or []
        if not isinstance(fallbacks, list):
            raise ValueError(f"frame_chain_{index}_fallback_selectors_must_be_array")
        for fb in fallbacks:
            fb_text = str(fb or "").strip()
            if fb_text.lower().startswith(("/", "./", "//")) or "xpath" in fb_text.lower():
                raise ValueError(f"frame_chain_{index}_fallback_selector_must_not_be_xpath")


def _coerce_scroll_delta(raw: Any) -> int:
    if raw is None:
        raise ValueError("scroll_amount_required")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("scroll_amount_must_be_integer") from exc


def validate_editor_patch(step: dict[str, Any], patch: dict[str, Any], policy: dict[str, Any]) -> None:
    """Raise ValueError with a human-readable message if the patch is not allowed."""
    if "frame" in patch:
        _validate_frame_patch(patch.get("frame"))

    merged = _merge_step_shell(step, patch)

    if "intent" in patch:
        raw = str(patch.get("intent") or "").strip()
        if not raw:
            raise ValueError("intent_empty")
        if not sanitize_intent_token(raw, ""):
            raise ValueError("invalid_intent_slug")

    act = action_name(merged).lower()
    spec = action_spec(act)
    if not is_supported_action(act):
        raise ValueError("unsupported_action_kind")
    if spec.marker:
        invalid_keys = sorted(set(patch))
        if invalid_keys:
            raise ValueError("recording_marker_steps_are_read_only")
        return
    if act == "navigate":
        invalid_keys = sorted(set(patch) - {"intent", "action", "url", "validation", "recovery", "frame"})
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
        invalid_keys = sorted(set(patch) - {"intent", "action", "frame"})
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
        return
    if act in {"wait", "screenshot"}:
        invalid_keys = sorted(set(patch) - {"intent", "action", "validation", "recovery", "value", "frame"})
        if invalid_keys:
            raise ValueError(f"{act}_step_allows_only_action_intent_validation_recovery")
    if act in {"check", "assert"}:
        invalid_keys = sorted(
            set(patch)
            - {
                "intent",
                "action",
                "check_kind",
                "check_pattern",
                "check_threshold",
                "check_selector",
                "check_text",
                "signals",
                "recovery",
                "frame",
            }
        )
        if invalid_keys:
            raise ValueError("check_step_allows_only_check_fields")
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
