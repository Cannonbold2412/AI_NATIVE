"""Attach deterministic enrichment fields (no ML)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_json_subset(ev: dict[str, Any]) -> dict[str, Any]:
    """Subset used only for hashing (ignore volatile timestamps)."""
    return {
        "action": ev.get("action", {}).get("action"),
        "target": ev.get("target"),
        "selectors": ev.get("selectors"),
        "semantic": ev.get("semantic"),
        "page": ev.get("page"),
        "state_after": ev.get("state_change", {}).get("after"),
    }


def fingerprint_event(ev: dict[str, Any]) -> str:
    payload = json.dumps(_stable_json_subset(ev), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def enrich_event(ev: dict[str, Any], *, pipeline_version: str, ordinal: int) -> dict[str, Any]:
    ex = dict(ev.get("extras") or {})
    ex["pipeline_version"] = pipeline_version
    ex["ordinal"] = ordinal
    ex["content_fp"] = fingerprint_event(ev)
    out = dict(ev)
    out["extras"] = ex
    return out
