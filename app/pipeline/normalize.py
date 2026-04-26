"""Back-compat shim — prefer `run_pipeline` from `app.pipeline.run`."""

from __future__ import annotations

from typing import Any

from app.pipeline.run import run_pipeline


def passthrough(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Alias for `run_pipeline` (keeps older imports working)."""
    return run_pipeline(events)
