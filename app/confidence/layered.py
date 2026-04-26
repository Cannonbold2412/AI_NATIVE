"""Layered confidence (Layers 1–3) + global recovery blend (Layer 4). Policy-resolved coefficients."""

from __future__ import annotations

import difflib
from typing import Any

from app.compiler.intent_access import get_effective_intent
from app.confidence.constants import RECOVERY_GLOBAL_WEIGHTS, THRESHOLDS
from app.confidence.uncertainty import is_top_two_ambiguous
from app.llm.recovery_llm import RecoveryCandidate, RecoveryLLMInput, assist_recovery
from app.llm.vision_llm import VisionCandidate, VisionLLMInput, assist_vision


def _effective_protocol(reference: dict[str, Any], protocol: dict[str, Any] | None) -> dict[str, Any]:
    base = reference.get("confidence_protocol") if isinstance(reference.get("confidence_protocol"), dict) else {}
    if protocol:
        merged = dict(base)
        merged.update(protocol)
        return merged
    return dict(base) if base else {}


def _thresholds(protocol: dict[str, Any]) -> dict[str, float]:
    t = protocol.get("layer_thresholds")
    if isinstance(t, dict) and t:
        out: dict[str, float] = {}
        for k, v in t.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out if out else dict(THRESHOLDS)
    return dict(THRESHOLDS)


def _recovery_weights(protocol: dict[str, Any]) -> dict[str, float]:
    w = protocol.get("recovery_global_weights")
    if isinstance(w, dict) and w:
        out: dict[str, float] = {}
        for k, v in w.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out if out else dict(RECOVERY_GLOBAL_WEIGHTS)
    return dict(RECOVERY_GLOBAL_WEIGHTS)


def _layer_scorers(protocol: dict[str, Any]) -> dict[str, Any]:
    ls = protocol.get("layer_scorers")
    return dict(ls) if isinstance(ls, dict) else {}


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def score_dom(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    protocol: dict[str, Any] | None = None,
) -> float:
    rt = reference.get("target") or {}
    ct = candidate.get("target") or {}
    rs = reference.get("selectors") or {}
    cs = candidate.get("selectors") or {}
    wmap = _layer_scorers(_effective_protocol(reference, protocol)).get("dom") or {}
    id_w = float(wmap.get("id", 0.35))
    tag_w = float(wmap.get("tag", 0.15))
    class_w = float(wmap.get("class", 0.25))
    xpath_w = float(wmap.get("xpath", 0.25))

    id_score = 1.0 if rt.get("id") and rt.get("id") == ct.get("id") else 0.0
    tag_score = 1.0 if rt.get("tag") and rt.get("tag") == ct.get("tag") else 0.0
    class_score = _jaccard(list(rt.get("classes") or []), list(ct.get("classes") or []))
    rx = str(rs.get("xpath") or "")
    cx = str(cs.get("xpath") or "")
    xpath_score = difflib.SequenceMatcher(a=rx, b=cx).ratio() if rx or cx else 1.0

    return round(id_w * id_score + tag_w * tag_score + class_w * class_score + xpath_w * xpath_score, 6)


def score_semantic(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    protocol: dict[str, Any] | None = None,
) -> float:
    rs = reference.get("semantic") or {}
    cs = candidate.get("semantic") or {}
    wmap = _layer_scorers(_effective_protocol(reference, protocol)).get("semantic") or {}
    tw = float(wmap.get("text", 0.35))
    rw = float(wmap.get("role", 0.25))
    iw = float(wmap.get("intent", 0.2))
    ctx_w = float(wmap.get("context", 0.2))
    pm = float(wmap.get("parent_mix", 0.5))
    fm = float(wmap.get("form_mix", 0.5))

    text_a = str(rs.get("normalized_text") or "")
    text_b = str(cs.get("normalized_text") or "")
    text_score = difflib.SequenceMatcher(a=text_a, b=text_b).ratio() if text_a or text_b else 1.0
    role_score = 1.0 if rs.get("role") == cs.get("role") else 0.0
    ri = get_effective_intent(rs)
    ci = get_effective_intent(cs)
    intent_match = (ri == ci and bool(ri)) or (
        rs.get("intent_hint") == cs.get("intent_hint") and not ri and not ci
    )
    intent_score = 1.0 if intent_match else 0.0
    rp = reference.get("context") or {}
    cp = candidate.get("context") or {}
    parent_score = difflib.SequenceMatcher(
        a=str(rp.get("parent") or ""), b=str(cp.get("parent") or "")
    ).ratio()
    form_score = 1.0 if (rp.get("form_context") or None) == (cp.get("form_context") or None) else 0.0
    den = pm + fm or 1.0
    ctx_mix = (pm * parent_score + fm * form_score) / den
    return round(tw * text_score + rw * role_score + iw * intent_score + ctx_w * ctx_mix, 6)


