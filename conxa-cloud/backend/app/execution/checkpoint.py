"""Step-level checkpoint persistence for pause/resume.

Written after each successful step so a failed or paused execution can
resume from the last known-good position rather than restarting from zero.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

_EXEC_DIR = settings.data_dir / "executions"


def _checkpoint_file(execution_id: str) -> Path:
    return _EXEC_DIR / execution_id / "checkpoint.json"


def write_checkpoint(
    execution_id: str,
    *,
    step_index: int,
    step_total: int,
    page_url: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist a checkpoint after successfully completing step_index."""
    f = _checkpoint_file(execution_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "execution_id": execution_id,
        "step_index": step_index,
        "step_total": step_total,
        "page_url": page_url,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        data.update(extra)
    f.write_text(json.dumps(data, indent=2))


def read_checkpoint(execution_id: str) -> dict[str, Any] | None:
    f = _checkpoint_file(execution_id)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


def clear_checkpoint(execution_id: str) -> None:
    f = _checkpoint_file(execution_id)
    try:
        f.unlink(missing_ok=True)
    except Exception:
        pass


def resume_from(execution_id: str) -> int:
    """Return the step index to resume from, or 0 if no checkpoint."""
    cp = read_checkpoint(execution_id)
    if not cp:
        return 0
    # Resume from the step AFTER the last completed one
    return int(cp.get("step_index", 0))
