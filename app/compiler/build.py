"""Phase 3 — compile normalized events into a SkillPackage (no runtime execution)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.compiler.action_policy import no_recovery_block, recovery_enabled_for_action
from app.compiler.decision_layer import rank_merged_anchors
from app.compiler.destructive_semantics import destructive_compiler_step
from app.compiler.recovery_policy import (
    default_recovery_block,
    merge_recovery_strategies_for_wait_shape,
)
from app.compiler.selector_filters import filter_selectors_dict, selector_passes_filters
from app.compiler.selector_score import rank_selectors_scored, score_selector_row
from app.compiler.v3 import (
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
from app.config import settings
from app.llm.anchor_vision_llm import VisionAnchorGenerationError, generate_anchors_for_step_or_raise
from app.llm.intent_llm import generate_intent_with_llm
from app.models.events import RecordedEvent
from app.models.skill_spec import (
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
from app.policy.bundle import PolicyBundle, get_policy_bundle
from app.policy.intent_ontology import intent_specificity_score, normalize_compiler_intent


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


def _build_target(ev: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
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

    fallback_raw = list(stable.get("fallback_selectors") or []) + ranked_extra
    fallback = [s for s in fallback_raw if selector_passes_filters(str(s)) and str(s) != primary]
    input_type = semantic.get("input_type")
    target_type = "input" if input_type else str(target.get("tag") or "")
    if target_type == "button" or semantic.get("role") == "button":
        target_type = "button"
    elif target_type not in {"button", "input"}:
        target_type = "input" if target_type in {"textarea", "select"} else target_type
    return {
        "primary_selector": primary,
        "fallback_selectors": fallback,
        "role": str(semantic.get("role") or target.get("role") or ""),
        "type": target_type or "input",
        "selector_confidence": selector_confidence,
    }


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
    action = ev.get("action") or {}
    raw_value = action.get("value")
    semantic = ev.get("semantic") or {}
    if raw_value is None:
        return None, None
    input_type = str(semantic.get("input_type") or "").lower()
    sig = policy.get("signals") if isinstance(policy.get("signals"), dict) else {}
    cred = sig.get("credential_bindings") if isinstance(sig.get("credential_bindings"), dict) else {}
    for ck, template in cred.items():
        if str(ck).lower() == input_type:
            return str(template), input_type
    if input_type:
        binding = input_type.replace("-", "_")
        return f"{{{{{binding}}}}}", binding
    return raw_value, None


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
        return SkillStep(
            action=scroll_action,
            intent="scroll_viewport",
            frame=_build_frame_context(ev),
            signals={
                "visual": visual_signals,
            },
            recovery=RecoveryBlock(**no_recovery_block("scroll_viewport")),
        )
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
        merged_anchors = generate_anchors_for_step_or_raise(
            ev_with_intent,
            session_root=session_root,
            final_intent=intent,
            policy=policy,
            step_index=step_index,
        )
    except VisionAnchorGenerationError as exc:
        if not _vision_anchor_failure_is_recoverable(exc):
            raise
        merged_anchors = _fallback_anchors_from_event(ev_with_intent, policy)
        vision_anchor_warning = _vision_anchor_warning(exc, step_index=step_index)
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
    target = _build_target(ev, policy)
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
    return SkillStep(
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
    )


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
    cleaned_events = fix_step_order(clean_steps(events, pol), pol)
    steps = [_build_step(e, bundle, session_root=session_root, step_index=i) for i, e in enumerate(cleaned_events)]
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
            "enabled": settings.llm_enabled,
            "semantic_enrichment": settings.llm_semantic_enrichment,
            "vision_reasoning": settings.llm_vision_reasoning,
            "anchor_vision": settings.llm_anchor_vision,
            "recovery_assist": settings.llm_recovery_assist,
            "max_calls_per_step": settings.llm_max_calls_per_step,
            "timeout_ms": settings.llm_pack_timeout_ms,
        },
    )
