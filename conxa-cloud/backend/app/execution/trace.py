"""Per-execution step-level trace for observability and post-mortem debugging.

Each execution writes a JSONL trace file where every line is one step record:
  {step_index, started_at, completed_at, duration_ms, outcome, recovery_used,
   assertion_warnings, error_class, error_message, page_url_after}

Aggregation utilities compute failure rates, recovery usage, and p95 duration.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from app.config import settings

_EXEC_DIR = settings.data_dir / "executions"


def _trace_file(execution_id: str) -> Path:
    return _EXEC_DIR / execution_id / "trace.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_step_trace(
    execution_id: str,
    *,
    step_index: int,
    step_type: str,
    intent: str,
    started_at: str,
    completed_at: str,
    duration_ms: float,
    outcome: str,               # "success" | "recovered" | "failed" | "assertion_failed"
    recovery_via: str = "",     # "primary" | "fingerprint_scored" | "fuzzy_text" | ""
    recovery_score: float = 0.0,
    assertion_warnings: list[dict[str, Any]] | None = None,
    error_class: str = "",
    error_message: str = "",
    page_url_after: str = "",
) -> None:
    f = _trace_file(execution_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "execution_id": execution_id,
        "step_index": step_index,
        "step_type": step_type,
        "intent": intent,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": round(duration_ms, 1),
        "outcome": outcome,
    }
    if recovery_via:
        record["recovery_via"]   = recovery_via
        record["recovery_score"] = round(recovery_score, 3)
    if assertion_warnings:
        record["assertion_warnings"] = assertion_warnings
    if error_class:
        record["error_class"]   = error_class
        record["error_message"] = error_message[:500]
    if page_url_after:
        record["page_url_after"] = page_url_after
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def read_trace(execution_id: str) -> list[dict[str, Any]]:
    f = _trace_file(execution_id)
    if not f.exists():
        return []
    records = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            pass
    return records


def aggregate_trace(execution_id: str) -> dict[str, Any]:
    """Compute summary stats from a trace: failure rate, recovery rate, p50/p95 duration."""
    records = read_trace(execution_id)
    if not records:
        return {"execution_id": execution_id, "step_count": 0}
    durations = [r["duration_ms"] for r in records if "duration_ms" in r]
    outcomes  = [r.get("outcome", "") for r in records]
    durations_sorted = sorted(durations)
    n = len(durations_sorted)
    p50 = durations_sorted[n // 2] if n else 0
    p95 = durations_sorted[int(n * 0.95)] if n else 0

    return {
        "execution_id": execution_id,
        "step_count":      len(records),
        "success_count":   sum(1 for o in outcomes if o == "success"),
        "recovered_count": sum(1 for o in outcomes if o == "recovered"),
        "failed_count":    sum(1 for o in outcomes if "fail" in o),
        "p50_ms":  round(p50, 1),
        "p95_ms":  round(p95, 1),
        "total_ms": round(sum(durations), 1),
        "recovery_rate": round(sum(1 for o in outcomes if o == "recovered") / max(len(outcomes), 1), 3),
    }


@contextmanager
def step_span(
    execution_id: str,
    step_index: int,
    step_type: str,
    intent: str,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that records a step trace entry on exit."""
    ctx: dict[str, Any] = {
        "started_at": _now_iso(),
        "_start_ms": time.monotonic() * 1000,
        "outcome": "success",
        "recovery_via": "",
        "recovery_score": 0.0,
        "assertion_warnings": [],
        "error_class": "",
        "error_message": "",
        "page_url_after": "",
    }
    try:
        yield ctx
    except Exception as exc:
        ctx["outcome"]       = "failed"
        ctx["error_class"]   = type(exc).__name__
        ctx["error_message"] = str(exc)
        raise
    finally:
        end_ms  = time.monotonic() * 1000
        duration = end_ms - ctx["_start_ms"]
        append_step_trace(
            execution_id,
            step_index=step_index,
            step_type=step_type,
            intent=intent,
            started_at=ctx["started_at"],
            completed_at=_now_iso(),
            duration_ms=duration,
            outcome=ctx["outcome"],
            recovery_via=ctx.get("recovery_via", ""),
            recovery_score=ctx.get("recovery_score", 0.0),
            assertion_warnings=ctx.get("assertion_warnings") or [],
            error_class=ctx.get("error_class", ""),
            error_message=ctx.get("error_message", ""),
            page_url_after=ctx.get("page_url_after", ""),
        )
