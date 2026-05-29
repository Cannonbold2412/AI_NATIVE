"""Request-scoped debug log for skill package builds (LLM + disk writes)."""

from __future__ import annotations

import json
import re
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
_WORD_RE = re.compile(r"\w+", re.UNICODE)


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


def skill_pack_text_metrics(text: Any, prefix: str = "") -> dict[str, int]:
    """Return repeatable text size metrics for build-log rows."""

    value = "" if text is None else str(text)
    key = f"{prefix}_" if prefix else ""
    return {
        f"{key}chars": len(value),
        f"{key}words": len(_WORD_RE.findall(value)),
        f"{key}bytes": len(value.encode("utf-8")),
    }


def skill_pack_json_metrics(value: Any, prefix: str = "") -> dict[str, int]:
    """Return compact JSON text metrics for arbitrary payloads."""

    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value)
    return skill_pack_text_metrics(text, prefix=prefix)
