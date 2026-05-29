"""Intent- and failure-class-aware recovery defaults (policy-driven, not fixed lists only)."""

from __future__ import annotations

from typing import Any

from app.compiler.decision_layer import intent_recovery_extra_strategies, intent_tokens_as_anchor_candidates
from app.compiler.wait_for_shape import leaf_wait_for_conditions


def recovery_strategies_for_intent(intent: str, policy: dict[str, Any]) -> list[str]:
    rd = policy.get("recovery_defaults") if isinstance(policy.get("recovery_defaults"), dict) else {}
    base = list(rd.get("strategies") or [])
    if not isinstance(base, list):
        base = ["semantic match", "position match", "visual match"]
    intent_l = (intent or "").lower()
    out = list(base)
    glue = rd.get("intent_strategy_glue")
    if isinstance(glue, list):
        for rule in glue:
            if not isinstance(rule, dict):
                continue
            add = str(rule.get("add") or "").strip()
            subs = rule.get("substrings")
            if not add or not isinstance(subs, list):
                continue
            if any(str(s).lower() in intent_l for s in subs if s):
                if add not in out:
                    out.append(add)
    else:
        if "scroll" in intent_l and "scroll_anchor" not in out:
            out.append("scroll_anchor")
        if any(k in intent_l for k in ("select", "dropdown", "combobox", "listbox")) and "role_match" not in out:
            out.append("role_match")
    for extra in intent_recovery_extra_strategies(intent, policy):
        if extra not in out:
            out.append(extra)
    return out


def merge_recovery_strategies_for_wait_shape(
    recovery: dict[str, Any],
    wait_for: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Append policy-driven strategies based on compiled wait_for type (deterministic)."""
    val = policy.get("validation") if isinstance(policy.get("validation"), dict) else {}
    hints = val.get("wait_for_recovery_strategy_hints")
    if not isinstance(hints, dict):
        return recovery
    strategies = list(recovery.get("strategies") or [])
    wf = dict(wait_for) if isinstance(wait_for, dict) else {}
    for leaf in leaf_wait_for_conditions(wf):
        wt = str(leaf.get("type") or "none")
        extra = hints.get(wt)
        if not isinstance(extra, list):
            continue
        for s in extra:
            ss = str(s).strip()
            if ss and ss not in strategies:
                strategies.append(ss)
    return {**recovery, "strategies": strategies}


def default_recovery_block(intent: str, anchors: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    rd = policy.get("recovery_defaults") if isinstance(policy.get("recovery_defaults"), dict) else {}
    fin = str(intent or "").strip()
    return {
        "intent": fin,
        "final_intent": fin,
        "anchors": anchors,
        "strategies": recovery_strategies_for_intent(fin, policy),
        "confidence_threshold": float(rd.get("confidence_threshold", 0.85)),
        "max_attempts": int(rd.get("max_attempts", 2)),
        "require_diverse_attempts": bool(rd.get("require_diverse_attempts", True)),
    }


def suggest_anchors_from_context(
    context: dict[str, Any],
    semantic: dict[str, Any],
    policy: dict[str, Any],
    *,
    target: dict[str, Any] | None = None,
    page: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Relational anchors: semantic phrases first; structural extras only when policy allows."""
    from app.compiler.v3 import semantic_anchor_phrase_kept, semantic_context_anchor_candidates

    anchors: list[dict[str, Any]] = list(
        semantic_context_anchor_candidates(context, semantic, target or {}, policy)
    )
    fin = str(semantic.get("final_intent") or semantic.get("llm_intent") or "").strip()
    if fin:
        ev_stub = {
            "page": page or {},
            "target": target or {},
            "semantic": semantic,
            "context": context,
        }
        for a in intent_tokens_as_anchor_candidates(ev_stub, fin, policy):
            if a not in anchors:
                anchors.append(a)
    sec = policy.get("anchors") if isinstance(policy.get("anchors"), dict) else {}
    sem_cfg = sec.get("semantic_anchors") if isinstance(sec.get("semantic_anchors"), dict) else {}
    skip_redundant = bool(sem_cfg.get("skip_redundant_structural_when_semantic", True))
    structural_ok = bool(sem_cfg.get("suggest_structural_extras", True))
    structural_only_when_no_phrases = bool(sem_cfg.get("structural_only_when_no_phrase_anchors", True))
    has_semantic = bool(anchors)

    it = str(semantic.get("input_type") or "").lower()
    role = str(semantic.get("role") or "").lower()
    type_map = sec.get("input_type_anchor_map")
    el_from_map: str | None = None
    if isinstance(type_map, dict) and it:
        raw = type_map.get(it)
        if raw is None:
            for k, v in type_map.items():
                if str(k).lower() == it:
                    raw = v
                    break
        if isinstance(raw, str) and raw.strip():
            el_from_map = raw.strip().lower()
    if el_from_map:
        anchors.append({"element": el_from_map, "relation": "near"})
    elif it == "password":
        anchors.append({"element": "password_input", "relation": "near"})
    elif it == "email":
        anchors.append({"element": "email_input", "relation": "near"})
    if role in {"combobox", "listbox"}:
        anchors.append({"element": "combobox", "relation": "inside"})
    allow_structural = structural_ok and (not skip_redundant or not has_semantic)
    if structural_only_when_no_phrases and has_semantic:
        allow_structural = False
    allowed = set((policy.get("anchors") or {}).get("allowed_elements") or [])
    if allowed:
        anchors = [
            a
            for a in anchors
            if str(a.get("element") or "").lower() in allowed
            or semantic_anchor_phrase_kept(str(a.get("element") or ""), policy)
        ]
    return anchors
