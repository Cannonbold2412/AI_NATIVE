"""Map persisted skill JSON → editor DTOs, suggestions, and structural edits."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from app.compiler.action_semantics import action_name
from app.compiler.destructive_semantics import destructive_compiler_step
from app.compiler.intent_access import get_effective_intent, get_effective_intent_from_skill_step
from app.compiler.patch import revalidate_step
from app.compiler.wait_for_shape import (
    destructive_wait_for_is_non_none,
    leaf_wait_for_conditions,
    leaf_wait_type,
    scan_wait_for_binding_targets,
)
from app.confidence.uncertainty import audit_reference
from app.editor.describe import describe_step
from app.editor.dto import StepEditorDTO, StepFlags, StepScreenshotDTO, SuggestionItem, WorkflowResponse
from app.editor.step_view import skill_step_for_destructive_check
from app.policy.bundle import get_policy_bundle
from app.policy.intent_ontology import generic_intents


def _parse_scroll_amount(step: dict[str, Any]) -> int | None:
    action = step.get("action")
    if isinstance(action, dict):
        raw = action.get("delta")
        try:
            if raw is not None:
                return int(raw)
        except (TypeError, ValueError):
            pass
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    visual = signals.get("visual") if isinstance(signals.get("visual"), dict) else {}
    pos = str(visual.get("scroll_position") or "").strip()
    if not pos:
        return None
    _, _, y = pos.partition(",")
    try:
        return int(float(y.strip() or 0))
    except ValueError:
        return None


def _build_reference_for_audit(step: dict[str, Any]) -> dict[str, Any]:
    signals = step.get("signals") or {}
    context = signals.get("context") or {}
    return {
        "action_kind": (step.get("action") or {}).get("action")
        if isinstance(step.get("action"), dict)
        else step.get("action"),
        "target": signals.get("dom") or {},
        "selectors": signals.get("selectors") or {},
        "semantic": signals.get("semantic") or {},
        "context": {k: v for k, v in context.items() if k not in {"page_url", "page_title", "state_after", "timing"}},
        "anchors": signals.get("anchors") or [],
        "visual": signals.get("visual") or {},
        "state_after": context.get("state_after") or "",
        "page_url": context.get("page_url") or "",
        "page_title": context.get("page_title") or "",
    }


def _editable_fields(step: dict[str, Any], policy: dict[str, Any]) -> dict[str, bool]:
    act = action_name(step).lower()
    is_scroll = act == "scroll"
    dest = destructive_compiler_step(skill_step_for_destructive_check(step), policy)
    return {
        "intent": True,
        "action": False,
        "selectors": not is_scroll,
        "anchors": not is_scroll,
        "validation": not is_scroll,
        "recovery_strategies": not is_scroll,
        "value": act in {"fill", "type"},
        "parameterization": not is_scroll,
        "destructive_requires_validation": dest,
    }


def _screenshot_dto(skill_id: str, visual: dict[str, Any], asset_base_url: str) -> StepScreenshotDTO:
    def u(rel: str) -> str | None:
        if not rel or not isinstance(rel, str):
            return None
        q = urllib.parse.urlencode({"path": rel})
        return f"{asset_base_url}/skills/{urllib.parse.quote(skill_id, safe='')}/assets?{q}"

    return StepScreenshotDTO(
        full_url=u(str(visual.get("full_screenshot") or "")),
        element_url=u(str(visual.get("element_snapshot") or "")),
        scroll_url=u(str(visual.get("scroll_screenshot") or "")),
        bbox=visual.get("bbox") if isinstance(visual.get("bbox"), dict) else {},
        viewport=str(visual.get("viewport") or ""),
        scroll_position=str(visual.get("scroll_position") or ""),
    )


def _parameter_bindings_from_step(step: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface {{var}} usage in whitelisted string fields (read-only hints for UI)."""
    pat = re.compile(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}")
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def scan(path: str, text: str) -> None:
        for m in pat.finditer(text):
            key = (path, m.group(1))
            if key not in seen:
                seen.add(key)
                out.append({"variable_id": m.group(1), "path": path, "match": m.group(0)})

    tgt = step.get("target") if isinstance(step.get("target"), dict) else {}
    scan("target.primary_selector", str(tgt.get("primary_selector") or ""))
    for i, fb in enumerate(tgt.get("fallback_selectors") or []):
        scan(f"target.fallback_selectors[{i}]", str(fb))
    val = step.get("value")
    if isinstance(val, str):
        scan("value", val)
    val = step.get("validation") if isinstance(step.get("validation"), dict) else {}
    wf = val.get("wait_for") or {}
    if isinstance(wf, dict):
        scan_wait_for_binding_targets(wf, "validation.wait_for", scan)
    return out


