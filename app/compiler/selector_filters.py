"""Deterministic selector quality gates (shared by ranking + stable selector build)."""

from __future__ import annotations

import re
from typing import Any


def is_dynamic_id(selector: str) -> bool:
    if not selector.startswith("#"):
        return False
    value = selector[1:]
    if not value:
        return True
    if value.startswith("_r_"):
        return True
    if re.search(r"[:][a-z0-9]{6,}", value, re.I):
        return True
    if re.search(r"-[a-f0-9]{8,}\b", value, re.I):
        return True
    return bool(re.search(r"\d", value) and re.search(r"[_\-]", value))


def is_unstable_generated_css_fragment(selector: str) -> bool:
    """Heuristic for hashed / scoped class segments in attribute selectors (not full parser)."""
    s = selector.strip()
    if len(s) < 24:
        return False
    if re.search(r"\[[^\]]{80,}\]", s):
        return True
    if s.count("[class") >= 2 and re.search(r"[a-f0-9]{6,}", s, re.I):
        return True
    return False


_INVALID_ARIA_ROLE_TOKENS = frozenset(
    {
        "path",
        "svg",
        "g",
        "div",
        "span",
        "none",
        "presentation",
        "input",
    }
)


def is_invalid_aria_semantic_role(selector: str) -> bool:
    """Reject selectors that claim impossible / non-interactive ARIA roles."""
    m = re.search(r'\[role=["\']([^"\']+)["\']', selector, re.I)
    if not m:
        return False
    r = str(m.group(1) or "").strip().lower()
    return r in _INVALID_ARIA_ROLE_TOKENS


def is_valid_selector(selector: str) -> bool:
    if not selector:
        return False
    normalized = selector.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in {'[role="input"]', "[role='input']"}:
        return False
    if lowered.startswith("[role=") and "input" in lowered:
        return False
    if is_invalid_aria_semantic_role(normalized):
        return False
    return True


def is_weak_literal_token(selector: str) -> bool:
    """Reject bare words mistaken for selectors (e.g. field name tokens)."""
    s = selector.strip()
    if not s:
        return True
    lowered = s.lower()
    if lowered.startswith(("[", "#", ".", "/", "*", "(")):
        return False
    for prefix in ("input", "button", "textarea", "select", "form", "option", "label", "svg", "path", "a[", "a."):
        if lowered.startswith(prefix):
            return False
    if "text=" in lowered:
        return False
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", s) and len(s) < 48:
        return True
    return False


def is_brittle_deep_chain(selector: str, *, max_xpath_segments: int = 10, max_css_child_depth: int = 6) -> bool:
    """Heuristic: very long positional CSS or XPath trees are fragile."""
    s = selector.strip()
    if not s:
        return False
    if s.startswith("/"):
        parts = [p for p in re.split(r"/+", s) if p and p not in (".",)]
        depth = len(parts)
        return depth > max_xpath_segments
    if ">" in s:
        depth = s.count(">") + 1
        return depth > max_css_child_depth
    if len(s) > 220:
        return True
    return False


def filter_selectors_dict(selectors: dict[str, Any] | None) -> dict[str, Any]:
    """Strip selector channels that fail quality gates before persisting to skill steps."""
    if not isinstance(selectors, dict):
        return {}
    out: dict[str, Any] = dict(selectors)
    for key in ("css", "aria", "text_based", "xpath", "name"):
        raw = out.get(key)
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s or not selector_passes_filters(s):
            out[key] = ""
        else:
            out[key] = s
    return out


def selector_passes_filters(selector: str) -> bool:
    if not is_valid_selector(selector):
        return False
    if is_weak_literal_token(selector):
        return False
    if is_dynamic_id(selector):
        return False
    if is_unstable_generated_css_fragment(selector):
        return False
    if is_brittle_deep_chain(selector):
        return False
    return True


def prefilter_selector_candidate(selector: str) -> bool:
    """Gate before scoring: same as selector_passes_filters (explicit alias for ranking pipelines)."""
    return selector_passes_filters(selector)
