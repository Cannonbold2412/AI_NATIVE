"""Tests for execution lifecycle state machine and checkpoint."""

from __future__ import annotations

import pytest

from app.execution.lifecycle import (
    ExecState,
    create_execution,
    get_execution,
    transition,
    update_progress,
)
from app.execution.checkpoint import (
    clear_checkpoint,
    read_checkpoint,
    resume_from,
    write_checkpoint,
)


# ─── Lifecycle state machine ──────────────────────────────────────────────────

@pytest.fixture
def execution(tmp_path, monkeypatch):
    """Create an execution with data_dir pointing to tmp_path."""
    from app.execution import lifecycle as lc
    monkeypatch.setattr(lc, "_EXEC_DIR", tmp_path / "executions")
    return create_execution("skill_test", {"email": "a@b.com"})


def test_create_execution_is_idle(execution):
    assert execution["state"] == ExecState.IDLE.value
    assert execution["execution_id"]
    assert execution["skill_id"] == "skill_test"


def test_get_execution_round_trip(tmp_path, monkeypatch):
    from app.execution import lifecycle as lc
    monkeypatch.setattr(lc, "_EXEC_DIR", tmp_path / "executions")
    rec = create_execution("skill_x", {})
    eid = rec["execution_id"]
    fetched = get_execution(eid)
    assert fetched["execution_id"] == eid
    assert fetched["state"] == ExecState.IDLE.value


def test_valid_transitions(tmp_path, monkeypatch):
    from app.execution import lifecycle as lc
    monkeypatch.setattr(lc, "_EXEC_DIR", tmp_path / "executions")
    rec = create_execution("skill_y", {})
    eid = rec["execution_id"]
    r = transition(eid, ExecState.STARTING)
    assert r["state"] == ExecState.STARTING.value
    r = transition(eid, ExecState.RUNNING)
    assert r["state"] == ExecState.RUNNING.value
    r = transition(eid, ExecState.PAUSED)
    assert r["state"] == ExecState.PAUSED.value
    r = transition(eid, ExecState.RESUMING)
    assert r["state"] == ExecState.RESUMING.value
    r = transition(eid, ExecState.RUNNING)
    assert r["state"] == ExecState.RUNNING.value
    r = transition(eid, ExecState.COMPLETED)
    assert r["state"] == ExecState.COMPLETED.value


def test_invalid_transition_raises(tmp_path, monkeypatch):
    from app.execution import lifecycle as lc
    monkeypatch.setattr(lc, "_EXEC_DIR", tmp_path / "executions")
    rec = create_execution("skill_z", {})
    eid = rec["execution_id"]
    # Cannot go from IDLE directly to RUNNING
    with pytest.raises(ValueError, match="Cannot transition"):
        transition(eid, ExecState.RUNNING)


def test_completed_is_terminal(tmp_path, monkeypatch):
    from app.execution import lifecycle as lc
    monkeypatch.setattr(lc, "_EXEC_DIR", tmp_path / "executions")
    rec = create_execution("skill_t", {})
    eid = rec["execution_id"]
    transition(eid, ExecState.STARTING)
    transition(eid, ExecState.RUNNING)
    transition(eid, ExecState.COMPLETED)
    with pytest.raises(ValueError):
        transition(eid, ExecState.RUNNING)


def test_update_progress(tmp_path, monkeypatch):
    from app.execution import lifecycle as lc
    monkeypatch.setattr(lc, "_EXEC_DIR", tmp_path / "executions")
    rec = create_execution("skill_p", {})
    eid = rec["execution_id"]
    update_progress(eid, current_step=3, total_steps=10)
    fetched = get_execution(eid)
    assert fetched["current_step"] == 3
    assert fetched["total_steps"] == 10


# ─── Checkpoint ──────────────────────────────────────────────────────────────

@pytest.fixture
def cp_exec_id(tmp_path, monkeypatch):
    from app.execution import checkpoint as cp
    monkeypatch.setattr(cp, "_EXEC_DIR", tmp_path / "executions")
    return "test-exec-123"


def test_write_and_read_checkpoint(tmp_path, monkeypatch, cp_exec_id):
    from app.execution import checkpoint as cp
    monkeypatch.setattr(cp, "_EXEC_DIR", tmp_path / "executions")
    write_checkpoint(cp_exec_id, step_index=5, step_total=12, page_url="https://example.com/step5")
    data = read_checkpoint(cp_exec_id)
    assert data is not None
    assert data["step_index"] == 5
    assert data["step_total"] == 12
    assert data["page_url"] == "https://example.com/step5"


def test_resume_from_returns_step_index(tmp_path, monkeypatch, cp_exec_id):
    from app.execution import checkpoint as cp
    monkeypatch.setattr(cp, "_EXEC_DIR", tmp_path / "executions")
    write_checkpoint(cp_exec_id, step_index=7, step_total=10)
    assert resume_from(cp_exec_id) == 7


def test_resume_from_returns_zero_without_checkpoint(tmp_path, monkeypatch):
    from app.execution import checkpoint as cp
    monkeypatch.setattr(cp, "_EXEC_DIR", tmp_path / "executions")
    assert resume_from("nonexistent-exec") == 0


def test_clear_checkpoint(tmp_path, monkeypatch, cp_exec_id):
    from app.execution import checkpoint as cp
    monkeypatch.setattr(cp, "_EXEC_DIR", tmp_path / "executions")
    write_checkpoint(cp_exec_id, step_index=3, step_total=8)
    clear_checkpoint(cp_exec_id)
    assert read_checkpoint(cp_exec_id) is None
    assert resume_from(cp_exec_id) == 0
