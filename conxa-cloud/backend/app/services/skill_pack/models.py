"""Data models for skill package builds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawWorkflow:
    """One workflow recording extracted from a raw package payload."""

    title: str
    payload: Any
    steps: list[dict[str, Any]]


@dataclass
class CompiledWorkflow:
    """In-memory artifacts for one workflow before it is written to disk."""

    name: str
    execution_json: str
    recovery_json: str
    inputs_json: str
    manifest_json: str
    skill_md: str
    inputs: list[dict[str, Any]]
    step_count: int
    visual_assets: dict[str, bytes]
    used_llm: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def input_count(self) -> int:
        return len(self.inputs)


@dataclass
class PersistedWorkflow:
    """API-facing summary for a workflow already written to bundle storage."""

    name: str
    bundle_slug: str
    index_json: str
    execution_json: str
    recovery_json: str
    inputs_json: str
    manifest_json: str
    input_count: int
    step_count: int
    used_llm: bool
    warnings: list[str] = field(default_factory=list)

    def to_response_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bundle_slug": self.bundle_slug,
            "index_json": self.index_json,
            "execution_json": self.execution_json,
            "recovery_json": self.recovery_json,
            "inputs_json": self.inputs_json,
            "manifest_json": self.manifest_json,
            "input_count": self.input_count,
            "step_count": self.step_count,
            "used_llm": self.used_llm,
            "warnings": list(self.warnings),
        }
