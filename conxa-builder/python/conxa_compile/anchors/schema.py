"""Normalize anchors to the canonical ``{element, relation}`` shape."""

from __future__ import annotations

from typing import Any

_ALLOWED_RELATIONS = frozenset({"target", "inside", "above", "below", "near"})


def normalize_anchor(raw: Any, *, default_relation: str = "near") -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None

    relation = str(raw.get("relation") or "").strip().lower()
    element = str(raw.get("element") or "").strip()
    if element:
        return {
            "element": element,
            "relation": relation if relation in _ALLOWED_RELATIONS else default_relation,
        }

    legacy_kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
    legacy_value = str(raw.get("value") or raw.get("text") or "").strip()
    if not legacy_value:
        return None
    return {
        "element": legacy_value,
        "relation": legacy_kind if legacy_kind in _ALLOWED_RELATIONS else default_relation,
    }


def normalize_anchor_list(raw: Any, *, default_relation: str = "near") -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw or []:
        anchor = normalize_anchor(item, default_relation=default_relation)
        if not anchor:
            continue
        key = (anchor["element"].strip().lower(), anchor["relation"])
        if key in seen:
            continue
        seen.add(key)
        out.append(anchor)
    return out
