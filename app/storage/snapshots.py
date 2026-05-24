"""Content-addressable storage for recorded DOM + a11y snapshots.

Layout:
  data_dir/sessions/{session_id}/blobs/{sha256}.html.gz   — full HTML, gzipped
  data_dir/sessions/{session_id}/blobs/{sha256}.a11y.json — Playwright accessibility tree

Dedup: identical pages share the same blob (hash collision = same content).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from app.config import settings


def _session_root(session_id: str) -> Path:
    return settings.data_dir / "sessions" / session_id


def blobs_dir(session_id: str) -> Path:
    p = _session_root(session_id) / "blobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def dom_hash(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()


def save_dom_snapshot(session_id: str, html: str) -> tuple[str, Path]:
    """Gzip + write HTML to {hash}.html.gz. Skips if blob already exists (dedup).

    Returns (sha256_hash, relative_path).
    """
    h = dom_hash(html)
    dest = blobs_dir(session_id) / f"{h}.html.gz"
    if not dest.exists():
        try:
            dest.write_bytes(gzip.compress(html.encode("utf-8", errors="ignore")))
        except OSError:
            pass
    return h, dest


def save_a11y_snapshot(session_id: str, snapshot: dict[str, Any] | None, dom_hash_value: str) -> Path | None:
    """Write Playwright accessibility snapshot keyed to the same dom_hash.

    Co-locating the a11y tree under the same hash lets the compiler load both
    blobs together via snapshot_ref.
    """
    if snapshot is None:
        return None
    dest = blobs_dir(session_id) / f"{dom_hash_value}.a11y.json"
    if not dest.exists():
        try:
            dest.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            return None
    return dest


def read_dom_snapshot(session_id: str, dom_hash_value: str) -> str | None:
    """Read + decompress the HTML blob for a given hash."""
    p = blobs_dir(session_id) / f"{dom_hash_value}.html.gz"
    if not p.is_file():
        return None
    try:
        return gzip.decompress(p.read_bytes()).decode("utf-8", errors="ignore")
    except (OSError, gzip.BadGzipFile, UnicodeDecodeError):
        return None


def read_a11y_snapshot(session_id: str, dom_hash_value: str) -> dict[str, Any] | None:
    p = blobs_dir(session_id) / f"{dom_hash_value}.a11y.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def relative_blob_path(session_id: str, dom_hash_value: str, suffix: str) -> str:
    """Path relative to data_dir for storage in event metadata."""
    return f"sessions/{session_id}/blobs/{dom_hash_value}.{suffix}"


def new_snapshot_ref() -> str:
    return uuid.uuid4().hex


def dedup_stats(session_id: str) -> dict[str, int]:
    """Quick stats for the metrics dashboard."""
    base = blobs_dir(session_id)
    dom_count = 0
    a11y_count = 0
    total_bytes = 0
    for path in base.glob("*"):
        if not path.is_file():
            continue
        if path.name.endswith(".html.gz"):
            dom_count += 1
        elif path.name.endswith(".a11y.json"):
            a11y_count += 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
    return {
        "unique_dom_snapshots": dom_count,
        "unique_a11y_snapshots": a11y_count,
        "total_blob_bytes": total_bytes,
    }