def collect_suggestions(steps: list[dict[str, Any]], policy: dict[str, Any]) -> list[SuggestionItem]:
    items: list[SuggestionItem] = []
    gen = generic_intents(policy)

    for idx, step in enumerate(steps):
        ref = _build_reference_for_audit(step)
        for issue in audit_reference(ref):
            sev: str = "error" if issue in {"missing_selectors", "empty_primary_css", "anchors_empty_required"} else "warn"
            items.append(
                SuggestionItem(
                    step_index=idx,
                    severity=sev,  # type: ignore[arg-type]
                    code=issue,
                    message=_issue_message(issue),
                )
            )
        intent = get_effective_intent_from_skill_step(step).strip().lower()
        if intent in gen or not intent:
            items.append(
                SuggestionItem(
                    step_index=idx,
                    severity="warn",
                    code="generic_or_empty_intent",
                    message="Intent is missing or generic; choose a specific slug.",
                )
            )
        wf = (step.get("validation") or {}).get("wait_for") or {}
        wf_d = dict(wf) if isinstance(wf, dict) else {}
        pri = str((step.get("target") or {}).get("primary_selector") or "").strip()
        missing_element_appear_target = False
        for leaf in leaf_wait_for_conditions(wf_d):
            if leaf_wait_type(leaf) != "element_appear":
                continue
            tgt = str(leaf.get("target") or "").strip()
            if not tgt and not pri:
                missing_element_appear_target = True
                break
        if missing_element_appear_target:
            items.append(
                SuggestionItem(
                    step_index=idx,
                    severity="warn",
                    code="element_appear_without_target",
                    message="wait_for element_appear needs a selector target or primary_selector on the step.",
                )
            )
        if destructive_compiler_step(skill_step_for_destructive_check(step), policy):
            cw = (step.get("confidence_protocol") or {}).get("compile_warnings") or {}
            if isinstance(cw, dict) and cw.get("destructive_low_anchor_count"):
                items.append(
                    SuggestionItem(
                        step_index=idx,
                        severity="warn",
                        code="destructive_low_anchor_count",
                        message="Destructive action: add more semantic anchors before relying on this step.",
                    )
                )
            anchors = ref.get("anchors") or []
            if not anchors:
                items.append(
                    SuggestionItem(
                        step_index=idx,
                        severity="error",
                        code="destructive_missing_anchors",
                        message="Destructive step should include anchors for safe recovery.",
                    )
                )
            if not destructive_wait_for_is_non_none(wf_d):
                items.append(
                    SuggestionItem(
                        step_index=idx,
                        severity="warn",
                        code="destructive_weak_validation",
                        message="Destructive step: set an explicit wait_for (e.g. element_appear or url_change).",
                    )
                )
    return items


def _issue_message(code: str) -> str:
    return {
        "missing_selectors": "Selector bundle is empty or unusable.",
        "empty_primary_css": "Primary CSS selector is empty.",
        "anchors_empty": "No semantic anchors on this step.",
        "anchors_empty_required": "Anchors required but missing.",
        "weak_visual_bbox": "Bounding box for visual match is weak or missing.",
    }.get(code, code.replace("_", " ").title())