def _bbox_iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax, ay, aw, ah = int(a.get("x", 0)), int(a.get("y", 0)), int(a.get("w", 0)), int(a.get("h", 0))
    bx, by, bw, bh = int(b.get("x", 0)), int(b.get("y", 0)), int(b.get("w", 0)), int(b.get("h", 0))
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    iw = max(0, x2 - x1)
    ih = max(0, y2 - y1)
    inter = iw * ih
    ua = aw * ah + bw * bh - inter
    return inter / ua if ua else 0.0


def score_visual(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    protocol: dict[str, Any] | None = None,
) -> float:
    wmap = _layer_scorers(_effective_protocol(reference, protocol)).get("visual") or {}
    vp = float(wmap.get("viewport_mismatch_penalty", 0.85))
    iou_w = float(wmap.get("iou_weight", 0.65))
    pos_w = float(wmap.get("pos_weight", 0.35))
    rv = reference.get("visual") or {}
    cv = candidate.get("visual") or {}
    if str(rv.get("viewport") or "") != str(cv.get("viewport") or ""):
        viewport_penalty = vp
    else:
        viewport_penalty = 1.0
    iou = _bbox_iou(rv.get("bbox") or {}, cv.get("bbox") or {})
    ra = rv.get("bbox") or {}
    ca = cv.get("bbox") or {}
    cx = (int(ra.get("x", 0)) + int(ra.get("w", 0)) / 2, int(ra.get("y", 0)) + int(ra.get("h", 0)) / 2)
    cb = (int(ca.get("x", 0)) + int(ca.get("w", 0)) / 2, int(ca.get("y", 0)) + int(ca.get("h", 0)) / 2)
    vw = max(int(str(rv.get("viewport") or "0x0").split("x")[0] or "1"), 1)
    vh = max(int(str(rv.get("viewport") or "0x0").split("x")[-1] or "1"), 1)
    dist = abs(cx[0] - cb[0]) / vw + abs(cx[1] - cb[1]) / vh
    pos_score = max(0.0, 1.0 - dist / 2.0)
    raw = iou_w * iou + pos_w * pos_score
    return round(viewport_penalty * raw, 6)


def score_context(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    protocol: dict[str, Any] | None = None,
) -> float:
    wmap = _layer_scorers(_effective_protocol(reference, protocol)).get("context") or {}
    uw = float(wmap.get("url", 0.6))
    tw = float(wmap.get("title", 0.4))
    url_a = str(reference.get("page_url") or "")
    url_b = str(candidate.get("page_url") or "")
    url_score = difflib.SequenceMatcher(a=url_a, b=url_b).ratio() if url_a or url_b else 1.0
    title_a = str(reference.get("page_title") or "")
    title_b = str(candidate.get("page_title") or "")
    title_score = difflib.SequenceMatcher(a=title_a, b=title_b).ratio() if title_a or title_b else 1.0
    s = uw + tw
    if s <= 0:
        return round(0.6 * url_score + 0.4 * title_score, 6)
    return round((uw * url_score + tw * title_score) / s, 6)


def global_recovery_score(
    dom: float,
    semantic: float,
    visual: float,
    context: float,
    *,
    weights: dict[str, float] | None = None,
) -> float:
    w = weights or RECOVERY_GLOBAL_WEIGHTS
    g = (
        w["dom"] * dom
        + w["semantic"] * semantic
        + w.get("visual", 0.15) * visual
        + w["context"] * context
    )
    return round(min(1.0, max(0.0, g)), 6)


