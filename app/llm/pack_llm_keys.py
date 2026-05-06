"""Round-robin rotation for SKILL_PACK_LLM_API_KEYS (comma-separated list)."""

from __future__ import annotations

import threading

from app.config import settings
from app.llm.pack_llm_config import selected_pack_provider

_PACK_KEY_IDX = 0
_PACK_KEY_LOCK = threading.Lock()


def configured_pack_keys() -> list[str]:
    provider = selected_pack_provider()
    candidates: list[str] = []
    if provider == "gemini":
        candidates.extend([settings.pack_llm_gemini_api_keys, settings.pack_llm_gemini_api_key])
    elif provider == "nvidia":
        candidates.extend(
            [
                settings.pack_llm_nvidia_api_keys,
                settings.pack_llm_nvidia_api_key,
                settings.pack_llm_api_keys,
                settings.pack_llm_api_key,
                settings.llm_api_keys,
                settings.llm_api_key,
            ]
        )
    else:
        candidates.extend([settings.pack_llm_api_keys, settings.pack_llm_api_key])

    for value in candidates:
        keys = [item.strip() for item in str(value or "").split(",") if item.strip()]
        if keys:
            return keys
    return []


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
