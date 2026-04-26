"""Normalize persisted SkillStep dicts for policy helpers that expect pipeline-shaped steps."""

from __future__ import annotations

from typing import Any


def skill_step_for_destructive_check(step: dict[str, Any]) -> dict[str, Any]:
    """Merge ``signals.semantic`` to top-level ``semantic`` for ``destructive_compiler_step``."""
    out = dict(step)
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    sem = signals.get("semantic") if isinstance(signals.get("semantic"), dict) else {}
    if sem:
        out["semantic"] = sem
    return out
