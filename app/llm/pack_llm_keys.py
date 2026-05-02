"""Round-robin rotation for SKILL_PACK_LLM_API_KEYS (comma-separated list)."""

from __future__ import annotations

import threading

from app.config import settings

_PACK_KEY_IDX = 0
_PACK_KEY_LOCK = threading.Lock()


def configured_pack_keys() -> list[str]:
    csv_keys = [item.strip() for item in str(settings.pack_llm_api_keys or "").split(",") if item.strip()]
    if csv_keys:
        return csv_keys
    single = str(settings.pack_llm_api_key or "").strip()
    return [single] if single else []


def next_pack_api_key() -> tuple[str | None, int, int]:
    """Return the next bearer token and metadata (1-based slot index, pool size)."""
    keys = configured_pack_keys()
    if not keys:
        return None, 0, 0
    global _PACK_KEY_IDX
    with _PACK_KEY_LOCK:
        i = _PACK_KEY_IDX % len(keys)
        _PACK_KEY_IDX += 1
    return keys[i], i + 1, len(keys)
