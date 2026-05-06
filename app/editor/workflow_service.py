"""Map persisted skill JSON → editor DTOs, suggestions, and structural edits."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from app.anchors.schema import normalize_anchor_list
from app.compiler.action_policy import no_recovery_block
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


def ensure_initial_navigation_step(document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Backfill a persisted first navigate step from the first recorded page URL."""
    doc = dict(document)
    skills = list(doc.get("skills") or [])
    if not skills:
        return doc, False
    block = dict(skills[0])
    steps = list(block.get("steps") or [])
    if not steps:
        return doc, False
    first = dict(steps[0])
    first_action = action_name(first).strip().lower()
    if first_action == "navigate":
        return doc, False
    url = ""
    title = ""
    for raw in steps:
        step = dict(raw) if isinstance(raw, dict) else {}
        signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
        context = signals.get("context") if isinstance(signals.get("context"), dict) else {}
        candidate = str(context.get("page_url") or "").strip()
        if candidate.startswith(("http://", "https://")):
            url = candidate
            title = str(context.get("page_title") or "")
            break
    if not url:
        return doc, False
    nav_step = {
        "action": {"action": "navigate", "url": url},
        "intent": "navigate_to_start_url",
        "url": url,
        "target": {},
        "signals": {
            "context": {"page_url": url, "page_title": title},
            "semantic": {
                "final_intent": "navigate_to_start_url",
                "llm_intent": "navigate_to_start_url",
            },
            "selectors": {},
            "anchors": [],
            "visual": {},
        },
        "state": {},
        "value": None,
        "input_binding": None,
        "validation": {
            "wait_for": {"type": "url_change", "target": url, "timeout": 15000},
            "success_conditions": {"url": url},
        },
        "recovery": no_recovery_block("navigate_to_start_url"),
        "confidence_protocol": {},
        "decision_policy": {},
    }
    block["steps"] = [nav_step, *steps]
    skills[0] = block
    doc["skills"] = skills
    meta = dict(doc.get("meta") or {})
    meta["version"] = int(meta.get("version", 1)) + 1
    doc["meta"] = meta
    return doc, True


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


def _scroll_mode(step: dict[str, Any]) -> str | None:
    action = step.get("action")
    if not isinstance(action, dict) or str(action.get("action") or "").strip().lower() != "scroll":
        return None
    selector = str(action.get("selector") or "").strip()
    if selector:
        return "scroll_to_locate"
    return "scroll_only"


def _scroll_selector(step: dict[str, Any]) -> str | None:
    action = step.get("action")
    if not isinstance(action, dict):
        return None
    selector = str(action.get("selector") or "").strip()
    return selector or None


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
        "anchors": normalize_anchor_list(signals.get("anchors") or []),
        "visual": signals.get("visual") or {},
        "state_after": context.get("state_after") or "",
        "page_url": context.get("page_url") or "",
        "page_title": context.get("page_title") or "",
    }


def _editable_fields(step: dict[str, Any], policy: dict[str, Any]) -> dict[str, bool]:
    act = action_name(step).lower()
    is_scroll = act == "scroll"
    is_navigate = act == "navigate"
    dest = destructive_compiler_step(skill_step_for_destructive_check(step), policy)
    return {
        "intent": True,
        "action": False,
        "url": is_navigate,
        "selectors": not is_scroll and not is_navigate,
        "anchors": not is_scroll and not is_navigate,
        "validation": not is_scroll,
        "recovery_strategies": False,
        "value": act in {"fill", "type"},
        "parameterization": not is_scroll,
        "destructive_requires_validation": dest,
    }


def _step_url(step: dict[str, Any]) -> str:
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    if isinstance(action, dict):
        url = str(action.get("url") or "").strip()
        if url:
            return url
    url = str(step.get("url") or "").strip()
    if url:
        return url
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    context = signals.get("context") if isinstance(signals.get("context"), dict) else {}
    return str(context.get("page_url") or "").strip()


def _persisted_visual_path(rel: str, source_session_id: str) -> str:
    r = rel.strip().replace("\\", "/")
    if not r or ".." in r:
        return ""
    if r.startswith("sessions/"):
        return r
    sid = source_session_id.strip()
    if sid and r.startswith("images/"):
        return f"sessions/{sid}/{r}"
    return r


def _screenshot_dto(
    skill_id: str,
    visual: dict[str, Any],
    asset_base_url: str,
    source_session_id: str = "",
) -> StepScreenshotDTO:
    def u(rel: str) -> str | None:
        if not rel or not isinstance(rel, str):
            return None
        persisted = _persisted_visual_path(rel, source_session_id)
        if not persisted:
            return None
        q = urllib.parse.urlencode({"path": persisted})
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


def step_to_dto(
    skill_id: str,
    step: dict[str, Any],
    step_index: int,
    policy: dict[str, Any],
    asset_base_url: str,
    source_session_id: str = "",
) -> StepEditorDTO:
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    semantic = signals.get("semantic") if isinstance(signals.get("semantic"), dict) else {}
    recovery = step.get("recovery") if isinstance(step.get("recovery"), dict) else {}
    validation = step.get("validation") if isinstance(step.get("validation"), dict) else {}
    visual = signals.get("visual") if isinstance(signals.get("visual"), dict) else {}
    is_url_check = str(action_name(step)).lower() == "check" and str(step.get("check_kind") or "url").lower() in {
        "url",
        "url_exact",
        "url_must_be",
    }

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
        url=_step_url(step),
        target=dict(step.get("target") or {}),
        selectors=dict(signals.get("selectors") or {}),
        anchors_signals=[] if is_url_check else normalize_anchor_list(signals.get("anchors") or []),
        anchors_recovery=[] if is_url_check else normalize_anchor_list(recovery.get("anchors") or []),
        validation={
            "wait_for": dict(validation.get("wait_for") or {}),
            "success_conditions": dict(validation.get("success_conditions") or {}),
        },
        recovery=dict(recovery),
        value=step.get("value"),
        scroll_mode=_scroll_mode(step),
        scroll_selector=_scroll_selector(step),
        scroll_amount=_parse_scroll_amount(step),
        input_binding=step.get("input_binding"),
        screenshot=_screenshot_dto(skill_id, visual, asset_base_url, source_session_id),
        editable_fields=_editable_fields(step, policy),
        flags=flags,
        parameter_bindings=_parameter_bindings_from_step(step),
        check_kind=str(step.get("check_kind") or "") or None,
        check_pattern=str(step.get("check_pattern") or "") or None,
        check_threshold=step.get("check_threshold") if isinstance(step.get("check_threshold"), (int, float)) else None,
        check_selector=str(step.get("check_selector") or "") or None,
        check_text=str(step.get("check_text") or "") or None,
    )


