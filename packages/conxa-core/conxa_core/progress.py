"""Job-progress primitive shared by the compile pipeline and the cloud job store.

The compile pipeline (in the Build Studio) and the cloud both want to emit
progress events tied to an ambient "current job". The contextvar + sink live
here so the pipeline has no dependency on any particular job backend:

  * The cloud registers ``job_store.append_event`` as the sink (see
    ``app/services/jobs.py``) so events land in the worker-backed job log.
  * The Build Studio leaves the sink unset (or registers its own stdio sink),
    so ``append_current_job_event`` is a no-op there.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_current_job_id: ContextVar[str | None] = ContextVar("current_job_id", default=None)

EventSink = Callable[[str, str, str, "dict[str, Any] | None"], None]
_event_sink: EventSink | None = None


def set_event_sink(sink: EventSink | None) -> None:
    """Register the backend that receives ``append_current_job_event`` calls."""
    global _event_sink
    _event_sink = sink


@contextmanager
def job_event_scope(job_id: str) -> Any:
    token = _current_job_id.set(job_id)
    try:
        yield
    finally:
        _current_job_id.reset(token)


def current_job_id() -> str | None:
    return _current_job_id.get()


def append_current_job_event(event: str, message: str, data: dict[str, Any] | None = None) -> None:
    job_id = _current_job_id.get()
    if not job_id or _event_sink is None:
        return
    _event_sink(job_id, event, message, data)
