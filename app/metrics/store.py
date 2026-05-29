"""Lightweight in-process metrics for MVP monitoring (swap for Prometheus later)."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class MetricsStore:
    recordings_started: int = 0
    recordings_stopped: int = 0
    events_captured: int = 0
    compile_attempts: int = 0
    compile_failures: int = 0
    compile_successes: int = 0
    update_step_attempts: int = 0
    update_step_successes: int = 0
    workflow_patch_step_attempts: int = 0
    workflow_patch_step_successes: int = 0
    fallback_usage: int = 0
    _lock: Lock = field(default_factory=Lock)

    def inc(self, name: str, delta: int = 1) -> None:
        with self._lock:
            current = getattr(self, name, None)
            if isinstance(current, int):
                setattr(self, name, current + delta)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            started = self.recordings_started
            stopped = self.recordings_stopped
            events = self.events_captured
            comp = self.compile_attempts
            comp_fail = self.compile_failures
            comp_ok = self.compile_successes
            upd = self.update_step_attempts
            upd_ok = self.update_step_successes
            wf_pa = self.workflow_patch_step_attempts
            wf_ok = self.workflow_patch_step_successes
            fb = self.fallback_usage
        success_rate = 1.0 if stopped == 0 else max(0.0, (stopped - comp_fail) / stopped)
        compile_ok_rate = 1.0 if comp == 0 else max(0.0, comp_ok / comp)
        return {
            "recordings_started": started,
            "recordings_stopped": stopped,
            "events_captured": events,
            "compile_attempts": comp,
            "compile_failures": comp_fail,
            "compile_successes": comp_ok,
            "compile_ok_rate": round(compile_ok_rate, 4),
            "update_step_attempts": upd,
            "update_step_successes": upd_ok,
            "workflow_patch_step_attempts": wf_pa,
            "workflow_patch_step_successes": wf_ok,
            "fallback_usage": fb,
            "success_rate": round(success_rate, 4),
            "failure_rate": round(1.0 - success_rate, 4),
        }


metrics = MetricsStore()
