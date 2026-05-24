"""LLM-driven selector compilation (Phase 3).

The recorder captures raw signals (DOM snapshot, ancestors, bbox, surrounding text).
This module asks an LLM to generate Playwright CSS selector candidates against the
recorded DOM snapshot, validates each candidate, and caches the result by
(dom_hash, element_bbox, model).

The runtime then tries these in order before falling back to a11y / LLM recovery.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.llm.openapi_client import (
    SelectorCandidate,
    generate_selector_candidates_with_fallback,
    infer_workflow_intent,
)
from app.storage import selector_cache, snapshots
from app.models.skill_spec import WorkflowIntentGraph, WorkflowIntentStep


_TOO_GENERIC = {"button", "div", "span", "input", "a", "form", "li", "ul", "p", "h1", "h2", "h3"}
_FORBIDDEN_PREFIXES = ("/", "//", "xpath=", "xpath:")


@dataclass
class SelectorCompileTask:
    """Per-step input for the LLM selector generator."""

    step_index: int
    snapshot_ref: str
    snapshot_hash: str
    dom_path: str | None
    element_bbox: dict[str, int]
    element_ancestors: list[dict[str, Any]]
    surrounding_text: str
    action_type: str
    target_dom: dict[str, Any]  # tag, id, classes, inner_text, role, aria_label, name, placeholder


def is_obviously_invalid(selector: str) -> bool:
    """Cheap rule-based filter before spending Playwright validation cycles."""
    s = (selector or "").strip()
    if not s or len(s) > 1024:
        return True
    low = s.lower()
    for pref in _FORBIDDEN_PREFIXES:
        if low.startswith(pref):
            return True
    if s in _TOO_GENERIC:
        return True
    # Sanity: must contain at least one of CSS's selector hooks.
    if not re.search(r"[#.\[\]:>~+\s]|[a-z][a-z0-9-]*", low):
        return True
    return False


def _count_matches_in_html(selector: str, html: str) -> int:
    """Best-effort match count via parsing the recorded snapshot.

    Uses html.parser + a tiny CSS subset because we only need a coarse check
    (1 vs many vs zero) — full Playwright validation is reserved for ambiguous
    cases at runtime. Returns -1 if the parser can't evaluate the selector.
    """
    try:
        from bs4 import BeautifulSoup, SoupStrainer  # type: ignore  # noqa: F401
    except ImportError:
        return -1
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        matches = soup.select(selector)
        return len(matches)
    except Exception:  # noqa: BLE001 — selector grammar mismatch, etc.
        return -1


def validate_selector(selector: str, dom_snapshot: str | None) -> tuple[bool, int]:
    """Returns (passes, match_count). passes=True iff exactly one match.

    When BeautifulSoup is unavailable or the selector uses Playwright extensions
    not supported by html.parser, we accept the candidate (skip rule-based check)
    and let runtime Playwright validation decide.
    """
    if is_obviously_invalid(selector):
        return False, 0
    if not dom_snapshot:
        return True, -1
    n = _count_matches_in_html(selector, dom_snapshot)
    if n < 0:
        return True, -1
    return n == 1, n


def rank_candidates(candidates: list[SelectorCandidate]) -> list[SelectorCandidate]:
    """Stability ordering: testid > aria > name > placeholder > text > tag+class."""

    def score(c: SelectorCandidate) -> tuple[int, int]:
        s = c.selector.lower()
        prio = 9
        if "data-testid" in s or "data-test-id" in s:
            prio = 0
        elif "aria-label" in s:
            prio = 1
        elif "[name=" in s:
            prio = 2
        elif "[placeholder=" in s:
            prio = 3
        elif "#" in s:
            prio = 4
        elif ":has-text" in s or ":text" in s:
            prio = 5
        elif "nth-of-type" in s or "nth-child" in s:
            prio = 8
        return (prio, c.rank or 99)

    return sorted(candidates, key=score)


def _dom_snippet_for_llm(dom_snapshot: str, max_chars: int = 60000) -> str:
    """Trim the snapshot so it fits in the LLM context window.

    For very large pages we send the head plus the section around the element's
    deepest ancestor; for now a head-truncated slice keeps the prompt bounded.
    """
    if not dom_snapshot:
        return ""
    if len(dom_snapshot) <= max_chars:
        return dom_snapshot
    return dom_snapshot[:max_chars] + "\n<!-- truncated -->\n"


def compile_selectors_for_task(
    task: SelectorCompileTask,
    *,
    session_id: str,
    model: str | None = None,
) -> list[SelectorCandidate]:
    """Generate, validate, rank, and cache selector candidates for one element."""
    # Cache lookup.
    effective_model = model or settings.llm_selector_model or "default"
    cached = selector_cache.get(task.snapshot_hash, task.element_bbox, effective_model)
    if cached:
        return [SelectorCandidate.from_dict(c) for c in cached]

    # Load DOM snapshot for validation.
    dom_snapshot = snapshots.read_dom_snapshot(session_id, task.snapshot_hash) if task.snapshot_hash else None

    # LLM call with adaptive fallback.
    raw_candidates = generate_selector_candidates_with_fallback(
        dom_snippet=_dom_snippet_for_llm(dom_snapshot or ""),
        element_bbox=task.element_bbox,
        element_ancestors=task.element_ancestors,
        surrounding_text=task.surrounding_text,
        action_type=task.action_type,
        target_dom=task.target_dom,
        candidates_wanted=settings.llm_selector_candidates,
        model=model,
    )
    if not raw_candidates:
        return []

    # Validate each candidate; discard obvious failures.
    validated: list[SelectorCandidate] = []
    for cand in raw_candidates:
        passes, _count = validate_selector(cand.selector, dom_snapshot)
        if passes:
            validated.append(cand)

    ranked = rank_candidates(validated)

    # Cache (even empty results) so we don't repeat doomed LLM calls.
    selector_cache.set(
        task.snapshot_hash,
        task.element_bbox,
        effective_model,
        [c.to_dict() for c in ranked],
    )
    return ranked


def compile_workflow_selectors(
    tasks: list[SelectorCompileTask],
    *,
    session_id: str,
    model: str | None = None,
) -> dict[int, list[SelectorCandidate]]:
    """Compile selectors for all tasks. Groups by snapshot_hash for cache efficiency.

    Returns {step_index: [candidates...]}.
    """
    by_hash: dict[str, list[SelectorCompileTask]] = defaultdict(list)
    no_hash: list[SelectorCompileTask] = []
    for t in tasks:
        if t.snapshot_hash:
            by_hash[t.snapshot_hash].append(t)
        else:
            no_hash.append(t)

    result: dict[int, list[SelectorCandidate]] = {}
    for _h, group in by_hash.items():
        # Same DOM state across many steps: cache amortizes per-element calls.
        for task in group:
            result[task.step_index] = compile_selectors_for_task(task, session_id=session_id, model=model)
    for task in no_hash:
        # Without a snapshot we still ask the LLM but can only do rule-based filtering.
        result[task.step_index] = compile_selectors_for_task(task, session_id=session_id, model=model)
    return result


def build_workflow_intent_graph(
    steps_summary: list[dict[str, Any]],
    page_urls: list[str],
    *,
    model: str | None = None,
) -> WorkflowIntentGraph:
    """Single LLM call producing high-level goal + per-step semantic intent."""
    raw = infer_workflow_intent(
        steps_summary=steps_summary,
        page_urls=page_urls,
        model=model,
    )
    if not raw:
        return WorkflowIntentGraph()
    intent_steps: list[WorkflowIntentStep] = []
    for item in raw.get("steps") or []:
        if not isinstance(item, dict):
            continue
        try:
            intent_steps.append(
                WorkflowIntentStep(
                    index=int(item.get("index") or 0),
                    intent=str(item.get("intent") or ""),
                    verification_anchor=str(item.get("verification_anchor") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return WorkflowIntentGraph(
        goal=str(raw.get("goal") or ""),
        steps=intent_steps,
        decision_points=list(raw.get("decision_points") or []),
        expected_end_state=dict(raw.get("expected_end_state") or {}),
    )


def task_from_recorded_event(ev: dict[str, Any], step_index: int) -> SelectorCompileTask:
    """Convert one raw recorded event dict into a SelectorCompileTask."""
    snapshot = ev.get("snapshot") or {}
    visual = ev.get("visual") or {}
    bbox = visual.get("bbox") or {}
    target = ev.get("target") or {}
    action = ev.get("action") or {}
    return SelectorCompileTask(
        step_index=step_index,
        snapshot_ref=str(snapshot.get("ref") or ""),
        snapshot_hash=str(snapshot.get("dom_hash") or ""),
        dom_path=snapshot.get("dom_path"),
        element_bbox={
            "x": int(bbox.get("x") or 0),
            "y": int(bbox.get("y") or 0),
            "w": int(bbox.get("w") or 0),
            "h": int(bbox.get("h") or 0),
        },
        element_ancestors=list(ev.get("ancestors") or []),
        surrounding_text=str(ev.get("surrounding_text") or ""),
        action_type=str(action.get("action") or ""),
        target_dom={
            "tag": str(target.get("tag") or ""),
            "id": target.get("id"),
            "classes": list(target.get("classes") or []),
            "inner_text": str(target.get("inner_text") or "")[:200],
            "role": target.get("role"),
            "aria_label": target.get("aria_label"),
            "name": target.get("name"),
            "placeholder": target.get("placeholder"),
        },
    )
