"""API key management for the unified Text LLM endpoint.

The Text LLM endpoint is used for all non-vision compile-time and runtime LLM
calls (structuring, skill.md generation, selector generation, intent inference,
runtime recovery). Supports a comma-separated rotation pool in SKILL_LLM_TEXT_API_KEY.
"""

from __future__ import annotations

from app.config import settings


def _split_keys(value: object) -> list[str]:
    keys: list[str] = []
    for item in str(value or "").split(","):
        key = item.strip().strip('"').strip("'").strip()
        if key.lower().startswith("bearer "):
            key = key[7:].strip()
        if key:
            keys.append(key)
    return keys


def configured_text_keys() -> list[str]:
    return _split_keys(settings.llm_text_api_key)


def next_text_api_key() -> tuple[str | None, int, int]:
    """Return the first available bearer token and metadata (1-based slot index, pool size)."""
    keys = configured_text_keys()
    if not keys:
        return None, 0, 0
    return keys[0], 1, len(keys)
