"""Garbage collection for DOM/a11y snapshot blobs.

Deletes old session blobs to prevent unbounded disk growth.
Intended to run as a daily background job.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from conxa_core.config import settings

_logger = logging.getLogger(__name__)


def cleanup_old_snapshots(retention_days: int | None = None) -> dict[str, int]:
    """Delete snapshot blobs for sessions older than retention_days.

    Returns stats: {deleted_sessions, deleted_files, error_count}.
    """
    if retention_days is None:
        retention_days = settings.snapshot_retention_days

    sessions_dir = settings.data_dir / "sessions"
    if not sessions_dir.is_dir():
        return {"deleted_sessions": 0, "deleted_files": 0, "error_count": 0}

    cutoff_time = time.time() - (retention_days * 86400)
    stats = {"deleted_sessions": 0, "deleted_files": 0, "error_count": 0}

    try:
        for session_dir in sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            try:
                session_mtime = session_dir.stat().st_mtime
                if session_mtime > cutoff_time:
                    continue

                blobs_dir = session_dir / "blobs"
                if blobs_dir.is_dir():
                    for blob_file in blobs_dir.glob("*"):
                        try:
                            blob_file.unlink()
                            stats["deleted_files"] += 1
                        except OSError:
                            stats["error_count"] += 1

                stats["deleted_sessions"] += 1
            except OSError:
                stats["error_count"] += 1
    except OSError:
        stats["error_count"] += 1

    if stats["deleted_files"] > 0 or stats["deleted_sessions"] > 0:
        _logger.info(
            "Snapshot GC: deleted %d files from %d sessions (errors: %d)",
            stats["deleted_files"],
            stats["deleted_sessions"],
            stats["error_count"],
        )

    return stats
