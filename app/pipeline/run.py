"""Phase 2 entrypoint — validate, clean, normalize, dedupe, enrich."""

from __future__ import annotations

import re
from typing import Any

from app.llm.semantic_llm import SemanticLLMInput, enrich_semantic
from app.models.events import RecordedEvent
from app.pipeline.dedupe import dedupe_scroll_events
from app.pipeline.enrich import enrich_event
from app.pipeline.selectors import canonicalize_selectors
from app.pipeline.signals import apply_signal_budget
from app.pipeline.text import collapse_ws, normalize_class_token
from app.policy.bundle import get_policy_bundle

PIPELINE_VERSION = "2.0.0"


def _clean_target(target: dict[str, Any]) -> dict[str, Any]:
    t = dict(target)
    t["inner_text"] = collapse_ws(str(t.get("inner_text", "")), max_len=2000)
    raw_classes = t.get("classes") or []
    cleaned: list[str] = []
    for c in raw_classes:
        nc = normalize_class_token(str(c))
        if nc and nc not in cleaned:
            cleaned.append(nc)
    cleaned.sort()
    t["classes"] = cleaned
    return t


def _clean_semantic(sem: dict[str, Any]) -> dict[str, Any]:
    s = dict(sem)
    s["normalized_text"] = collapse_ws(str(s.get("normalized_text", "")), max_len=500).lower()
    return s


def _clean_context(ctx: dict[str, Any]) -> dict[str, Any]:
    c = dict(ctx)
    sibs = []
    for x in c.get("siblings") or []:
        sx = collapse_ws(str(x), max_len=120)
        if sx and sx not in sibs:
            sibs.append(sx)
    c["siblings"] = sibs
    c["parent"] = collapse_ws(str(c.get("parent", "")), max_len=200)
    if c.get("form_context"):
        c["form_context"] = collapse_ws(str(c["form_context"]), max_len=200)
    return c


def _clean_one(ev: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    row = dict(ev)
    row["target"] = _clean_target(dict(row.get("target") or {}))
    selectors, selector_meta = canonicalize_selectors(dict(row.get("selectors") or {}), policy)
    row["selectors"] = selectors
    extras = dict(row.get("extras") or {})
    extras.update(selector_meta)
    row["extras"] = extras
    row["semantic"] = _clean_semantic(dict(row.get("semantic") or {}))
    row["context"] = _clean_context(dict(row.get("context") or {}))
    if row.get("page"):
        p = dict(row["page"])
        p["title"] = collapse_ws(str(p.get("title", "")), max_len=300)
        row["page"] = p
    return apply_signal_budget(row, policy)


def _semantic_enrich_one(ev: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    out = dict(ev)
    sem = dict(out.get("semantic") or {})
    target = dict(out.get("target") or {})
    page = dict(out.get("page") or {})
    raw_text = str(target.get("inner_text") or sem.get("normalized_text") or "")
    element_type = str(target.get("tag") or sem.get("role") or "")
    context = str(page.get("title") or "")
    enriched = enrich_semantic(
        SemanticLLMInput(raw_text=raw_text, element_type=element_type, context=context)
    )
    sem["llm_intent"] = enriched.intent
    if not sem.get("input_type"):
        sig = policy.get("signals") if isinstance(policy.get("signals"), dict) else {}
        detectors = sig.get("input_type_detectors") or []
        norm = str(sem.get("normalized_text") or enriched.normalized_text).lower()
        if isinstance(detectors, list):
            for det in detectors:
                if not isinstance(det, dict):
                    continue
                pat = str(det.get("regex") or "")
                val = str(det.get("value") or "").strip()
                if pat and val and re.search(pat, norm, re.I):
                    sem["input_type"] = val
                    break
    out["semantic"] = sem
    return out


def _parse_scroll_position(raw: object) -> tuple[int, int]:
    text = str(raw or "").strip()
    if not text:
        return 0, 0
    left, _, right = text.partition(",")
    try:
        return int(float(left.strip() or 0)), int(float(right.strip() or 0))
    except ValueError:
        return 0, 0


def _annotate_scroll_amounts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    last_y = 0
    for ev in events:
        row = dict(ev)
        visual = dict(row.get("visual") or {})
        _, current_y = _parse_scroll_position(visual.get("scroll_position"))
        extras = dict(row.get("extras") or {})
        if str((row.get("action") or {}).get("action") or "").strip().lower() == "scroll":
            extras["scroll_amount"] = current_y - last_y
        row["extras"] = extras
        out.append(row)
        last_y = current_y
    return out


def run_pipeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bundle = get_policy_bundle()
    policy = bundle.data
    validated: list[dict[str, Any]] = []
    for row in events:
        validated.append(RecordedEvent.model_validate(row).model_dump(mode="json"))
    cleaned = [_clean_one(e, policy) for e in validated]
    sem_enriched = [_semantic_enrich_one(e, policy) for e in cleaned]
    deduped = dedupe_scroll_events(sem_enriched)
    scroll_annotated = _annotate_scroll_amounts(deduped)
    return [
        enrich_event(e, pipeline_version=PIPELINE_VERSION, ordinal=i) for i, e in enumerate(scroll_annotated)
    ]
