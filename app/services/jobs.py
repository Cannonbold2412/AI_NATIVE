"""Small job abstraction used by the API while Redis workers are being wired in."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]
TerminalStatus = Literal["succeeded", "failed", "canceled"]


@dataclass
class JobEvent:
    ts: float
    event: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {"ts": self.ts, "event": self.event, "message": self.message, "data": self.data}


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: JobStatus = "queued"
    resource_id: str | None = None
    retry_count: int = 0
    user_error: str | None = None
    internal_error_code: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[JobEvent] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "resource_id": self.resource_id,
            "retry_count": self.retry_count,
            "user_error": self.user_error,
            "internal_error_code": self.internal_error_code,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()

    def create(self, kind: str, resource_id: str | None = None) -> JobRecord:
        job = JobRecord(job_id=f"job_{uuid.uuid4().hex}", kind=kind, resource_id=resource_id)
        job.events.append(JobEvent(time.time(), "queued", "Job queued."))
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def event_count(self, job_id: str) -> int:
        job = self.get(job_id)
        return len(job.events) if job else 0

    def events_after(self, job_id: str, index: int) -> list[dict[str, Any]]:
        job = self.get(job_id)
        if job is None:
            return []
        return [event.public() for event in job.events[index:]]

    def mark_running(self, job_id: str) -> None:
        self._update(job_id, "running", "running", "Job started.")

    def mark_canceled(self, job_id: str) -> None:
        self._update(job_id, "canceled", "canceled", "Job canceled.")

    def mark_succeeded(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        self._update(job_id, "succeeded", "succeeded", "Job completed.", result=result)

    def mark_failed(self, job_id: str, message: str, internal_error_code: str = "job_failed") -> None:
        self._update(
            job_id,
            "failed",
            "failed",
            message,
            user_error=message,
            internal_error_code=internal_error_code,
        )

    def _update(
        self,
        job_id: str,
        status: JobStatus,
        event: str,
        message: str,
        *,
        result: dict[str, Any] | None = None,
        user_error: str | None = None,
        internal_error_code: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = status
            job.updated_at = time.time()
            if result is not None:
                job.result = result
                if result.get("skill_id"):
                    job.resource_id = str(result["skill_id"])
            if user_error is not None:
                job.user_error = user_error
            if internal_error_code is not None:
                job.internal_error_code = internal_error_code
            job.events.append(JobEvent(time.time(), event, message, result or {}))


job_store = JobStore()


async def enqueue_job(
    kind: str,
    runner: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]],
    *,
    resource_id: str | None = None,
) -> JobRecord:
    job = job_store.create(kind, resource_id=resource_id)

    async def _run() -> None:
        job_store.mark_running(job.job_id)
        try:
            result = runner()
            if inspect.isawaitable(result):
                result = await result
            job_store.mark_succeeded(job.job_id, dict(result or {}))
        except Exception as exc:  # noqa: BLE001
            status_code = getattr(exc, "status_code", None)
            detail = getattr(exc, "detail", None)
            message = str(detail or exc)
            code = f"http_{status_code}" if status_code else exc.__class__.__name__
            job_store.mark_failed(job.job_id, message, code)

    asyncio.create_task(_run())
    return job
