"""Execution lifecycle API: status, pause, resume, cancel, trace, drift check."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.execution.lifecycle import (
    ExecState,
    create_execution,
    get_execution,
    list_executions,
    transition,
)
from app.execution.checkpoint import read_checkpoint
from app.execution.trace import read_trace, aggregate_trace
from app.storage.json_store import read_skill

router = APIRouter(prefix="/executions", tags=["executions"])


# ─── Execution status ─────────────────────────────────────────────────────────

@router.get("")
def list_executions_api(limit: int = 50) -> dict[str, Any]:
    return {"executions": list_executions(limit=limit)}


@router.get("/{execution_id}")
def get_execution_api(execution_id: str) -> dict[str, Any]:
    record = get_execution(execution_id)
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")
    cp = read_checkpoint(execution_id)
    return {"execution": record, "checkpoint": cp}


# ─── Lifecycle controls ───────────────────────────────────────────────────────

class PauseBody(BaseModel):
    pass


@router.post("/{execution_id}/pause")
def pause_execution(execution_id: str) -> dict[str, Any]:
    """Signal the running execution to pause at the next step boundary."""
    record = get_execution(execution_id)
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")
    if record["state"] not in {ExecState.RUNNING.value, ExecState.RESUMING.value}:
        raise HTTPException(status_code=409, detail=f"Cannot pause: execution is {record['state']}")
    try:
        updated = transition(execution_id, ExecState.PAUSED)
        # Write pause signal to control file so runtime picks it up
        _write_ctrl(execution_id, "pause")
        return {"execution": updated, "message": "Pause signal sent. Execution will stop at next step boundary."}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{execution_id}/resume")
def resume_execution(execution_id: str) -> dict[str, Any]:
    """Resume a paused execution from its last checkpoint."""
    record = get_execution(execution_id)
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")
    if record["state"] != ExecState.PAUSED.value:
        raise HTTPException(status_code=409, detail=f"Cannot resume: execution is {record['state']}")
    try:
        updated = transition(execution_id, ExecState.RESUMING)
        _clear_ctrl(execution_id)
        cp = read_checkpoint(execution_id)
        resume_from = cp["step_index"] if cp else 0
        return {
            "execution": updated,
            "resume_from_step": resume_from,
            "message": f"Resume signal sent. Will continue from step {resume_from}.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{execution_id}/cancel")
def cancel_execution(execution_id: str) -> dict[str, Any]:
    """Cancel a running or paused execution."""
    record = get_execution(execution_id)
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found")
    if record["state"] in {ExecState.COMPLETED.value, ExecState.FAILED.value, ExecState.CANCELLED.value}:
        raise HTTPException(status_code=409, detail=f"Execution already {record['state']}")
    try:
        _clear_ctrl(execution_id)
        updated = transition(execution_id, ExecState.CANCELLED, error="Cancelled by user")
        return {"execution": updated}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ─── Trace / observability ────────────────────────────────────────────────────

@router.get("/{execution_id}/trace")
def get_trace(execution_id: str) -> dict[str, Any]:
    """Return full step-level trace for post-mortem analysis."""
    records = read_trace(execution_id)
    if not records:
        return {"execution_id": execution_id, "steps": [], "aggregate": None}
    agg = aggregate_trace(execution_id)
    return {"execution_id": execution_id, "steps": records, "aggregate": agg}


# ─── Drift check (pre-execution) ─────────────────────────────────────────────
# Note: Drift detection requires a live browser — it is done synchronously
# with Playwright. This endpoint returns what the compiler stored; the actual
# live check is triggered by the caller passing an active Playwright page.
# For the MCP/CLI path, drift is checked inside execute_plan before step 1.

@router.get("/drift-check/{skill_id}")
def drift_check_info(skill_id: str) -> dict[str, Any]:
    """Return the stored structural fingerprint for a skill (for manual inspection)."""
    pkg = read_skill(skill_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="Skill not found")
    fp = (pkg.get("meta") or {}).get("structural_fingerprint") or {}
    return {
        "skill_id": skill_id,
        "structural_fingerprint": fp,
        "landmark_count": fp.get("landmark_count", 0),
        "message": "Use the /drift endpoint with a live browser for runtime drift detection.",
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

import json
from pathlib import Path
from app.config import settings

_CTRL_DIR = settings.data_dir / "executions"


def _write_ctrl(execution_id: str, action: str) -> None:
    from datetime import datetime, timezone
    d = _CTRL_DIR / execution_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "ctrl.json").write_text(json.dumps({
        "action": action,
        "ts": datetime.now(timezone.utc).isoformat(),
    }))


def _clear_ctrl(execution_id: str) -> None:
    try:
        (_CTRL_DIR / execution_id / "ctrl.json").unlink(missing_ok=True)
    except Exception:
        pass
