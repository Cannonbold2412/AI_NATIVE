"""Request-scoped debug log for skill package builds (LLM + disk writes)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_log: ContextVar[list[dict[str, Any]] | None] = ContextVar("skill_pack_build_log", default=None)
_realtime_sink: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "skill_pack_build_realtime_sink",
    default=None,
)


@contextmanager
def skill_pack_build_log_scope(
    *,
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    buf: list[dict[str, Any]] = []
    token_log = _log.set(buf)
    token_rt = _realtime_sink.set(realtime_sink) if realtime_sink is not None else None
    try:
        yield buf
    finally:
        if token_rt is not None:
            _realtime_sink.reset(token_rt)
        _log.reset(token_log)


def skill_pack_log_append(entry: dict[str, Any]) -> None:
    buf = _log.get()
    if buf is None:
        return
    row = dict(entry)
    row.setdefault("ts", time.time())
    buf.append(row)
    sink = _realtime_sink.get()
    if sink is not None:
        sink(dict(row))
