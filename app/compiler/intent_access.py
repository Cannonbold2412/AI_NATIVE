"""Canonical FINAL_INTENT access — single read path for compiled and in-flight steps."""

from __future__ import annotations

from typing import Any


def get_effective_intent(semantic: dict[str, Any] | None) -> str:
    """Return FINAL_INTENT if set, else legacy llm_intent (must match compiler output after Phase 3)."""
    if not semantic:
        return ""
    fin = str(semantic.get("final_intent") or "").strip()
    if fin:
        return fin
    return str(semantic.get("llm_intent") or "").strip()


def get_effective_intent_from_skill_step(step: dict[str, Any]) -> str:
    """Resolve intent from a compiled skill step dict (top-level or nested signals)."""
    if not step:
        return ""
    top = str(step.get("intent") or "").strip()
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    sem = signals.get("semantic") if isinstance(signals.get("semantic"), dict) else {}
    if isinstance(step.get("semantic"), dict):
        sem = {**dict(step["semantic"]), **sem}
    eff = get_effective_intent(sem)
    return eff or top
