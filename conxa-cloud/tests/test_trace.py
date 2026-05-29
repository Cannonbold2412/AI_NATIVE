"""Tests for execution trace observability."""

from __future__ import annotations

import pytest

from app.execution.trace import (
    aggregate_trace,
    append_step_trace,
    read_trace,
    step_span,
)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def exec_id(tmp_path, monkeypatch):
    from app.execution import trace as t
    monkeypatch.setattr(t, "_EXEC_DIR", tmp_path / "executions")
    return "trace-test-exec"


def test_append_and_read_trace(exec_id, tmp_path, monkeypatch):
    from app.execution import trace as t
    monkeypatch.setattr(t, "_EXEC_DIR", tmp_path / "executions")

    now = _now()
    append_step_trace(
        exec_id,
        step_index=0, step_type="navigate", intent="navigate_to_start_url",
        started_at=now, completed_at=now, duration_ms=420.5,
        outcome="success",
    )
    append_step_trace(
        exec_id,
        step_index=1, step_type="click", intent="click_submit",
        started_at=now, completed_at=now, duration_ms=850.2,
        outcome="recovered", recovery_via="fingerprint_scored", recovery_score=0.78,
    )

    records = read_trace(exec_id)
    assert len(records) == 2
    assert records[0]["step_type"] == "navigate"
    assert records[1]["outcome"] == "recovered"
    assert records[1]["recovery_via"] == "fingerprint_scored"
    assert records[1]["recovery_score"] == 0.778


def test_aggregate_trace(exec_id, tmp_path, monkeypatch):
    from app.execution import trace as t
    monkeypatch.setattr(t, "_EXEC_DIR", tmp_path / "executions")

    now = _now()
    for i, (outcome, duration) in enumerate([
        ("success",   200.0),
        ("success",   300.0),
        ("recovered", 800.0),
        ("failed",    1200.0),
    ]):
        append_step_trace(
            exec_id,
            step_index=i, step_type="click", intent="click_x",
            started_at=now, completed_at=now, duration_ms=duration,
            outcome=outcome,
        )

    agg = aggregate_trace(exec_id)
    assert agg["step_count"] == 4
    assert agg["success_count"] == 2
    assert agg["recovered_count"] == 1
    assert agg["failed_count"] == 1
    assert agg["recovery_rate"] == 0.25
    assert agg["p50_ms"] > 0


def test_empty_trace_returns_empty(exec_id, tmp_path, monkeypatch):
    from app.execution import trace as t
    monkeypatch.setattr(t, "_EXEC_DIR", tmp_path / "executions")

    records = read_trace(exec_id)
    assert records == []
    agg = aggregate_trace(exec_id)
    assert agg["step_count"] == 0


def test_step_span_success(exec_id, tmp_path, monkeypatch):
    from app.execution import trace as t
    monkeypatch.setattr(t, "_EXEC_DIR", tmp_path / "executions")

    with step_span(exec_id, step_index=0, step_type="click", intent="click_btn") as ctx:
        ctx["page_url_after"] = "https://example.com/dashboard"

    records = read_trace(exec_id)
    assert len(records) == 1
    assert records[0]["outcome"] == "success"
    assert records[0]["page_url_after"] == "https://example.com/dashboard"
    assert records[0]["duration_ms"] >= 0


def test_step_span_failure(exec_id, tmp_path, monkeypatch):
    from app.execution import trace as t
    monkeypatch.setattr(t, "_EXEC_DIR", tmp_path / "executions")

    with pytest.raises(RuntimeError):
        with step_span(exec_id, step_index=0, step_type="click", intent="click_btn"):
            raise RuntimeError("Selector not found")

    records = read_trace(exec_id)
    assert records[0]["outcome"] == "failed"
    assert records[0]["error_class"] == "RuntimeError"
    assert "Selector not found" in records[0]["error_message"]
