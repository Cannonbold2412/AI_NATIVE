"""Phase 6 — merge user-provided fixes into a compiled skill (1-click fix API)."""

from __future__ import annotations

from typing import Any

from app.compiler.intent_access import get_effective_intent_from_skill_step
from app.compiler.recovery_policy import (
    merge_recovery_strategies_for_wait_shape,
    recovery_strategies_for_intent,
    suggest_anchors_from_context,
)
from app.confidence.layered import layered_decision
from app.confidence.uncertainty import audit_reference
from app.llm.semantic_llm import SemanticLLMInput, enrich_semantic
from app.policy.bundle import get_policy_bundle
from app.policy.intent_ontology import sanitize_intent_token


def _build_reference_from_signals(step: dict[str, Any]) -> dict[str, Any]:
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


def _enhance_step_with_llm(step: dict[str, Any]) -> dict[str, Any]:
    """1-click fix enhancement: improve intent + anchors + strategies (assist-only)."""
    out = dict(step)
    signals = out.get("signals") or {}
    dom = signals.get("dom") or {}
    semantic = signals.get("semantic") or {}
    context = signals.get("context") or {}
    pol = get_policy_bundle().data
    unc = pol.get("uncertainty") if isinstance(pol.get("uncertainty"), dict) else {}
    patch_min = float(unc.get("patch_llm_min_confidence", 0.8))
    llm = enrich_semantic(
        SemanticLLMInput(
            raw_text=str(dom.get("inner_text") or semantic.get("normalized_text") or ""),
            element_type=str(dom.get("tag") or semantic.get("role") or ""),
            context=str(context.get("page_title") or ""),
        )
    )
    if llm.confidence >= patch_min:
        resolved = str(out.get("intent") or llm.intent or "").strip()
        out["intent"] = resolved
        signals = dict(out.get("signals") or {})
        sem = dict(signals.get("semantic") or {})
        if resolved:
            sem["final_intent"] = resolved
            sem["llm_intent"] = resolved
        signals["semantic"] = sem
        out["signals"] = signals
        recovery = dict(out.get("recovery") or {})
        recovery["intent"] = resolved or llm.intent
        recovery["final_intent"] = str(recovery.get("intent") or "").strip()
        anchors = list(recovery.get("anchors") or [])
        if not anchors:
            anchors = suggest_anchors_from_context(context, semantic, pol, target=dict(dom or {}))
        recovery["anchors"] = anchors
        intent_for_recovery = str(recovery.get("intent") or resolved or llm.intent or "").strip()
        strategies = list(recovery_strategies_for_intent(intent_for_recovery, pol))
        if "llm_reasoned_match" not in strategies:
            strategies.append("llm_reasoned_match")
        recovery["strategies"] = strategies
        out["recovery"] = recovery
    return out


def _apply_top_level_step_fields(step: dict[str, Any], patch: dict[str, Any]) -> None:
    if "intent" in patch and isinstance(patch["intent"], str):
        raw = str(patch["intent"]).strip()
        prev = str(step.get("intent") or "").strip()
        resolved = sanitize_intent_token(raw, sanitize_intent_token(prev, "edited_step"))
        step["intent"] = resolved
        signals = dict(step.get("signals") or {})
        sem = dict(signals.get("semantic") or {})
        if resolved:
            sem["final_intent"] = resolved
            sem["llm_intent"] = resolved
        signals["semantic"] = sem
        step["signals"] = signals
    if "value" in patch:
        step["value"] = patch["value"]


def _sync_recovery_deterministic(step: dict[str, Any]) -> dict[str, Any]:
    """After a non-LLM patch, align recovery strategies with intent + wait_for (deterministic)."""
    pol = get_policy_bundle().data
    intent = get_effective_intent_from_skill_step(step) or str(step.get("intent") or "").strip()
    recovery = dict(step.get("recovery") or {})
    recovery["intent"] = intent
    recovery["final_intent"] = intent
    recovery["strategies"] = recovery_strategies_for_intent(intent, pol)
    wf = (step.get("validation") or {}).get("wait_for") or {}
    recovery = merge_recovery_strategies_for_wait_shape(recovery, dict(wf) if isinstance(wf, dict) else {}, pol)
    out = dict(step)
    out["recovery"] = recovery
    return out


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_step_patch(
    document: dict[str, Any],
    step_index: int,
    patch: dict[str, Any],
    *,
    assist_llm: bool = True,
) -> dict[str, Any]:
    """Returns a new document dict with step merged and meta.version incremented.

    When ``assist_llm`` is False (editor saves), semantic enrichment LLM is skipped and
    recovery strategies are recomputed deterministically from intent + wait_for.
    """
    doc = dict(document)
    skills = list(doc.get("skills") or [])
    if not skills:
        raise ValueError("no_skills_block")
    block = dict(skills[0])
    steps = list(block.get("steps") or [])
    if step_index < 0 or step_index >= len(steps):
        raise ValueError("step_index_out_of_range")
    step = dict(steps[step_index])
    for key in (
        "target",
        "signals",
        "validation",
        "recovery",
        "confidence_protocol",
        "decision_policy",
    ):
        if key in patch and isinstance(patch[key], dict):
            base = step.get(key) or {}
            step[key] = deep_merge(dict(base), dict(patch[key]))
    _apply_top_level_step_fields(step, patch)
    if assist_llm:
        step = _enhance_step_with_llm(step)
    else:
        step = _sync_recovery_deterministic(step)
    steps[step_index] = step
    block["steps"] = steps
    skills[0] = block
    doc["skills"] = skills
    meta = dict(doc.get("meta") or {})
    meta["version"] = int(meta.get("version", 1)) + 1
    doc["meta"] = meta
    return doc


def revalidate_step(step: dict[str, Any]) -> dict[str, Any]:
    """Deterministic checks after a user fix (no browser execution)."""
    ref = _build_reference_from_signals(step)
    issues = audit_reference(ref)
    proto = step.get("confidence_protocol") if isinstance(step.get("confidence_protocol"), dict) else None
    self_check = layered_decision(ref, ref, protocol=proto)
    return {"audit_issues": issues, "self_check": self_check}
