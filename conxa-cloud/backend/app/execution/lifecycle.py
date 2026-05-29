"""Execution lifecycle state machine.

States:
  idle → starting → running → paused → resuming → completed | failed | cancelled

Each execution is identified by execution_id (uuid). State is persisted to
~/.conxa/data/executions/{id}/state.json so it survives process restarts
and is readable by external tools (dashboard, CLI).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.config import settings

_EXEC_DIR = settings.data_dir / "executions"


class ExecState(str, Enum):
    IDLE       = "idle"
    STARTING   = "starting"
    RUNNING    = "running"
    PAUSED     = "paused"
    RESUMING   = "resuming"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


# Valid state transitions
_TRANSITIONS: dict[ExecState, set[ExecState]] = {
    ExecState.IDLE:      {ExecState.STARTING},
    ExecState.STARTING:  {ExecState.RUNNING, ExecState.FAILED, ExecState.CANCELLED},
    ExecState.RUNNING:   {ExecState.PAUSED, ExecState.COMPLETED, ExecState.FAILED, ExecState.CANCELLED},
    ExecState.PAUSED:    {ExecState.RESUMING, ExecState.CANCELLED},
    ExecState.RESUMING:  {ExecState.RUNNING, ExecState.FAILED, ExecState.CANCELLED},
    ExecState.COMPLETED: set(),
    ExecState.FAILED:    set(),
    ExecState.CANCELLED: set(),
}


def _exec_dir(execution_id: str) -> Path:
    return _EXEC_DIR / execution_id


def _state_file(execution_id: str) -> Path:
    return _exec_dir(execution_id) / "state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_execution(
    skill_id: str,
    inputs: dict[str, Any],
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Create a new execution record in IDLE state. Returns the execution dict."""
    eid = execution_id or str(uuid.uuid4())
    d = _exec_dir(eid)
    d.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "execution_id": eid,
        "skill_id": skill_id,
        "inputs": inputs,
        "state": ExecState.IDLE.value,
        "created_at": _now(),
        "updated_at": _now(),
        "current_step": 0,
        "total_steps": 0,
        "error": None,
        "result": None,
    }
    _write(eid, record)
    return record


def get_execution(execution_id: str) -> dict[str, Any] | None:
    f = _state_file(execution_id)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


def transition(execution_id: str, to_state: ExecState, **updates: Any) -> dict[str, Any]:
    """Transition execution to a new state. Raises ValueError on invalid transition."""
    record = get_execution(execution_id)
    if record is None:
        raise ValueError(f"Execution {execution_id} not found")
    current = ExecState(record["state"])
    if to_state not in _TRANSITIONS[current]:
        raise ValueError(f"Cannot transition {current} → {to_state}")
    record["state"] = to_state.value
    record["updated_at"] = _now()
    for k, v in updates.items():
        record[k] = v
    _write(execution_id, record)
    return record


def update_progress(execution_id: str, current_step: int, total_steps: int) -> None:
    record = get_execution(execution_id)
    if record is None:
        return
    record["current_step"] = current_step
    record["total_steps"]  = total_steps
    record["updated_at"]   = _now()
    _write(execution_id, record)


def list_executions(limit: int = 50) -> list[dict[str, Any]]:
    if not _EXEC_DIR.exists():
        return []
    results = []
    for d in sorted(_EXEC_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        rec = get_execution(d.name)
        if rec:
            results.append(rec)
        if len(results) >= limit:
            break
    return results


def _write(execution_id: str, record: dict[str, Any]) -> None:
    f = _state_file(execution_id)
    f.write_text(json.dumps(record, indent=2))