def layered_decision(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns execute-at-layer, recovery global score, and numeric breakdown."""
    eff = _effective_protocol(reference, protocol)
    th = _thresholds(eff)
    wg = _recovery_weights(eff)
    d = score_dom(reference, candidate, protocol=protocol)
    if d >= th["dom_execute"]:
        return {
            "decision": "execute",
            "layer": "dom",
            "scores": {"dom": d},
            "global_recovery": None,
            "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
        }
    s = score_semantic(reference, candidate, protocol=protocol)
    if s >= th["semantic_execute"]:
        return {
            "decision": "execute",
            "layer": "semantic",
            "scores": {"dom": d, "semantic": s},
            "global_recovery": None,
            "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
        }
    v = score_visual(reference, candidate, protocol=protocol)
    if v >= th["visual_execute"]:
        return {
            "decision": "execute",
            "layer": "visual",
            "scores": {"dom": d, "semantic": s, "visual": v},
            "global_recovery": None,
            "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
        }
    c = score_context(reference, candidate, protocol=protocol)
    g = global_recovery_score(d, s, v, c, weights=wg)
    return {
        "decision": "recovery",
        "layer": "recovery",
        "scores": {"dom": d, "semantic": s, "visual": v, "context": c},
        "global_recovery": g,
        "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
    }


def recovery_decision_with_assist(
    reference: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    context: str = "",
    protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic-first recovery selection with optional LLM assist on ambiguity only."""
    eff = _effective_protocol(reference, protocol)
    unc = eff.get("uncertainty_policy") if isinstance(eff.get("uncertainty_policy"), dict) else {}
    margin = float(unc.get("candidate_ambiguity_margin", 0.03))
    assist_min = float(unc.get("assist_min_confidence", 0.75))
    budget = int(unc.get("recovery_candidate_budget", 5))
    wg = _recovery_weights(eff)

    scored: list[dict[str, Any]] = []
    for c in candidates:
        d = score_dom(reference, c, protocol=protocol)
        s = score_semantic(reference, c, protocol=protocol)
        v = score_visual(reference, c, protocol=protocol)
        x = score_context(reference, c, protocol=protocol)
        g = global_recovery_score(d, s, v, x, weights=wg)
        scored.append(
            {
                "id": str((c.get("target") or {}).get("id") or c.get("selectors", {}).get("css") or "candidate"),
                "global": g,
                "candidate": c,
            }
        )
    scored.sort(key=lambda row: row["global"], reverse=True)
    if not scored:
        return {"decision": "ask_user", "reason": "no_candidates", "scores": []}
    top_scores = [float(x["global"]) for x in scored[:2]]
    ambiguous = is_top_two_ambiguous(top_scores, margin=margin)
    if not ambiguous:
        return {
            "decision": "recovery_select",
            "selected": scored[0]["id"],
            "confidence": scored[0]["global"],
            "source": "deterministic",
            "scores": [{"id": s["id"], "global": s["global"]} for s in scored],
            "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
        }
    top_rows = scored[:budget]
    ref_sem = reference.get("semantic") or {}
    ref_sem_d = ref_sem if isinstance(ref_sem, dict) else {}
    eff_intent = get_effective_intent(ref_sem_d)
    llm_inp = RecoveryLLMInput(
        intent=str(eff_intent or ref_sem_d.get("intent_hint") or "interact"),
        candidates=[
            RecoveryCandidate(
                id=row["id"],
                text=str((row["candidate"].get("target") or {}).get("inner_text") or ""),
                role=str((row["candidate"].get("semantic") or {}).get("role") or ""),
                score=float(row["global"]),
            )
            for row in top_rows
        ],
        context=context,
    )
    llm_out = assist_recovery(llm_inp, call_count=0)
    if llm_out and llm_out.confidence >= assist_min:
        return {
            "decision": "recovery_select",
            "selected": llm_out.selected,
            "confidence": llm_out.confidence,
            "source": "llm_assist",
            "reason": llm_out.reason,
            "scores": [{"id": s["id"], "global": s["global"]} for s in scored],
            "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
        }
    screenshot = str((reference.get("visual") or {}).get("full_screenshot") or "")
    if screenshot:
        vis_out = assist_vision(
            VisionLLMInput(
                full_screenshot=screenshot,
                candidates=[
                    VisionCandidate(
                        element_id=row["id"],
                        crop_path=str((row["candidate"].get("visual") or {}).get("element_snapshot") or ""),
                        text=str((row["candidate"].get("target") or {}).get("inner_text") or ""),
                    )
                    for row in top_rows
                ],
                intent=str((llm_inp.intent or "interact")),
            ),
            call_count=0,
            recovery_phase=True,
        )
        if vis_out and vis_out.confidence >= assist_min:
            return {
                "decision": "recovery_select",
                "selected": vis_out.best_candidate,
                "confidence": vis_out.confidence,
                "source": "vision_llm_assist",
                "reason": vis_out.reason,
                "scores": [{"id": s["id"], "global": s["global"]} for s in scored],
                "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
            }
    return {
        "decision": "ask_user",
        "reason": "ambiguous_after_assist",
        "scores": [{"id": s["id"], "global": s["global"]} for s in scored],
        "resolved_policy": {"policy_version": eff.get("policy_version"), "policy_hash": eff.get("policy_hash")},
    }