def build_workflow_response(skill_id: str, document: dict[str, Any], *, asset_base_url: str) -> WorkflowResponse:
    policy = get_policy_bundle().data
    meta = dict(document.get("meta") or {})
    source_session_id = str(meta.get("source_session_id") or "").strip()
    steps_raw = (document.get("skills") or [{}])[0].get("steps") or []
    if not isinstance(steps_raw, list):
        steps_raw = []
    steps = [
        step_to_dto(skill_id, dict(s), i, policy, asset_base_url, source_session_id)
        for i, s in enumerate(steps_raw)
    ]
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


def _last_known_page_url(steps: list[Any], insert_after: int) -> str:
    for raw in reversed(steps[: insert_after + 1]):
        step = dict(raw) if isinstance(raw, dict) else {}
        action = step.get("action") if isinstance(step.get("action"), dict) else {}
        url = str(action.get("url") or step.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            return url
        signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
        context = signals.get("context") if isinstance(signals.get("context"), dict) else {}
        url = str(context.get("page_url") or "").strip()
        if url.startswith(("http://", "https://")):
            return url
    return ""


def _new_manual_step(action_kind: str, page_url: str) -> dict[str, Any]:
    kind = action_kind.strip().lower().replace("-", "_")
    if kind == "type":
        kind = "fill"
    allowed = {"navigate", "click", "fill", "scroll", "check"}
    if kind not in allowed:
        raise ValueError("unsupported_action_kind")

    intent = {
        "navigate": "navigate_to_page",
        "click": "click_target",
        "fill": "fill_field",
        "scroll": "scroll_page",
        "check": "check_page_state",
    }[kind]
    url = page_url if page_url.startswith(("http://", "https://")) else ""
    action: dict[str, Any] = {"action": kind}
    if kind == "navigate":
        action["url"] = url or "https://example.com"
        url = action["url"]
    elif kind == "scroll":
        action["delta"] = 600

    step: dict[str, Any] = {
        "action": action,
        "intent": intent,
        "url": url,
        "target": {
            "primary_selector": "",
            "fallback_selectors": [],
        },
        "signals": {
            "dom": {},
            "selectors": {"css": "", "aria": "", "text_based": "", "xpath": ""},
            "semantic": {"final_intent": intent, "llm_intent": intent},
            "context": {"page_url": url, "page_title": ""},
            "anchors": [],
            "visual": {},
        },
        "state": {},
        "value": "" if kind == "fill" else None,
        "input_binding": None,
        "validation": {
            "wait_for": {"type": "none", "timeout": 5000},
            "success_conditions": {},
        },
        "recovery": no_recovery_block(intent),
        "confidence_protocol": {},
        "decision_policy": {},
    }
    if kind == "navigate":
        step["validation"] = {
            "wait_for": {"type": "url_change", "target": url, "timeout": 15000},
            "success_conditions": {"url": url},
        }
    if kind == "check":
        step["check_kind"] = "url"
        step["check_pattern"] = url
    return step


def insert_step_after(document: dict[str, Any], action_kind: str, insert_after: int | None = None) -> dict[str, Any]:
    doc = dict(document)
    skills = list(doc.get("skills") or [])
    if not skills:
        raise ValueError("no_skills_block")
    block = dict(skills[0])
    steps = list(block.get("steps") or [])
    if insert_after is None:
        insert_at = len(steps)
        anchor_index = len(steps) - 1
    else:
        if insert_after < -1 or insert_after >= len(steps):
            raise ValueError("step_index_out_of_range")
        insert_at = insert_after + 1
        anchor_index = insert_after
    steps.insert(insert_at, _new_manual_step(action_kind, _last_known_page_url(steps, anchor_index)))
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


def _deep_replace_string_values(value: Any, find: str, replace: str) -> Any:
    """Return a structure copy with every string leaf updated via str.replace(find, replace)."""
    if isinstance(value, str):
        return value.replace(find, replace)
    if isinstance(value, list):
        return [_deep_replace_string_values(v, find, replace) for v in value]
    if isinstance(value, dict):
        return {k: _deep_replace_string_values(v, find, replace) for k, v in value.items()}
    return value


def replace_string_literals_in_skill_document(document: dict[str, Any], find: str, replace: str) -> dict[str, Any]:
    """Replace a literal substring everywhere in the stored skill JSON (steps, inputs, meta, etc.)."""
    if not isinstance(find, str) or not find:
        raise ValueError("find_must_be_nonempty")
    if not isinstance(replace, str):
        raise ValueError("replace_with_must_be_string")
    new_doc = _deep_replace_string_values(dict(document), find, replace)
    meta = dict(new_doc.get("meta") or {})
    meta["version"] = int(meta.get("version", 1)) + 1
    new_doc["meta"] = meta
    return new_doc
