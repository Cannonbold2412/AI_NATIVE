"""Intent-centric decision layer: deterministic validation hints and anchor ranking.

Inputs are signals + FINAL_INTENT + policy. LLM output is not used here.
"""

from __future__ import annotations

from typing import Any

from app.compiler.intent_access import get_effective_intent


def infer_compiled_validation(
    step: dict[str, Any],
    state_diff: dict[str, Any],
    page_url: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Single entry: wait_for + success_conditions from FINAL_INTENT-first planner."""
    from app.compiler.validation_planner import infer_success_conditions, infer_wait_for_shape

    wait_for = infer_wait_for_shape(step, state_diff, policy)
    sem = step.get("semantic") or {}
    final_intent = get_effective_intent(sem if isinstance(sem, dict) else {})
    success_conditions = infer_success_conditions(
        wait_for,
        state_diff,
        page_url,
        policy,
        final_intent=final_intent,
        source_step=step,
    )
    return {"wait_for": wait_for, "success_conditions": success_conditions}


def _decision_section(policy: dict[str, Any]) -> dict[str, Any]:
    sec = policy.get("decision_layer")
    return sec if isinstance(sec, dict) else {}


def intent_primary_validation_enabled(policy: dict[str, Any]) -> bool:
    return bool(_decision_section(policy).get("intent_primary_validation", False))


def semantic_anchor_ranking_enabled(policy: dict[str, Any]) -> bool:
    return bool(_decision_section(policy).get("semantic_anchor_ranking", False))


def _anchor_rank_weights(policy: dict[str, Any]) -> dict[str, Any]:
    dl = _decision_section(policy)
    raw = dl.get("anchor_rank_weights")
    return raw if isinstance(raw, dict) else {}


def _anchor_score(anchor: dict[str, Any], ev: dict[str, Any], final_intent: str, policy: dict[str, Any]) -> float:
    el_raw = str(anchor.get("element") or "")
    el = el_raw.strip().lower()
    relation = str(anchor.get("relation") or "").strip().lower()
    if not el:
        return -1.0
    target = ev.get("target") or {}
    semantic = ev.get("semantic") or {}
    ctx = ev.get("context") or {}
    blob = " ".join(
        [
            str(target.get("inner_text") or ""),
            str(target.get("name") or ""),
            str(target.get("aria_label") or ""),
            str(target.get("placeholder") or ""),
            str(semantic.get("normalized_text") or ""),
            final_intent.replace("_", " "),
        ]
    ).lower()
    score = 0.0
    if el in blob:
        score += 4.0
    for tok in el.replace(":", " ").split():
        t = tok.strip().lower()
        if len(t) > 2 and t in blob:
            score += 1.5
    sibs = " ".join(str(s) for s in (ctx.get("siblings") or [])).lower()
    parent = str(ctx.get("parent") or "").lower()
    if el in sibs or el in parent:
        score += 2.0
    if relation == "near" and ("label" in el or "for=" in el_raw.lower()):
        score += 1.0
    dl = _decision_section(policy)
    rw = _anchor_rank_weights(policy)
    w_intent = float(rw.get("intent_token_hit", 2.0))
    w_scope = float(rw.get("selector_scope_bonus", 1.0))
    w_multi = float(rw.get("multiword_phrase_bonus", 0.55))
    w_short = float(rw.get("short_singleword_without_signal_penalty", -0.45))
    short_max = int(rw.get("short_token_char_max", 6))

    intent_tokens = intent_outcome_tokens(final_intent, policy)
    for it in intent_tokens:
        if len(it) >= 3 and it in el:
            score += w_intent
    if any(ch in el for ch in "#.[/@"):
        score += w_scope
    if " " in el.strip():
        score += w_multi

    raw_dep = dl.get("anchor_deprioritize_elements")
    if raw_dep is None:
        deprior = ["form", "section"]
    else:
        deprior = [str(x).strip().lower() for x in raw_dep if str(x).strip()]
    if el in deprior and score < 2.0:
        score -= 0.8
    low_info = {str(x).strip().lower() for x in (dl.get("anchor_low_information_substrings") or ["header", "nav", "footer", "main", "h1", "h2", "h3"])}
    if any(s in el for s in low_info) and score < 1.5:
        score -= 0.5
    if len(el_raw) > 80:
        score -= 0.3

    has_intent_hit = any(len(it) >= 3 and it in el for it in intent_tokens)
    has_context_signal = el in sibs or el in parent or el in blob
    if " " not in el and len(el) <= short_max and not has_intent_hit and not has_context_signal:
        score += w_short
    return score


def rank_merged_anchors(
    anchors: list[dict[str, Any]],
    ev: dict[str, Any],
    final_intent: str,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Order anchors by semantic informativeness relative to target + intent (stable)."""
    if not semantic_anchor_ranking_enabled(policy) or not anchors:
        return list(anchors)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for i, a in enumerate(anchors):
        if not isinstance(a, dict):
            continue
        s = _anchor_score(a, ev, final_intent, policy)
        scored.append((s, i, dict(a)))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [t[2] for t in scored]


def intent_outcome_tokens(final_intent: str, policy: dict[str, Any]) -> list[str]:
    """Deterministic tokens derived from FINAL_INTENT for validation hints (not UI-specific)."""
    dl = _decision_section(policy)
    stop = {str(x).strip().lower() for x in (dl.get("intent_token_stopwords") or ["the", "and", "for", "to", "a", "an"])}
    generic = {"interact", "perform", "action", "provide", "input", "advance", "ui", "flow", "click", "enter", "focus"}
    out: list[str] = []
    for part in (final_intent or "").replace("-", "_").split("_"):
        p = part.strip().lower()
        if len(p) < 3 or p in stop or p in generic:
            continue
        if p not in out:
            out.append(p)
        if len(out) >= 8:
            break
    return out


def intent_tokens_as_anchor_candidates(
    ev: dict[str, Any],
    final_intent: str,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Add short anchor phrases from FINAL_INTENT tokens only when they appear in page/target context."""
    dl = _decision_section(policy)
    if not bool(dl.get("intent_tokens_as_anchors", True)):
        return []
    page = ev.get("page") or {}
    tgt = ev.get("target") or {}
    sem = ev.get("semantic") or {}
    ctx = ev.get("context") or {}
    blob = " ".join(
        [
            str(page.get("title") or ""),
            str(tgt.get("inner_text") or ""),
            str(sem.get("normalized_text") or ""),
            " ".join(str(s) for s in (ctx.get("siblings") or [])[:4]),
        ]
    ).lower()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tok in intent_outcome_tokens(final_intent, policy):
        if len(tok) < 4 or tok not in blob:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append({"element": tok, "relation": "near"})
    return out


def intent_recovery_extra_strategies(final_intent: str, policy: dict[str, Any]) -> list[str]:
    """Policy-ordered recovery strategy tags from FINAL_INTENT (deterministic; same policy → same list)."""
    dl = _decision_section(policy)
    if not bool(dl.get("intent_recovery_from_facets", True)):
        return []
    raw = dl.get("intent_recovery_facets")
    if not isinstance(raw, list):
        return []
    intent_l = (final_intent or "").lower()
    out: list[str] = []
    for facet in raw:
        if not isinstance(facet, dict):
            continue
        add = str(facet.get("add") or "").strip()
        subs = facet.get("substrings")
        if not add or not isinstance(subs, list):
            continue
        if any(str(s).lower() in intent_l for s in subs if s):
            if add not in out:
                out.append(add)
    return out
