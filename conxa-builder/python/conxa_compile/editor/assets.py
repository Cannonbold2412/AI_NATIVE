"""Resolve screenshot paths under data_dir with traversal protection."""

from __future__ import annotations

import base64
import mimetypes
import urllib.parse
from pathlib import Path

from conxa_core.config import settings


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


def _asset_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def asset_url(relative_path: str, *, asset_base_url: str, skill_id: str) -> str:
    """Return a renderer-loadable URL for a persisted visual asset."""
    if asset_base_url.strip().lower().startswith("file://"):
        path = resolve_skill_asset(relative_path)
        if path.is_file():
            return _asset_data_url(path)
        return path.as_uri()
    q = urllib.parse.urlencode({"path": relative_path})
    base = asset_base_url.rstrip("/")
    sid_q = urllib.parse.quote(skill_id, safe="")
    return f"{base}/skills/{sid_q}/assets?{q}"
