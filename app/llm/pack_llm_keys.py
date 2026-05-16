"""API key management for Skill Pack Builder."""

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


def configured_pack_keys() -> list[str]:
    """Get comma-separated API keys for Skill Pack Builder."""
    return _split_keys(settings.llm_pack_api_key)


def next_pack_api_key() -> tuple[str | None, int, int]:
    """Return the first available bearer token and metadata (1-based slot index, pool size)."""
    keys = configured_pack_keys()
    if not keys:
        return None, 0, 0
    return keys[0], 1, len(keys)