def step_to_dto(skill_id: str, step: dict[str, Any], step_index: int, policy: dict[str, Any], asset_base_url: str) -> StepEditorDTO:
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    semantic = signals.get("semantic") if isinstance(signals.get("semantic"), dict) else {}
    recovery = step.get("recovery") if isinstance(step.get("recovery"), dict) else {}
    validation = step.get("validation") if isinstance(step.get("validation"), dict) else {}
    visual = signals.get("visual") if isinstance(signals.get("visual"), dict) else {}

    intent_top = str(step.get("intent") or "").strip()
    final_intent = get_effective_intent(semantic) or intent_top

    gen = generic_intents(policy)
    flags = StepFlags(
        is_destructive=destructive_compiler_step(skill_step_for_destructive_check(step), policy),
        is_scroll=str(action_name(step)).lower() == "scroll",
        generic_intent=(final_intent.strip().lower() in gen) or not final_intent.strip(),
    )

    return StepEditorDTO(
        id=f"{skill_id}:{step_index}",
        step_index=step_index,
        human_readable_description=describe_step(step, step_index),
        action_type=str(action_name(step)),
        intent=intent_top,
        final_intent=final_intent,
        target=dict(step.get("target") or {}),
        selectors=dict(signals.get("selectors") or {}),
        anchors_signals=list(signals.get("anchors") or []),
        anchors_recovery=list(recovery.get("anchors") or []),
        validation={
            "wait_for": dict(validation.get("wait_for") or {}),
            "success_conditions": dict(validation.get("success_conditions") or {}),
        },
        recovery=dict(recovery),
        value=step.get("value"),
        scroll_amount=_parse_scroll_amount(step),
        input_binding=step.get("input_binding"),
        screenshot=_screenshot_dto(skill_id, visual, asset_base_url),
        editable_fields=_editable_fields(step, policy),
        flags=flags,
        parameter_bindings=_parameter_bindings_from_step(step),
    )


def build_workflow_response(skill_id: str, document: dict[str, Any], *, asset_base_url: str) -> WorkflowResponse:
    policy = get_policy_bundle().data
    meta = dict(document.get("meta") or {})
    steps_raw = (document.get("skills") or [{}])[0].get("steps") or []
    if not isinstance(steps_raw, list):
        steps_raw = []
    steps = [step_to_dto(skill_id, dict(s), i, policy, asset_base_url) for i, s in enumerate(steps_raw)]
    suggestions = collect_suggestions([dict(s) for s in steps_raw], policy)
    return WorkflowResponse(
        skill_id=skill_id,
        package_meta=meta,
        inputs=list(document.get("inputs") or []),
        steps=steps,
        suggestions=suggestions,
        asset_base_url=asset_base_url,
    )


def validate_skill_document(document: dict[str, Any]) -> dict[str, Any]:
    policy = get_policy_bundle().data
    steps_raw = (document.get("skills") or [{}])[0].get("steps") or []
    if not isinstance(steps_raw, list):
        steps_raw = []
    per_step: list[dict[str, Any]] = []
    for idx, s in enumerate(steps_raw):
        step = dict(s)
        ref = _build_reference_for_audit(step)
        per_step.append(
            {
                "step_index": idx,
                "audit_issues": audit_reference(ref),
                "revalidation": revalidate_step(step),
            }
        )
    return {"steps": per_step, "suggestions": [m.model_dump() for m in collect_suggestions([dict(s) for s in steps_raw], policy)]}


def reorder_steps(document: dict[str, Any], new_order: list[int]) -> dict[str, Any]:
    doc = dict(document)
    skills = list(doc.get("skills") or [])
    if not skills:
        raise ValueError("no_skills_block")
    block = dict(skills[0])
    steps = list(block.get("steps") or [])
    n = len(steps)
    if sorted(new_order) != list(range(n)):
        raise ValueError("invalid_reorder_permutation")
    new_steps = [dict(steps[i]) for i in new_order]
    block["steps"] = new_steps
    skills[0] = block
    doc["skills"] = skills
    meta = dict(doc.get("meta") or {})
    meta["version"] = int(meta.get("version", 1)) + 1
    doc["meta"] = meta
    return doc


def delete_step_at(document: dict[str, Any], step_index: int) -> dict[str, Any]:
    doc = dict(document)
    skills = list(doc.get("skills") or [])
    if not skills:
        raise ValueError("no_skills_block")
    block = dict(skills[0])
    steps = list(block.get("steps") or [])
    if step_index < 0 or step_index >= len(steps):
        raise ValueError("step_index_out_of_range")
    del steps[step_index]
    block["steps"] = steps
    skills[0] = block
    doc["skills"] = skills
    meta = dict(doc.get("meta") or {})
    meta["version"] = int(meta.get("version", 1)) + 1
    doc["meta"] = meta
    return doc


def merge_skill_inputs(document: dict[str, Any], inputs: list[dict[str, Any]], title: str | None) -> dict[str, Any]:
    doc = dict(document)
    doc["inputs"] = list(inputs)
    if title is not None:
        meta = dict(doc.get("meta") or {})
        meta["title"] = title
        doc["meta"] = meta
    meta = dict(doc.get("meta") or {})
    meta["version"] = int(meta.get("version", 1)) + 1
    doc["meta"] = meta
    return doc
