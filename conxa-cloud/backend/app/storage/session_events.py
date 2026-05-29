"""Load recorded events from disk (session may already be stopped)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings


def session_events_path(session_id: str) -> Path:
    return settings.data_dir / "sessions" / session_id / "events.jsonl"


def read_session_events(session_id: str) -> list[dict[str, Any]]:
    path = session_events_path(session_id)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out
