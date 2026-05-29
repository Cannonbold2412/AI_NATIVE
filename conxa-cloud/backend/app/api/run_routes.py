"""Tracker ingest and timeline API for plugin run events.

Three event types only: step_failure | recovery_attempt | run_outcome.
Storage: append-only JSONL on disk, one file per plugin.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from conxa_core.config import settings
from conxa_core.db import db_append, db_get, db_list_kv

router = APIRouter(prefix="/runs", tags=["runs"])


def _runs_dir() -> Path:
    d = settings.data_dir / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plugin_log_path(plugin_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in plugin_id)[:80]
    return _runs_dir() / f"{safe}.jsonl"


_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _get_file_lock(key: str) -> threading.Lock:
    with _file_locks_guard:
        if key not in _file_locks:
            _file_locks[key] = threading.Lock()
        return _file_locks[key]


def _append_events(plugin_id: str, events: list[dict[str, Any]]) -> None:
    db_append("runs", plugin_id, events)
    # Also append to file for local dev
    path = _plugin_log_path(plugin_id)
    try:
        lines = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = _get_file_lock(str(path))
        with lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(lines)
    except OSError:
        pass


def _read_events(plugin_id: str, since: float = 0.0) -> list[dict[str, Any]]:
    db_items = db_get("runs", plugin_id)
    if db_items is not None:
        events = db_items if isinstance(db_items, list) else []
    else:
        # File fallback
        path = _plugin_log_path(plugin_id)
        if not path.is_file():
            return []
        events = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if isinstance(e, dict):
                        events.append(e)
                except (json.JSONDecodeError, ValueError):
                    continue
    if since:
        cutoff = _epoch_to_iso(since)
        events = [e for e in events if isinstance(e, dict) and not (e.get("ts") or e.get("timestamp") or "") < cutoff]
    return events


def _epoch_to_iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _group_by_run(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for e in events:
        rid = str(e.get("run_id") or "unknown")
        if rid not in runs:
            runs[rid] = {
                "run_id": rid,
                "plugin_id": e.get("plugin_id", ""),
                "skill_slug": e.get("skill_slug", ""),
                "events": [],
                "outcome": None,
            }
        runs[rid]["events"].append(e)
        if e.get("event") == "run_outcome":
            data = e.get("data") or {}
            runs[rid]["outcome"] = {
                "status": data.get("status", "unknown"),
                "duration_ms": data.get("duration_ms", 0),
                "total_steps": data.get("total_steps", 0),
                "recovered_steps": data.get("recovered_steps", 0),
                "failed_step_id": data.get("failed_step_id"),
            }
    return list(runs.values())


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RunEvent(BaseModel):
    event: str = Field(..., description="step_failure | recovery_attempt | run_outcome")
    run_id: str = ""
    plugin_id: str = ""
    skill_slug: str = ""
    step_id: Any = None
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = ""


class IngestBody(BaseModel):
    events: list[RunEvent] | None = None
    # Single-event shorthand
    event: str = ""
    run_id: str = ""
    plugin_id: str = ""
    skill_slug: str = ""
    step_id: Any = None
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/events")
def post_run_events(body: IngestBody) -> dict[str, Any]:
    """Accept a single event or batch; append to per-plugin JSONL log."""
    if body.events:
        raw_events = [e.model_dump(mode="json") for e in body.events]
    else:
        # Single-event shorthand
        if not body.event:
            raise HTTPException(status_code=400, detail="Missing 'event' field.")
        raw_events = [body.model_dump(mode="json", exclude={"events"})]

    # Stamp each event with current time if missing
    now_iso = _epoch_to_iso(time.time())
    for e in raw_events:
        if not e.get("ts"):
            e["ts"] = now_iso

    # Group by plugin_id for storage
    by_plugin: dict[str, list[dict[str, Any]]] = {}
    for e in raw_events:
        pid = str(e.get("plugin_id") or "unknown")
        by_plugin.setdefault(pid, []).append(e)

    for pid, events in by_plugin.items():
        _append_events(pid, events)

    return {"accepted": len(raw_events)}


@router.get("")
def get_runs(plugin_id: str = "", since: float = 0.0) -> dict[str, Any]:
    """Return timeline grouped by run_id. Filter by plugin_id and/or since (epoch)."""
    if plugin_id:
        events = _read_events(plugin_id, since=since)
        runs = _group_by_run(events)
    else:
        all_events: list[dict[str, Any]] = []
        db_pairs = db_list_kv("runs")
        if db_pairs:
            for pid, items in db_pairs:
                all_events.extend(_read_events(pid, since=since))
        else:
            for log_path in sorted(_runs_dir().glob("*.jsonl")):
                all_events.extend(_read_events(log_path.stem, since=since))
        runs = _group_by_run(all_events)
    return {"runs": runs}


@router.get("/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Return all events for a single run_id."""
    all_events: list[dict[str, Any]] = []
    db_pairs = db_list_kv("runs")
    if db_pairs:
        for pid, _ in db_pairs:
            all_events.extend(_read_events(pid))
    else:
        for log_path in sorted(_runs_dir().glob("*.jsonl")):
            all_events.extend(_read_events(log_path.stem))

    run_events = [e for e in all_events if str(e.get("run_id") or "") == run_id]
    if not run_events:
        raise HTTPException(status_code=404, detail="Run not found.")
    grouped = _group_by_run(run_events)
    return {"run": grouped[0] if grouped else {"run_id": run_id, "events": run_events}}
