"""Skill package schema (Phase 3+). Stubs only — compiler fills these."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillMeta(BaseModel):
    id: str
    version: int = 1
    title: str = ""
    created_at: str = ""
    source_session_id: str | None = None
    compiler_policy_version: str = ""
    compiler_policy_hash: str = ""


class SkillPolicies(BaseModel):
    failure_first: bool = True
    stop_on_low_confidence: bool = True


class RecoveryBlock(BaseModel):
    intent: str = ""
    final_intent: str = ""
    anchors: list[dict[str, Any]] = Field(default_factory=list)
    strategies: list[str] = Field(
        default_factory=lambda: ["semantic match", "position match", "visual match"]
    )
    confidence_threshold: float = 0.85
    max_attempts: int = 2
    require_diverse_attempts: bool = True


class ValidationBlock(BaseModel):
    wait_for: dict[str, Any] = Field(default_factory=dict)
    success_conditions: dict[str, Any] = Field(default_factory=dict)


class DecisionPolicy(BaseModel):
    ask_if_ambiguous: bool = True
    stop_if_low_confidence: bool = True
    max_retries: int = 2


class SkillStep(BaseModel):
    action: str | dict[str, Any]
    intent: str = ""
    url: str = ""
    target: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    value: Any = None
    input_binding: str | None = None
    validation: ValidationBlock = Field(default_factory=ValidationBlock)
    recovery: RecoveryBlock = Field(default_factory=RecoveryBlock)
    # Thresholds, weights, and layer rules — deterministic protocol for executors.
    confidence_protocol: dict[str, Any] = Field(default_factory=dict)
    decision_policy: DecisionPolicy = Field(default_factory=DecisionPolicy)


class SkillBlock(BaseModel):
    name: str = "default"
    steps: list[SkillStep] = Field(default_factory=list)


class SkillPackage(BaseModel):
    meta: SkillMeta
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[SkillBlock] = Field(default_factory=list)
    policies: SkillPolicies = Field(default_factory=SkillPolicies)
    llm: dict[str, Any] = Field(default_factory=dict)
