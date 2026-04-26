"""Resolve screenshot paths under data_dir with traversal protection."""

from __future__ import annotations

from pathlib import Path

from app.config import settings


def resolve_skill_asset(relative_path: str) -> Path:
    """Return absolute path if ``relative_path`` resolves under ``settings.data_dir``."""
    raw = (relative_path or "").strip().replace("\\", "/")
    if not raw or ".." in raw or raw.startswith("/"):
        raise ValueError("invalid_asset_path")
    base = settings.data_dir.resolve()
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("asset_path_outside_data_dir") from exc
    return candidate
