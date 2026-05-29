"""LLM-native selector generation with objective confidence computation.

Generates high-confidence selectors using 3 objective signals:
1. DOM uniqueness (0.4) — how many elements match the selector in recorded DOM
2. Self-consistency (0.3) — how many of N LLM calls agree on the same selector
3. Visual verification (0.3) — [future] cross-frame confirmation via vision

Confidence = sum of signals, capped at 1.0
"""

from __future__ import annotations

import json
import re
from typing import Any

from conxa_compile.llm.openapi_client import generate_selector_candidates


def _count_selector_matches(selector: str, dom_snapshot: dict[str, Any]) -> int:
    """Count elements matching selector in recorded DOM.

    This is a simplified matcher that handles common selector patterns.
    Returns exact match count if possible, else 1 (unknown/assume unique).
    """
    selector = selector.strip()
    if not selector:
        return 0

    # data-testid selector
    m = re.match(r'\[data-testid=["\']?([^"\']+)["\']?\]', selector)
    if m:
        testid = m.group(1)
        count = _count_dom_elements_with_attr(dom_snapshot, "data-testid", testid)
        return count

    # aria-label selector
    m = re.match(r'\[aria-label=["\']?([^"\']+)["\']?\]', selector)
    if m:
        label = m.group(1)
        count = _count_dom_elements_with_attr(dom_snapshot, "aria-label", label)
        return count

    # text content selector
    m = re.match(r'text=["\']?([^"\']+)["\']?', selector)
    if m:
        text = m.group(1)
        count = _count_dom_elements_with_text(dom_snapshot, text)
        return count

    # Simple tag selector
    m = re.match(r'^([a-z]+)$', selector.lower())
    if m:
        tag = m.group(1)
        count = _count_dom_elements_by_tag(dom_snapshot, tag)
        return count

    # For complex selectors, return 1 (unknown, assume unique)
    return 1


def _count_dom_elements_by_tag(dom: dict[str, Any], tag: str) -> int:
    """Recursively count elements with given tag in DOM."""
    count = 0
    if isinstance(dom, dict):
        if str(dom.get("tag") or "").lower() == tag.lower():
            count = 1
        for child in dom.get("children") or []:
            count += _count_dom_elements_by_tag(child, tag)
    return count


def _count_dom_elements_with_attr(dom: dict[str, Any], attr: str, value: str) -> int:
    """Recursively count elements with given attribute value in DOM."""
    count = 0
    if isinstance(dom, dict):
        attrs = dom.get("attributes") or {}
        if isinstance(attrs, dict) and str(attrs.get(attr) or "") == value:
            count = 1
        for child in dom.get("children") or []:
            count += _count_dom_elements_with_attr(child, attr, value)
    return count


def _count_dom_elements_with_text(dom: dict[str, Any], text: str) -> int:
    """Recursively count elements with inner text matching in DOM."""
    count = 0
    if isinstance(dom, dict):
        inner = str(dom.get("inner_text") or "").strip()
        if inner.lower() == text.lower() or text.lower() in inner.lower():
            count = 1
        for child in dom.get("children") or []:
            count += _count_dom_elements_with_text(child, text)
    return count


def compute_dom_uniqueness_signal(selector: str, dom_snapshot: dict[str, Any] | None) -> float:
    """Compute DOM uniqueness confidence signal (0.4 max).

    Returns:
    - 0.40 if selector matches exactly 1 element
    - 0.15 if matches 2-3 elements (usable but ambiguous)
    - 0.05 if matches 4+ elements (very ambiguous)
    - 0.00 if matches 0 elements (broken)
    """
    if not dom_snapshot:
        return 0.0

    count = _count_selector_matches(selector, dom_snapshot)
    if count == 1:
        return 0.40
    elif count in {2, 3}:
        return 0.15
    elif count > 3:
        return 0.05
    else:
        return 0.0


def compute_self_consistency_signal(selectors: list[str]) -> float:
    """Compute self-consistency confidence signal (0.3 max).

    Pass the result of N LLM calls (typically 5). Groups by string equality
    and returns confidence based on agreement rate.

    Returns:
    - 0.30 if 5/5 agree
    - 0.22 if 4/5 agree
    - 0.15 if 3/5 agree
    - 0.00 if ≤2/5 agree (too noisy)
    """
    if not selectors:
        return 0.0

    # Count unique selectors (normalized: strip whitespace, lowercase attr names)
    normalized = [_normalize_selector(s) for s in selectors]
    from collections import Counter
    counts = Counter(normalized)

    total = len(normalized)
    agreement = max(counts.values()) if counts else 0

    if agreement == total:  # All agree
        return 0.30
    elif agreement / total >= 0.8:  # 4/5
        return 0.22
    elif agreement / total >= 0.6:  # 3/5
        return 0.15
    else:
        return 0.0


def _normalize_selector(selector: str) -> str:
    """Normalize selector for comparison (strip whitespace, lowercase attrs)."""
    s = selector.strip()
    # Normalize aria-label="X" and aria-label='X' to the same form
    s = re.sub(r"aria-label=['\"]", 'aria-label="', s)
    s = re.sub(r"data-testid=['\"]", 'data-testid="', s)
    return s


