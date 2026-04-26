"""Phase 3 — compile normalized events into a SkillPackage (no runtime execution)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.compiler.decision_layer import rank_merged_anchors
from app.compiler.destructive_semantics import destructive_compiler_step
from app.compiler.recovery_policy import (
    default_recovery_block,
    merge_recovery_strategies_for_wait_shape,
    suggest_anchors_from_context,
)
from app.compiler.selector_filters import filter_selectors_dict, selector_passes_filters
from app.compiler.v3 import (
    capture_state_snapshot,
    clean_steps,
    clean_anchors,
    compare_state,
    fix_step_order,
    generate_stable_selector,
    optimize_scroll,
    rank_selectors,
    validation_from_diff,
)
from app.config import settings
from app.llm.intent_llm import generate_intent_with_llm
from app.models.events import RecordedEvent
from app.models.skill_spec import (
    DecisionPolicy,
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


def _default_confidence_protocol(bundle: PolicyBundle) -> dict[str, Any]:
    return bundle.as_confidence_protocol_fragment()


def _merge_compile_warnings(
    protocol: dict[str, Any],
    ev_with_intent: dict[str, Any],
    merged_anchors: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    out = dict(protocol)
    if not destructive_compiler_step(ev_with_intent, policy):
        return out
    unc = policy.get("uncertainty") if isinstance(policy.get("uncertainty"), dict) else {}
    min_a = int(unc.get("destructive_min_anchors_warn", 2))
    if len(merged_anchors) < min_a:
        cw = dict(out.get("compile_warnings") or {})
        cw["destructive_low_anchor_count"] = True
        out["compile_warnings"] = cw
    return out


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


def _build_target(ev: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    selectors = filter_selectors_dict(ev.get("selectors") or {})
    target = ev.get("target") or {}
    semantic = ev.get("semantic") or {}
    stable = generate_stable_selector(
        {"target": target, "selectors": selectors, "semantic": semantic}, policy
    )
    ranked = rank_selectors(
        {
            "aria": selectors.get("aria"),
            "name": target.get("name"),
            "text_based": selectors.get("text_based"),
            "css": selectors.get("css"),
            "xpath": selectors.get("xpath"),
        },
        policy,
    )
    ranked_extra = [
        selector
        for selector in ranked
        if selector not in {stable.get("primary_selector"), *(stable.get("fallback_selectors") or [])}
    ]
    primary = str(stable.get("primary_selector") or (ranked[0] if ranked else str(selectors.get("css") or "")))
    if not selector_passes_filters(primary):
        primary = next((r for r in ranked if selector_passes_filters(str(r))), "") or str(
            target.get("tag") or "input"
        )
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
    }


def _build_signals(
    ev: dict[str, Any],
    *,
    resolved_intent: str,
    policy: dict[str, Any],
    anchors_override: list[dict[str, Any]] | None = None,
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


def _build_step(ev: dict[str, Any], bundle: PolicyBundle) -> SkillStep:
    policy = bundle.data
    action_payload = optimize_scroll(ev)
    if action_payload == "scroll":
        visual = ev.get("visual") or {}
        scroll_screenshot = (
            visual.get("full_screenshot")
            or visual.get("element_snapshot")
            or ""
        )
        scroll_position = visual.get("scroll_position") or ""
        visual_signals: dict[str, Any] = {"scroll_position": scroll_position}
        if scroll_screenshot:
            visual_signals["scroll_screenshot"] = scroll_screenshot
        return SkillStep(
            action=action_payload,
            signals={
                "visual": visual_signals,
            },
        )
    anchors = clean_anchors(
        ev.get("anchors") or [],
        ev.get("context") or {},
        policy,
        target=dict(ev.get("target") or {}),
        semantic=dict(ev.get("semantic") or {}),
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
    extra_anchors = suggest_anchors_from_context(
        ev.get("context") or {},
        semantic,
        policy,
        target=dict(ev.get("target") or {}),
        page=dict(ev.get("page") or {}),
    )
    merged_anchors = anchors + [a for a in extra_anchors if a not in anchors]
    merged_anchors = rank_merged_anchors(merged_anchors, ev, intent, policy)
    validation = _build_validation(ev_with_intent, state_diff, policy)
    recovery_dict = default_recovery_block(intent, merged_anchors, policy)
    recovery_dict = merge_recovery_strategies_for_wait_shape(
        recovery_dict,
        dict(validation.wait_for) if validation.wait_for else {},
        policy,
    )
    recovery = RecoveryBlock(**recovery_dict)
    target = _build_target(ev, policy)
    signals = _build_signals(ev, resolved_intent=intent, policy=policy, anchors_override=merged_anchors)
    value, input_binding = _derive_input_binding(ev, policy)
    confidence_protocol = _merge_compile_warnings(
        _default_confidence_protocol(bundle),
        ev_with_intent,
        merged_anchors,
        policy,
    )
    return SkillStep(
        action=action_payload,
        intent=intent,
        target=target,
        signals=signals,
        state={"before": state_before, "after": state_after},
        state_diff=state_diff,
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
    cleaned_events = fix_step_order(clean_steps(events, pol), pol)
    steps = [_build_step(e, bundle) for e in cleaned_events]
    now = datetime.now(timezone.utc).isoformat()
    meta = SkillMeta(
        id=skill_id,
        version=version,
        title=title or skill_id,
        created_at=now,
        source_session_id=source_session_id,
        compiler_policy_version=bundle.version,
        compiler_policy_hash=bundle.content_hash,
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
            "recovery_assist": settings.llm_recovery_assist,
            "max_calls_per_step": settings.llm_max_calls_per_step,
            "timeout_ms": settings.llm_timeout_ms,
        },
    )
