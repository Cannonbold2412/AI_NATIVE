"""Deterministic selector portfolio scoring (stability, uniqueness heuristics, policy weights)."""

from __future__ import annotations

from typing import Any

from conxa_compile.compiler.selector_filters import is_dynamic_id, selector_passes_filters

# Lower index = higher reliability; used as tie-breaker when scores are equal.
_KIND_PRIORITY: dict[str, int] = {
    "aria": 0,
    "label": 1,
    "name": 2,
    "text_based": 3,
    "css": 4,
    "role": 5,
    "xpath": 6,
}


def score_selector_row(kind: str, value: str, policy: dict[str, Any]) -> float:
    if not (value or "").strip():
        return -1.0
    v = value.strip()
    if not selector_passes_filters(v):
        return -1.0
    sel_policy = policy.get("selectors") if isinstance(policy.get("selectors"), dict) else {}
    base_map = sel_policy.get("kind_base_scores") or {}
    base = float(base_map.get(kind, 50))
    score = base
    if kind == "xpath":
        pen = float(sel_policy.get("xpath_length_penalty_per_50", 3))
        score -= (max(0, len(v) - 50) // 50) * pen
    if kind == "css" and is_dynamic_id(v):
        score -= 12.0
    if len(v) > 200:
        score -= 5.0
    return round(score, 4)


def rank_selectors_scored(selectors: dict[str, Any], policy: dict[str, Any]) -> list[tuple[float, str, str]]:
    """Return sorted list of (score, kind, value) descending."""
    rows: list[tuple[float, str, str]] = []
    mapping = [
        ("aria", str(selectors.get("aria") or "").strip()),
        ("name", str(selectors.get("name") or "").strip()),
        ("text_based", str(selectors.get("text_based") or "").strip()),
        ("role", str(selectors.get("role") or "").strip()),
        ("css", str(selectors.get("css") or "").strip()),
        ("xpath", str(selectors.get("xpath") or "").strip()),
    ]
    seen: set[str] = set()
    for kind, val in mapping:
        if not val:
            continue
        s = score_selector_row(kind, val, policy)
        if s < 0 or val in seen:
            continue
        seen.add(val)
        rows.append((s, kind, val))
    rows.sort(key=lambda r: (r[0], -_KIND_PRIORITY.get(r[1], 99)), reverse=True)
    return rows


def ordered_selector_strings(selectors: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    return [v for _, _, v in rank_selectors_scored(selectors, policy)]


def rank_labeled_selector_candidates(
    candidates: list[tuple[str, str]], policy: dict[str, Any]
) -> list[str]:
    """Score and order arbitrary selector strings (e.g. stable-synthesis rows) by policy weights."""
    rows: list[tuple[float, str, str]] = []
    seen: set[str] = set()
    for kind, val in candidates:
        v = (val or "").strip()
        if not v:
            continue
        s = score_selector_row(kind, v, policy)
        if s < 0.0 or v in seen:
            continue
        seen.add(v)
        rows.append((s, kind, v))
    rows.sort(key=lambda r: (r[0], -_KIND_PRIORITY.get(r[1], 99)), reverse=True)
    return [r[2] for r in rows]