def generate_selector_with_objective_confidence(
    *,
    dom_snippet: str,
    element_bbox: dict[str, int],
    element_ancestors: list[dict[str, Any]],
    surrounding_text: str,
    action_type: str,
    target_dom: dict[str, Any] | None = None,
    a11y_node: dict[str, Any] | None = None,
    full_page_html: str | None = None,
    candidates_wanted: int = 1,
    num_samples: int = 5,
    error_detail: list[str] | None = None,
) -> tuple[str, float, dict[str, float], str]:
    """Generate a high-confidence selector using LLM + objective signals.

    Args:
        dom_snippet: Isolated DOM subtree for the element
        element_bbox: Bounding box of the element
        element_ancestors: List of ancestor elements
        surrounding_text: Context text around element
        action_type: Type of action (click, type, etc.)
        target_dom: Full recorded DOM for uniqueness checking
        candidates_wanted: Number of candidates to request from first LLM call
        num_samples: Number of LLM calls for self-consistency check (typically 5)
        error_detail: List to append debug info to

    Returns:
        (selector, confidence, confidence_breakdown, rationale)
        - selector: Best selector string (empty if confidence < 0.50)
        - confidence: Total confidence (0.0 to 1.0)
        - confidence_breakdown: {dom_uniqueness, self_consistency, visual_verification}
        - rationale: Human-readable explanation
    """
    # Call LLM to generate candidate selectors
    candidates = generate_selector_candidates(
        dom_snippet=dom_snippet,
        element_bbox=element_bbox,
        element_ancestors=element_ancestors,
        surrounding_text=surrounding_text,
        action_type=action_type,
        target_dom=target_dom,
        a11y_node=a11y_node,
        candidates_wanted=candidates_wanted,
        error_detail=error_detail,
    )

    if not candidates:
        return "", 0.0, {
            "dom_uniqueness": 0.0,
            "self_consistency": 0.0,
            "visual_verification": 0.0,
        }, "LLM failed to generate candidates"

    # Get the best candidate
    best_candidate = candidates[0]
    primary_selector = best_candidate.selector.strip()

    if not primary_selector:
        return "", 0.0, {
            "dom_uniqueness": 0.0,
            "self_consistency": 0.0,
            "visual_verification": 0.0,
        }, "LLM returned empty selector"

    # Signal 1: DOM uniqueness — use full-page HTML when available for accurate match counting.
    if full_page_html:
        from conxa_compile.compiler.llm_selector_generator import validate_selector  # noqa: PLC0415
        _, match_count = validate_selector(primary_selector, full_page_html)
        if match_count < 0:    dom_signal = 0.20   # parse failed → conservative
        elif match_count == 1: dom_signal = 0.40
        elif match_count <= 3: dom_signal = 0.15
        elif match_count > 3:  dom_signal = 0.05
        else:                  dom_signal = 0.0    # 0 matches → broken selector
    else:
        dom_signal = compute_dom_uniqueness_signal(primary_selector, target_dom)

    # Signal 2: Self-consistency — call LLM multiple times and compare results
    consistency_selectors = [primary_selector]
    for _ in range(num_samples - 1):
        other_candidates = generate_selector_candidates(
            dom_snippet=dom_snippet,
            element_bbox=element_bbox,
            element_ancestors=element_ancestors,
            surrounding_text=surrounding_text,
            action_type=action_type,
            target_dom=target_dom,
            a11y_node=a11y_node,
            candidates_wanted=1,
            error_detail=error_detail,
        )
        if other_candidates:
            consistency_selectors.append(other_candidates[0].selector.strip())

    consistency_signal = compute_self_consistency_signal(consistency_selectors)

    # Signal 3: Visual verification (future: implemented later with video frames)
    visual_signal = 0.0  # Placeholder

    # Compute total confidence
    total_confidence = min(1.0, dom_signal + consistency_signal + visual_signal)

    # Build rationale
    breakdown = {
        "dom_uniqueness": round(dom_signal, 2),
        "self_consistency": round(consistency_signal, 2),
        "visual_verification": round(visual_signal, 2),
    }

    rationale_parts = []
    if dom_signal > 0:
        count = _count_selector_matches(primary_selector, target_dom)
        rationale_parts.append(f"DOM uniqueness: matched {count} element(s) → {dom_signal:.2f}")
    else:
        rationale_parts.append("DOM uniqueness: selector did not match any elements → 0.0")

    if consistency_signal > 0:
        agreement_rate = consistency_selectors.count(primary_selector) / len(consistency_selectors)
        rationale_parts.append(
            f"Self-consistency: {int(agreement_rate * len(consistency_selectors))}/{len(consistency_selectors)} "
            f"LLM calls agreed → {consistency_signal:.2f}"
        )
    else:
        rationale_parts.append("Self-consistency: LLM calls diverged → 0.0")

    rationale = "; ".join(rationale_parts)

    if total_confidence < 0.50:
        # Low confidence: don't use this selector
        return "", total_confidence, breakdown, rationale

    return primary_selector, total_confidence, breakdown, rationale
