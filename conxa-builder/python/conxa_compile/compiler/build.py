"""Phase 3 — compile normalized events into a SkillPackage (no runtime execution)."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conxa_compile.compiler.action_policy import no_recovery_block, recovery_enabled_for_action
from conxa_compile.compiler.decision_layer import rank_merged_anchors
from conxa_compile.compiler.destructive_semantics import destructive_compiler_step
from conxa_compile.compiler.input_binding_v2 import derive_input_binding_v2
from conxa_compile.compiler.llm_selector_generator_v2 import generate_selector_with_objective_confidence
from conxa_compile.compiler.recovery_policy import (
    default_recovery_block,
    merge_recovery_strategies_for_wait_shape,
)
from conxa_compile.compiler.selector_filters import filter_selectors_dict, selector_passes_filters
from conxa_compile.compiler.selector_score import rank_selectors_scored, score_selector_row
from conxa_compile.compiler.v3 import (
    capture_state_snapshot,
    clean_steps,
    clean_anchors,
    compare_state,
    fix_step_order,
    generate_stable_selector,
    optimize_scroll,
    scroll_payload,
    validation_from_diff,
)
from conxa_core.config import settings
from conxa_compile.llm.anchor_vision_llm import VisionAnchorGenerationError, generate_anchors_for_step_or_raise
from conxa_compile.llm.intent_llm import generate_intent_with_llm
from conxa_core.models.events import RecordedEvent
from conxa_core.models.skill_spec import (
    Assertion,
    DecisionPolicy,
    ElementFingerprint,
    RecoveryBlock,
    SkillBlock,
    SkillMeta,
    SkillPackage,
    SkillPolicies,
    SkillStep,
    ValidationBlock,
)
from conxa_compile.policy.bundle import PolicyBundle, get_policy_bundle
from conxa_compile.policy.intent_ontology import intent_specificity_score, normalize_compiler_intent
from conxa_core.progress import append_current_job_event
from conxa_core.storage import snapshots


_RECOVERABLE_VISION_ANCHOR_REASONS = frozenset({
    "vision_anchors_disabled_in_policy",
    "llm_disabled",
    "llm_anchor_vision_disabled",
    "llm_endpoint_unset",
    "llm_endpoint_not_multimodal_capable",
    "vision_llm_request_failed",
    "vision_llm_empty_response",
    "vision_llm_invalid_primary_phrase",
})


def _compile_log(event: str, message: str, data: dict[str, Any] | None = None) -> None:
    append_current_job_event(event, message, data or {})


def _default_confidence_protocol(bundle: PolicyBundle) -> dict[str, Any]:
    return bundle.as_confidence_protocol_fragment()


def _infer_selector_kind(selector: str) -> str:
    """Infer selector kind from its string pattern for confidence scoring."""
    s = selector.strip()
    if s.startswith("label:has-text("):
        return "label"
    if s.startswith("[aria-label="):
        return "aria"
    if re.match(r"input\[name=", s):
        return "name"
    if s.lower().startswith("text="):
        return "text_based"
    if s.startswith("/") or s.startswith("(//"):
        return "xpath"
    return "css"


def _build_frame_context(ev: dict[str, Any]) -> dict[str, Any]:
    frame = ev.get("frame")
    if not isinstance(frame, dict):
        return {}
    chain = frame.get("chain")
    if not isinstance(chain, list):
        return {}
    out_chain: list[dict[str, Any]] = []
    for raw in chain:
        if not isinstance(raw, dict):
            continue
        selector = str(raw.get("selector") or "").strip()
        if not selector:
            continue
        fallbacks = [
            str(item).strip()
            for item in (raw.get("fallback_selectors") or [])
            if str(item or "").strip()
        ][:5]
        out_chain.append(
            {
                "selector": selector,
                "fallback_selectors": fallbacks,
                "url": str(raw.get("url") or "").strip(),
                "url_pattern": str(raw.get("url_pattern") or "").strip(),
            }
        )
    return {"chain": out_chain} if out_chain else {}


def _merge_compile_warnings(
    protocol: dict[str, Any],
    ev_with_intent: dict[str, Any],
    merged_anchors: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    vision_anchor_warning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(protocol)
    cw = dict(out.get("compile_warnings") or {})
    if vision_anchor_warning:
        cw["vision_anchor_fallback"] = vision_anchor_warning
    unc = policy.get("uncertainty") if isinstance(policy.get("uncertainty"), dict) else {}
    min_a = int(unc.get("destructive_min_anchors_warn", 2))
    if destructive_compiler_step(ev_with_intent, policy) and len(merged_anchors) < min_a:
        cw["destructive_low_anchor_count"] = True
    if cw:
        out["compile_warnings"] = cw
    return out


def _vision_anchor_failure_is_recoverable(exc: VisionAnchorGenerationError) -> bool:
    reason = str(exc.reason or "")
    return reason in _RECOVERABLE_VISION_ANCHOR_REASONS


def _fallback_anchors_from_event(ev_with_intent: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = clean_anchors(
        ev_with_intent.get("anchors") or [],
        ev_with_intent.get("context") or {},
        policy,
        target=dict(ev_with_intent.get("target") or {}),
        semantic=dict(ev_with_intent.get("semantic") or {}),
    )
    target = ev_with_intent.get("target") if isinstance(ev_with_intent.get("target"), dict) else {}
    semantic = ev_with_intent.get("semantic") if isinstance(ev_with_intent.get("semantic"), dict) else {}
    direct = ""
    for key in ("inner_text", "aria_label", "name", "placeholder"):
        direct = str(target.get(key) or "").strip()
        if direct:
            break
    if not direct:
        direct = str(semantic.get("normalized_text") or "").strip()
    direct = " ".join(direct.lower().split())[:96]
    if direct and direct not in {"button", "input", "link", "element"}:
        target_anchor = {"element": direct, "relation": "target"}
        anchors = [target_anchor, *[a for a in anchors if str(a.get("element") or "").lower() != direct]]
    return anchors


def _vision_anchor_warning(exc: VisionAnchorGenerationError, *, step_index: int) -> dict[str, Any]:
    warning: dict[str, Any] = {
        "reason": str(exc.reason or ""),
        "step_index": exc.step_index if exc.step_index is not None else step_index,
        "fallback": "deterministic_anchors",
    }
    if exc.hint:
        warning["hint"] = exc.hint
    return warning


def _persisted_visual_asset_path(
    ev: dict[str, Any],
    rel: str | None,
    *,
    session_id_fallback: str = "",
) -> str:
    """Turn recorder-relative paths (files under sessions/<id>/) into paths under data_dir."""
    if not rel or not isinstance(rel, str):
        return ""
    r = rel.strip().replace("\\", "/")
    if not r or ".." in r:
        return ""
    if r.startswith("sessions/"):
        return r
    session_id = str((ev.get("extras") or {}).get("session_id") or "").strip()
    if not session_id:
        session_id = str(session_id_fallback or "").strip()
    if session_id:
        return f"sessions/{session_id}/{r}"
    return r


def build_signal_reference(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_kind": ev.get("action", {}).get("action"),
        "target": ev.get("target") or {},
        "selectors": ev.get("selectors") or {},
        "semantic": ev.get("semantic") or {},
        "context": ev.get("context") or {},
        "anchors": ev.get("anchors") or [],
        "visual": {
            "bbox": (ev.get("visual") or {}).get("bbox") or {},
            "viewport": (ev.get("visual") or {}).get("viewport") or "",
            "scroll_position": (ev.get("visual") or {}).get("scroll_position") or "",
        },
        "state_after": (ev.get("state_change") or {}).get("after") or "",
        "page_url": (ev.get("page") or {}).get("url") or "",
        "page_title": (ev.get("page") or {}).get("title") or "",
    }


def _build_element_fingerprint(ev: dict[str, Any]) -> ElementFingerprint:
    """Extract stable element identity from recorded event signals."""
    target = ev.get("target") or {}
    semantic = ev.get("semantic") or {}
    selectors = ev.get("selectors") or {}
    anchors = ev.get("anchors") or []
    visual = ev.get("visual") or {}

    # Extract data-testid from CSS selector — highest-stability attribute
    data_testid = ""
    css = str(selectors.get("css") or "")
    m = re.search(r'data-testid=["\']?([^"\'>\s\]]+)', css)
    if m:
        data_testid = m.group(1)
    if not data_testid:
        aria = str(selectors.get("aria") or "")
        m2 = re.search(r'data-testid=["\']?([^"\'>\s\]]+)', aria)
        if m2:
            data_testid = m2.group(1)

    inner_text = str(target.get("inner_text") or semantic.get("normalized_text") or "").strip()[:120]

    # Only keep class tokens that look stable (no hash-like sequences, min length 3)
    raw_classes = " ".join(target.get("classes") or []) if isinstance(target.get("classes"), list) else str(target.get("classes") or "")
    class_tokens = [
        c for c in raw_classes.split()
        if len(c) >= 3 and not re.search(r"[0-9]{4,}|[a-f0-9]{6,}", c)
    ][:8]

    anchor_phrases = [
        str(a.get("element") or "").strip()
        for a in anchors
        if a.get("element") and str(a.get("element")).strip()
    ][:6]

    bbox = visual.get("bbox") or {}
    vw = max(int(bbox.get("vw", 0)) or 1280, 1)
    vh = max(int(bbox.get("vh", 0)) or 800, 1)

    return ElementFingerprint(
        role=str(semantic.get("role") or target.get("role") or ""),
        tag=str(target.get("tag") or ""),
        inner_text=inner_text,
        aria_label=str(target.get("aria_label") or ""),
        name=str(target.get("name") or ""),
        placeholder=str(target.get("placeholder") or ""),
        label_text=str(target.get("label_text") or ""),
        data_testid=data_testid,
        input_type=str(semantic.get("input_type") or ""),
        css_class_tokens=class_tokens,
        anchor_phrases=anchor_phrases,
        position_hint={
            "x_pct": round(int(bbox.get("x") or 0) / vw, 3),
            "y_pct": round(int(bbox.get("y") or 0) / vh, 3),
        },
    )


def _build_assertions(
    ev: dict[str, Any],
    validation: ValidationBlock,
) -> list[Assertion]:
    """Compile multiple verifiable post-action assertions from all available evidence."""
    assertions: list[Assertion] = []
    action = str((ev.get("action") or {}).get("action") or "").lower()

    # fill/type have no observable post-action outcome to assert at compile time
    if action in {"fill", "type", "focus", "scroll"}:
        return []

    # Primary wait_for assertion
    wf = validation.wait_for
    wf_type = str(wf.get("type") or "")
    wf_target = str(wf.get("target") or "")
    wf_timeout = int(wf.get("timeout") or 5000)

    if wf_type == "url_change":
        before_url = str((ev.get("page") or {}).get("url") or "")
        # URL must change but we don't know to what — assert it differs from current
        assertions.append(Assertion(
            type="url_changed",
            target=before_url,
            timeout_ms=wf_timeout,
            required=True,
        ))
    elif wf_type == "element_appear" and wf_target:
        assertions.append(Assertion(
            type="selector_present",
            target=wf_target,
            timeout_ms=wf_timeout,
            required=True,
        ))

    # success_conditions: required_elements and expected_text_tokens as advisory assertions
    sc = validation.success_conditions
    for el in (sc.get("required_elements") or [])[:3]:
        if el and isinstance(el, str):
            assertions.append(Assertion(
                type="selector_present",
                target=el,
                timeout_ms=wf_timeout,
                required=False,
            ))
    for tok in (sc.get("expected_text_tokens") or [])[:3]:
        if tok and isinstance(tok, str):
            assertions.append(Assertion(
                type="text_present",
                target=tok,
                timeout_ms=min(wf_timeout, 5000),
                required=False,
            ))

    return assertions


def _build_structural_fingerprint(steps: list[SkillStep]) -> dict[str, Any]:
    """Fingerprint the first 3 interactive steps for pre-execution drift detection."""
    landmarks: list[dict[str, Any]] = []
    for step in steps[:5]:
        action = step.action if isinstance(step.action, str) else (step.action or {}).get("action", "")
        if action in {"navigate", "scroll"}:
            continue
        fp = step.element_fingerprint
        primary = step.target.get("primary_selector", "")
        if primary or fp.data_testid or fp.aria_label or fp.inner_text:
            landmarks.append({
                "intent": step.intent,
                "primary_selector": primary,
                "data_testid": fp.data_testid,
                "aria_label": fp.aria_label,
                "inner_text": fp.inner_text[:60],
                "tag": fp.tag,
            })
        if len(landmarks) >= 3:
            break
    return {"landmarks": landmarks, "landmark_count": len(landmarks)}


def _build_target(ev: dict[str, Any], policy: dict[str, Any], session_id: str = "") -> dict[str, Any]:
    raw_selectors = ev.get("selectors") or {}
    selectors = filter_selectors_dict(raw_selectors)
    target = ev.get("target") or {}
    semantic = ev.get("semantic") or {}
    stable = generate_stable_selector(
        {"target": target, "selectors": selectors, "semantic": semantic}, policy
    )
    ranked_scored = rank_selectors_scored(
        {
            "aria": selectors.get("aria"),
            "name": target.get("name"),
            "text_based": selectors.get("text_based"),
            "css": selectors.get("css"),
            "xpath": selectors.get("xpath"),
        },
        policy,
    )
    ranked = [v for _, _, v in ranked_scored]
    top_score = ranked_scored[0][0] if ranked_scored else 0.0
    # Also score the synthesized stable primary — it may be higher (e.g. label selector)
    stable_primary = str(stable.get("primary_selector") or "").strip()
    if stable_primary:
        stable_kind = _infer_selector_kind(stable_primary)
        stable_score = max(0.0, score_selector_row(stable_kind, stable_primary, policy))
        top_score = max(top_score, stable_score)
    selector_confidence = round(top_score / 100.0, 3)

    ranked_extra = [
        selector
        for selector in ranked
        if selector not in {stable.get("primary_selector"), *(stable.get("fallback_selectors") or [])}
    ]
    primary = str(stable.get("primary_selector") or (ranked[0] if ranked else str(selectors.get("css") or "")))
    _is_bare_tag = bool(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", primary.strip()))
    if not selector_passes_filters(primary) or _is_bare_tag:
        primary = next((r for r in ranked if selector_passes_filters(str(r))), "")
        if not primary:
            # Last resort: use the best raw (unfiltered) selector — brittle > bare tag
            primary = next(
                (str(v).strip() for v in [
                    raw_selectors.get("css"), raw_selectors.get("aria"),
                    raw_selectors.get("text_based"), raw_selectors.get("xpath"),
                ] if v and str(v).strip()),
                str(target.get("tag") or "input"),
            )
            selector_confidence = 0.0

    confidence_breakdown: dict[str, float] | None = None
    selector_rationale = ""
    selector_source = "heuristic"

    # Heuristic survives ONLY at perfect confidence == 1.0 with a non-bare selector.
    # Anything below 1.0 MUST go through the LLM with full multi-frame context.
    _primary_is_bare_tag = bool(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", primary.strip()))
    use_heuristic = (
        selector_confidence >= 1.0
        and bool(primary.strip())
        and not _primary_is_bare_tag
    )
    if not use_heuristic:
        # Mandatory LLM call. Failure raises and aborts the compile — no silent fallback.
        llm_selector, llm_confidence, llm_breakdown, llm_rationale = _call_llm_native_selector(
            ev, target, semantic, session_id=session_id
        )
        if not llm_selector:
            _action_kind = str((ev.get("action") or {}).get("action") or "").lower()
            if _action_kind == "focus":
                # Focus is a soft action — the runtime recovery cascade is designed to
                # handle weak selectors. Record confidence 0.0; compile report flags it.
                selector_confidence = 0.0
                confidence_breakdown = {
                    "dom_uniqueness": 0.0,
                    "self_consistency": 0.0,
                    "visual_verification": 0.0,
                }
                selector_rationale = "focus: LLM selector unavailable; heuristic fallback"
                selector_source = "heuristic_fallback"
                # primary remains whatever the heuristic produced above
            else:
                raise RuntimeError(
                    f"LLM-native selector generation returned empty selector for action "
                    f"{ev.get('action', {}).get('action')!r}; cannot produce reliable compile."
                )
        else:
            primary = llm_selector
            selector_confidence = llm_confidence
            confidence_breakdown = llm_breakdown
            selector_rationale = llm_rationale
            selector_source = "llm_native"

    fallback_raw = list(stable.get("fallback_selectors") or []) + ranked_extra
    fallback = [s for s in fallback_raw if selector_passes_filters(str(s)) and str(s) != primary]
    input_type = semantic.get("input_type")
    target_type = "input" if input_type else str(target.get("tag") or "")
    if target_type == "button" or semantic.get("role") == "button":
        target_type = "button"
    elif target_type not in {"button", "input"}:
        target_type = "input" if target_type in {"textarea", "select"} else target_type
    result = {
        "primary_selector": primary,
        "fallback_selectors": fallback,
        "role": str(semantic.get("role") or target.get("role") or ""),
        "type": target_type or "input",
        "selector_confidence": selector_confidence,
        "selector_source": selector_source,
    }
    if confidence_breakdown:
        result["confidence_breakdown"] = confidence_breakdown
    if selector_rationale:
        result["selector_rationale"] = selector_rationale
    return result


def _call_llm_native_selector(
    ev: dict[str, Any],
    target: dict[str, Any],
    semantic: dict[str, Any],
    session_id: str = "",
) -> tuple[str, float, dict[str, float], str]:
    """LLM-native selector generation. Raises on failure — compile must fail loudly."""
    action = ev.get("action") or {}
    action_type = str(action.get("action") or "")
    ancestors = ev.get("ancestors") or []
    surrounding = str(ev.get("surrounding_text") or "")
    visual = ev.get("visual") or {}
    bbox = visual.get("bbox") or {}

    # Load full-page DOM + a11y when snapshot is available; fall back to ancestor snippet.
    dom_hash = str((ev.get("snapshot") or {}).get("dom_hash") or "")
    full_html: str | None = None
    a11y_node: dict[str, Any] | None = None
    if session_id and dom_hash:
        full_html = snapshots.read_dom_snapshot(session_id, dom_hash)
        a11y_tree = snapshots.read_a11y_snapshot(session_id, dom_hash)
        if a11y_tree:
            from conxa_compile.compiler.llm_selector_generator import _extract_a11y_node  # noqa: PLC0415
            a11y_node = _extract_a11y_node(a11y_tree, target)

    if full_html:
        from conxa_compile.compiler.llm_selector_generator import _dom_snippet_for_llm  # noqa: PLC0415
        dom_snippet = _dom_snippet_for_llm(full_html)
    else:
        # Build a DOM snippet from ancestors + target
        dom_parts = []
        for anc in ancestors[:3]:
            if isinstance(anc, dict):
                outer = str(anc.get("outer_html") or "")[:2000]
                if outer:
                    dom_parts.append(outer)
        dom_snippet = "\n".join(dom_parts) or json.dumps(target, ensure_ascii=False)

    return generate_selector_with_objective_confidence(
        dom_snippet=dom_snippet,
        element_bbox=bbox if isinstance(bbox, dict) else {},
        element_ancestors=ancestors if isinstance(ancestors, list) else [],
        surrounding_text=surrounding,
        action_type=action_type,
        target_dom=target,
        a11y_node=a11y_node,
        full_page_html=full_html,
        candidates_wanted=1,
        num_samples=3,  # Reduced from 5 to keep compile times reasonable
    )


def _build_signals(
    ev: dict[str, Any],
    *,
    resolved_intent: str,
    policy: dict[str, Any],
    anchors_override: list[dict[str, Any]] | None = None,
    asset_session_id: str = "",
) -> dict[str, Any]:
    visual = ev.get("visual") or {}
    target = dict(ev.get("target") or {})
    selectors = filter_selectors_dict(dict(ev.get("selectors") or {}))
    semantic = dict(ev.get("semantic") or {})
    semantic.pop("llm_confidence", None)
    semantic.pop("llm_source", None)
    semantic["final_intent"] = resolved_intent
    semantic["llm_intent"] = resolved_intent
    semantic.pop("intent_hint", None)
    is_scroll = str((ev.get("action") or {}).get("action") or "") == "scroll"
    sig_cfg = policy.get("signals") if isinstance(policy.get("signals"), dict) else {}
    text_max = int(sig_cfg.get("build_inner_text_max", 240))
    sib_max = int(sig_cfg.get("pipeline_siblings_max", 4))
    if is_scroll:
        target.pop("inner_text", None)
    else:
        target["inner_text"] = str(target.get("inner_text") or "")[:text_max]
    compact_context = dict(ev.get("context") or {})
    compact_context["siblings"] = list(compact_context.get("siblings") or [])[:sib_max]
    signals = {
        "dom": target,
        "selectors": {
            "aria": selectors.get("aria"),
            "text_based": selectors.get("text_based"),
            "css": selectors.get("css"),
            "xpath": selectors.get("xpath"),
        },
        "semantic": semantic,
        "context": {
            **compact_context,
            "page_url": (ev.get("page") or {}).get("url") or "",
            "page_title": (ev.get("page") or {}).get("title") or "",
            "timing": ev.get("timing") or {},
        },
        "anchors": (
            anchors_override
            if anchors_override is not None
            else clean_anchors(
                ev.get("anchors") or [],
                ev.get("context") or {},
                policy,
                target=dict(ev.get("target") or {}),
                semantic=dict(ev.get("semantic") or {}),
            )
        ),
        "visual": {
            "bbox": visual.get("bbox") or {},
            "viewport": visual.get("viewport") or "",
            "scroll_position": visual.get("scroll_position") or "",
            "full_screenshot": _persisted_visual_asset_path(
                ev, visual.get("full_screenshot"), session_id_fallback=asset_session_id
            ),
            "element_snapshot": _persisted_visual_asset_path(
                ev, visual.get("element_snapshot"), session_id_fallback=asset_session_id
            ),
        },
    }
    if is_scroll:
        return {"visual": {"scroll_position": visual.get("scroll_position") or ""}}
    return signals


def _derive_input_binding(ev: dict[str, Any], policy: dict[str, Any]) -> tuple[Any, str | None]:
    """Delegate to derive_input_binding_v2 with priority signals (label_text → placeholder → aria_label → value pattern → input_type)."""
    return derive_input_binding_v2(ev, policy)


def _build_validation(ev: dict[str, Any], state_diff: dict[str, Any], policy: dict[str, Any]) -> ValidationBlock:
    action = str((ev.get("action") or {}).get("action") or "")
    intent = str((ev.get("semantic") or {}).get("llm_intent") or "")
    timeout = int((ev.get("timing") or {}).get("timeout") or 5000)
    page_url = str((ev.get("page") or {}).get("url") or "")
    dynamic = validation_from_diff(
        action, intent, state_diff, timeout, page_url=page_url, source_step=ev, policy=policy
    )
    return ValidationBlock(
        wait_for=dynamic.get("wait_for") or {},
        success_conditions=dynamic.get("success_conditions") or {},
    )

def _build_step(
    ev: dict[str, Any],
    bundle: PolicyBundle,
    *,
    session_root: Path,
    step_index: int,
) -> SkillStep:
    policy = bundle.data
    action_payload = optimize_scroll(ev)
    started = time.perf_counter()
    _compile_log(
        "compile_step",
        f"Compiling step {step_index + 1}.",
        {"phase": "step_start", "step_index": step_index, "action": action_payload},
    )
    if action_payload == "scroll":
        scroll_action = scroll_payload(ev, policy)
        visual = ev.get("visual") or {}
        scroll_rel = visual.get("full_screenshot") or visual.get("element_snapshot")
        scroll_screenshot = _persisted_visual_asset_path(
            ev,
            scroll_rel if isinstance(scroll_rel, str) else None,
            session_id_fallback=session_root.name,
        )
        scroll_position = visual.get("scroll_position") or ""
        visual_signals: dict[str, Any] = {"scroll_position": scroll_position}
        if scroll_screenshot:
            visual_signals["scroll_screenshot"] = scroll_screenshot
        step = SkillStep(
            action=scroll_action,
            intent="scroll_viewport",
            frame=_build_frame_context(ev),
            signals={
                "visual": visual_signals,
            },
            recovery=RecoveryBlock(**no_recovery_block("scroll_viewport")),
        )
        _compile_log(
            "compile_step",
            f"Compiled step {step_index + 1}.",
            {
                "phase": "step_done",
                "step_index": step_index,
                "action": action_payload,
                "intent": step.intent,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return step
    llm_raw = generate_intent_with_llm(ev)
    intent = normalize_compiler_intent(ev, llm_raw, policy)
    state_before = capture_state_snapshot(ev, before=True)
    state_after = capture_state_snapshot(ev, before=False)
    state_diff = compare_state(state_before, state_after)
    ev_with_intent = dict(ev)
    semantic = dict(ev_with_intent.get("semantic") or {})
    pipeline_candidate = str(semantic.get("llm_intent") or "").strip()
    if pipeline_candidate and pipeline_candidate != intent:
        semantic["intent_candidate"] = pipeline_candidate
    semantic["final_intent"] = intent
    semantic["llm_intent"] = intent
    semantic["intent_specificity_score"] = intent_specificity_score(intent, policy)
    ev_with_intent["semantic"] = semantic
    vision_anchor_warning: dict[str, Any] | None = None
    try:
        _compile_log(
            "compile_step",
            f"Generating vision anchors for step {step_index + 1}.",
            {"phase": "vision_anchor_start", "step_index": step_index, "intent": intent},
        )
        merged_anchors = generate_anchors_for_step_or_raise(
            ev_with_intent,
            session_root=session_root,
            final_intent=intent,
            policy=policy,
            step_index=step_index,
        )
        _compile_log(
            "compile_step",
            f"Vision anchors generated for step {step_index + 1}.",
            {"phase": "vision_anchor_done", "step_index": step_index, "anchor_count": len(merged_anchors)},
        )
    except VisionAnchorGenerationError as exc:
        if not _vision_anchor_failure_is_recoverable(exc):
            raise
        merged_anchors = _fallback_anchors_from_event(ev_with_intent, policy)
        vision_anchor_warning = _vision_anchor_warning(exc, step_index=step_index)
        _compile_log(
            "compile_step",
            f"Vision anchors fell back for step {step_index + 1}.",
            {
                "phase": "vision_anchor_fallback",
                "step_index": step_index,
                "reason": exc.reason,
                "anchor_count": len(merged_anchors),
            },
        )
    merged_anchors = rank_merged_anchors(merged_anchors, ev_with_intent, intent, policy)
    validation = _build_validation(ev_with_intent, state_diff, policy)
    if recovery_enabled_for_action(action_payload):
        recovery_dict = default_recovery_block(intent, merged_anchors, policy)
        recovery_dict = merge_recovery_strategies_for_wait_shape(
            recovery_dict,
            dict(validation.wait_for) if validation.wait_for else {},
            policy,
        )
    else:
        recovery_dict = no_recovery_block(intent)
    recovery = RecoveryBlock(**recovery_dict)
    target = _build_target(ev, policy, session_id=session_root.name)
    signals = _build_signals(
        ev,
        resolved_intent=intent,
        policy=policy,
        anchors_override=merged_anchors,
        asset_session_id=session_root.name,
    )
    value, input_binding = _derive_input_binding(ev, policy)
    confidence_protocol = _merge_compile_warnings(
        _default_confidence_protocol(bundle),
        ev_with_intent,
        merged_anchors,
        policy,
        vision_anchor_warning=vision_anchor_warning,
    )
    sel_conf = target.get("selector_confidence", 1.0)
    if sel_conf <= 0.5:
        cw = dict(confidence_protocol.get("compile_warnings") or {})
        cw["selector_confidence"] = sel_conf
        confidence_protocol = {**confidence_protocol, "compile_warnings": cw}
    fingerprint = _build_element_fingerprint(ev_with_intent)
    assertions = _build_assertions(ev_with_intent, validation)
    if assertions:
        validation = ValidationBlock(
            wait_for=validation.wait_for,
            success_conditions=validation.success_conditions,
            assertions=assertions,
        )
    snapshot = ev.get("snapshot") or {}
    step = SkillStep(
        action=action_payload,
        intent=intent,
        frame=_build_frame_context(ev),
        target=target,
        element_fingerprint=fingerprint,
        signals=signals,
        state={"before": state_before, "after": state_after},
        value=value,
        input_binding=input_binding,
        validation=validation,
        recovery=recovery,
        confidence_protocol=confidence_protocol,
        decision_policy=DecisionPolicy(),
        snapshot_ref=str(snapshot.get("ref") or ""),
        snapshot_dom_hash=str(snapshot.get("dom_hash") or ""),
    )
    _compile_log(
        "compile_step",
        f"Compiled step {step_index + 1}.",
        {
            "phase": "step_done",
            "step_index": step_index,
            "action": action_payload,
            "intent": step.intent,
            "selector": (step.target or {}).get("primary_selector"),
            "selector_confidence": (step.target or {}).get("selector_confidence"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return step


def _build_compile_report(steps: list[SkillStep]) -> dict[str, Any]:
    """Aggregate per-step selector confidence + LLM router stats into a single report.

    Status:
    - "ok" if all confidence >= 0.90 and no warnings
    - "review_needed" if any confidence 0.75–0.89
    - "failed" if any confidence < 0.75
    """
    step_reports: list[dict[str, Any]] = []
    min_confidence = 1.0
    has_warnings = False

    for i, step in enumerate(steps):
        target = step.target or {}
        selector = str(target.get("primary_selector") or "")
        confidence = float(target.get("selector_confidence") or 0.0)
        breakdown = target.get("confidence_breakdown") or {}
        source = str(target.get("selector_source") or "heuristic")
        rationale = str(target.get("selector_rationale") or "")

        warnings: list[dict[str, str]] = []
        if confidence < 0.50:
            warnings.append({
                "code": "low_selector_confidence",
                "message": f"Selector confidence {confidence:.2f} is below 0.50 — runtime may need to fall back to vision recovery",
            })
            has_warnings = True

        if not selector:
            warnings.append({
                "code": "empty_selector",
                "message": "No selector could be generated — step may fail at runtime",
            })
            has_warnings = True

        if confidence < min_confidence:
            min_confidence = confidence

        step_reports.append({
            "index": i,
            "intent": step.intent,
            "selector": selector,
            "confidence": round(confidence, 3),
            "confidence_breakdown": breakdown,
            "source": source,
            "reasoning": rationale,
            "input_binding": step.input_binding,
            "warnings": warnings,
        })

    if min_confidence >= 0.90 and not has_warnings:
        status = "ok"
    elif min_confidence >= 0.75:
        status = "review_needed"
    else:
        status = "failed"

    from conxa_core.llm import get_router
    router = get_router()
    if hasattr(router, "pool"):
        if not router.pool:
            raise RuntimeError(
                "LLM router has no providers configured. Compile cannot produce a "
                "trustworthy report without LLM verification. Set at least one "
                "*_API_KEYS + *_ENABLED=true in .env."
            )
        router_stats = router.stats()
    else:
        # Proxy client (Build Studio) — no local provider pool; stats not applicable.
        router_stats = {"provider": "cloud_proxy"}

    return {
        "status": status,
        "steps_total": len(steps),
        "steps_with_warnings": sum(1 for sr in step_reports if sr["warnings"]),
        "min_confidence": round(min_confidence, 3),
        "steps": step_reports,
        "llm_router_stats": router_stats,
    }


def _deduplicate_input_bindings(steps: list[SkillStep]) -> None:
    """Ensure no two type/keyboard_shortcut steps share the same input_binding name.

    If two steps both resolve to {{name}}, the second becomes {{name_2}}, third {{name_3}}, etc.
    Keyboard shortcut steps (with input_binding=None) are left alone.
    """
    seen_counts: dict[str, int] = {}
    for step in steps:
        binding = step.input_binding
        if not binding:
            continue
        if binding not in seen_counts:
            seen_counts[binding] = 1
            continue
        seen_counts[binding] += 1
        new_binding = f"{binding}_{seen_counts[binding]}"
        step.input_binding = new_binding
        if isinstance(step.value, str) and step.value == f"{{{{{binding}}}}}":
            step.value = f"{{{{{new_binding}}}}}"


def compile_skill_package(
    events: list[dict[str, Any]],
    *,
    skill_id: str,
    source_session_id: str | None,
    title: str,
    version: int,
    policy_bundle: PolicyBundle | None = None,
) -> SkillPackage:
    """Build a package from already pipeline-normalized event dicts."""
    bundle = policy_bundle or get_policy_bundle()
    pol = bundle.data
    for e in events:
        RecordedEvent.model_validate(e)
    sid = str(source_session_id or "").strip()
    if not sid:
        raise VisionAnchorGenerationError("source_session_id_required")
    session_root = (settings.data_dir / "sessions" / sid).resolve()
    _compile_log(
        "compile_phase",
        "Preparing compiler inputs.",
        {"phase": "compiler_prepare", "event_count": len(events), "session_id": sid},
    )
    cleaned_events = fix_step_order(clean_steps(events, pol), pol)
    _compile_log(
        "compile_phase",
        "Compiler inputs prepared.",
        {"phase": "compiler_prepare_done", "cleaned_event_count": len(cleaned_events)},
    )
    steps = [_build_step(e, bundle, session_root=session_root, step_index=i) for i, e in enumerate(cleaned_events)]

    # Phase 3: LLM-driven selector compilation. Only runs when snapshots exist and
    # LLM is enabled. Failures degrade gracefully — runtime falls back to existing
    # heuristic selectors plus a11y tier 2.
    intent_graph = _llm_compile_selectors(steps, cleaned_events, session_id=sid)

    _deduplicate_input_bindings(steps)

    _compile_log(
        "compile_phase",
        "Building compile confidence report.",
        {"phase": "compile_report_start", "step_count": len(steps)},
    )
    compile_report = _build_compile_report(steps)
    _compile_log(
        "compile_phase",
        "Compile confidence report finished.",
        {
            "phase": "compile_report_done",
            "status": compile_report.get("status"),
            "min_confidence": compile_report.get("min_confidence"),
            "steps_with_warnings": compile_report.get("steps_with_warnings"),
        },
    )

    now = datetime.now(timezone.utc).isoformat()
    structural_fp = _build_structural_fingerprint(steps)
    meta = SkillMeta(
        id=skill_id,
        version=version,
        title=title or skill_id,
        created_at=now,
        source_session_id=source_session_id,
        compiler_policy_version=bundle.version,
        compiler_policy_hash=bundle.content_hash,
        structural_fingerprint=structural_fp,
    )
    return SkillPackage(
        meta=meta,
        inputs=[],
        skills=[SkillBlock(name="recorded", steps=steps)],
        policies=SkillPolicies(),
        llm={
            "max_calls_per_step": settings.llm_max_calls_per_step,
            "timeout_ms": settings.llm_pack_timeout_ms,
        },
        intent_graph=intent_graph,
        compile_report=compile_report,
    )


def _llm_compile_selectors(
    steps: list[SkillStep],
    cleaned_events: list[dict[str, Any]],
    *,
    session_id: str,
) -> "WorkflowIntentGraph":
    """Populate steps[i].compiled_selectors + semantic_description from LLM.

    Returns the workflow intent graph. Raises if the LLM router has no
    providers configured.
    """
    from conxa_core.models.skill_spec import WorkflowIntentGraph  # noqa: PLC0415 — local import to avoid circular ref

    try:
        from conxa_compile.compiler.llm_selector_generator import (  # noqa: PLC0415
            build_workflow_intent_graph,
            compile_workflow_selectors,
            task_from_recorded_event,
        )
    except ImportError:
        return WorkflowIntentGraph()

    # Build compile tasks for steps that have snapshot data.
    tasks = []
    for i, ev in enumerate(cleaned_events):
        snap = ev.get("snapshot") or {}
        if not snap.get("dom_hash"):
            continue
        tasks.append(task_from_recorded_event(ev, step_index=i))

    _compile_log(
        "compile_phase",
        "Preparing LLM selector compilation.",
        {"phase": "llm_selector_prepare", "task_count": len(tasks), "step_count": len(cleaned_events)},
    )

    if tasks:
        _compile_log(
            "compile_phase",
            "Compiling LLM selector candidates.",
            {"phase": "llm_selector_start", "task_count": len(tasks)},
        )
        candidates_by_step = compile_workflow_selectors(tasks, session_id=session_id)
        _compile_log(
            "compile_phase",
            "LLM selector compilation finished.",
            {
                "phase": "llm_selector_done",
                "task_count": len(tasks),
                "steps_with_candidates": sum(1 for cands in candidates_by_step.values() if cands),
            },
        )
        for i, step in enumerate(steps):
            cands = candidates_by_step.get(i) or []
            if not cands:
                continue
            step.compiled_selectors = [c.selector for c in cands[:3]]
            # Use the top candidate's intent string as semantic description.
            for c in cands:
                if c.intent:
                    step.semantic_description = c.intent
                    break

    # Workflow-level intent graph (one LLM call).
    steps_summary = [
        {
            "index": i,
            "action": ev.get("action", {}).get("action"),
            "target_text": (ev.get("target") or {}).get("inner_text") or "",
            "url": (ev.get("page") or {}).get("url") or "",
            "semantic_intent": (ev.get("semantic") or {}).get("intent_hint") or "",
        }
        for i, ev in enumerate(cleaned_events)
    ]
    page_urls = sorted({(ev.get("page") or {}).get("url") or "" for ev in cleaned_events} - {""})
    try:
        _compile_log(
            "compile_phase",
            "Building workflow intent graph.",
            {"phase": "workflow_intent_start", "step_count": len(steps_summary), "page_url_count": len(page_urls)},
        )
        graph = build_workflow_intent_graph(steps_summary, page_urls)
        _compile_log(
            "compile_phase",
            "Workflow intent graph finished.",
            {
                "phase": "workflow_intent_done",
                "goal": graph.goal,
                "intent_step_count": len(graph.steps),
            },
        )
        return graph
    except Exception:  # noqa: BLE001 — LLM failure is non-fatal at compile time
        _compile_log(
            "compile_phase",
            "Workflow intent graph generation failed; continuing with an empty graph.",
            {"phase": "workflow_intent_failed"},
        )
        return WorkflowIntentGraph()
