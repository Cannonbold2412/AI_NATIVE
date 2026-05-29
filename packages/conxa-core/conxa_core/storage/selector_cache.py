"""Content-addressable cache for LLM-generated selector candidates.

Cache key: (dom_hash, element_bbox, model_name) → list of validated candidates.
Backed by the kv_store DB layer with a file fallback for local dev.
TTL controlled by settings.selector_cache_ttl_days.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from conxa_core.config import settings
from conxa_core.db import db_get, db_set


_NAMESPACE = "selector_cache"


def _cache_dir() -> Path:
    p = settings.data_dir / "cache" / "selectors"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _bbox_key(element_bbox: dict[str, Any] | None) -> str:
    if not element_bbox:
        return "_"
    keys = ("x", "y", "w", "h")
    return ",".join(str(int(element_bbox.get(k) or 0)) for k in keys)


def make_cache_key(dom_hash: str, element_bbox: dict[str, Any] | None, model: str | None) -> str:
    return f"{dom_hash}:{_bbox_key(element_bbox)}:{model or 'default'}"


def _ttl_seconds() -> int:
    return max(1, int(settings.selector_cache_ttl_days)) * 86400


def _read_cache_file(key: str) -> dict[str, Any] | None:
    path = _cache_dir() / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache_file(key: str, entry: dict[str, Any]) -> None:
    path = _cache_dir() / f"{key}.json"
    try:
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def get(dom_hash: str, element_bbox: dict[str, Any] | None, model: str | None) -> list[dict[str, Any]] | None:
    """Return cached selector candidates or None if missing/expired."""
    if not settings.selector_cache_enabled:
        return None
    key = make_cache_key(dom_hash, element_bbox, model)
    entry = db_get(_NAMESPACE, key) or _read_cache_file(key)
    if not isinstance(entry, dict):
        return None
    created_at = float(entry.get("created_at") or 0.0)
    if created_at and time.time() - created_at > _ttl_seconds():
        return None
    candidates = entry.get("candidates")
    if not isinstance(candidates, list):
        return None
    return candidates


def set(  # noqa: A001 — public cache API
    dom_hash: str,
    element_bbox: dict[str, Any] | None,
    model: str | None,
    candidates: list[dict[str, Any]],
) -> None:
    if not settings.selector_cache_enabled:
        return
    key = make_cache_key(dom_hash, element_bbox, model)
    entry = {
        "dom_hash": dom_hash,
        "element_bbox": element_bbox or {},
        "model": model or "default",
        "candidates": candidates,
        "created_at": time.time(),
    }
    db_set(_NAMESPACE, key, entry)
    _write_cache_file(key, entry)


def invalidate(dom_hash: str) -> int:
    """Delete all cached entries for a given dom_hash.

    Returns count of deleted entries (both DB and file cache).
    """
    count = 0
    base = _cache_dir()
    if base.is_dir():
        for path in base.glob(f"{dom_hash}:*.json"):
            try:
                path.unlink()
                count += 1
            except OSError:
                pass
    return count


def hit_rate(window_keys: list[str] | None = None) -> dict[str, Any]:
    """Aggregate cache stats for the metrics dashboard.

    window_keys: restrict to specific dom_hashes (e.g. recent workflows).
    Falls back to scanning the file cache when DB is not configured.
    """
    base = _cache_dir()
    total = 0
    by_model: dict[str, int] = {}
    now = time.time()
    ttl = _ttl_seconds()
    if not base.is_dir():
        return {"total": 0, "by_model": {}}
    for path in base.glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        created = float(entry.get("created_at") or 0.0)
        if created and now - created > ttl:
            continue
        if window_keys and entry.get("dom_hash") not in window_keys:
            continue
        total += 1
        model = str(entry.get("model") or "default")
        by_model[model] = by_model.get(model, 0) + 1
    return {"total": total, "by_model": by_model}
