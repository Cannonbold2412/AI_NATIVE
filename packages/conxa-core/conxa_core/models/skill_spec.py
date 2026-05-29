"""Skill package schema (Phase 3+). Compiler fills these at compile time."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class SkillMeta(BaseModel):
    id: str
    version: int = 1
    title: str = ""
    created_at: str = ""
    source_session_id: str | None = None
    compiler_policy_version: str = ""
    compiler_policy_hash: str = ""
    # Structural fingerprint of the first 3 steps' landmark selectors — used by
    # drift detection to detect site redesigns before execution begins.
    structural_fingerprint: dict[str, Any] = Field(default_factory=dict)


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


class Assertion(BaseModel):
    """A verifiable post-action condition checked after each step."""
    # url_pattern | selector_present | selector_absent | text_present | text_absent
    type: str
    target: str = ""
    timeout_ms: int = 5000
    # If True, assertion failure halts execution. If False, records a warning only.
    required: bool = True


class ValidationBlock(BaseModel):
    wait_for: dict[str, Any] = Field(default_factory=dict)
    success_conditions: dict[str, Any] = Field(default_factory=dict)
    # Multi-assertion outcome verification — runtime checks all assertions after action.
    assertions: list[Assertion] = Field(default_factory=list)


class DecisionPolicy(BaseModel):
    ask_if_ambiguous: bool = True
    stop_if_low_confidence: bool = True
    max_retries: int = 2


class ElementFingerprint(BaseModel):
    """Stable element identity for scoring-based resolution. Compiled from recorded signals."""
    role: str = ""
    tag: str = ""
    inner_text: str = ""       # visible text, max 120 chars
    aria_label: str = ""
    name: str = ""
    placeholder: str = ""
    label_text: str = ""
    data_testid: str = ""      # data-testid attribute value — highest-stability signal
    input_type: str = ""       # for <input> elements
    css_class_tokens: list[str] = Field(default_factory=list)   # stable class tokens only
    anchor_phrases: list[str] = Field(default_factory=list)     # relational context phrases
    position_hint: dict[str, Any] = Field(default_factory=dict) # normalized x/y as 0.0–1.0


class SkillStep(BaseModel):
    action: str | dict[str, Any]
    intent: str = ""
    url: str = ""
    frame: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    # Scoring-based element identity — runtime uses this to rank all candidates
    # against the recorded element instead of trying selectors blindly in order.
    element_fingerprint: ElementFingerprint = Field(default_factory=ElementFingerprint)
    signals: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    value: Any = None
    input_binding: str | None = None
    validation: ValidationBlock = Field(default_factory=ValidationBlock)
    recovery: RecoveryBlock = Field(default_factory=RecoveryBlock)
    confidence_protocol: dict[str, Any] = Field(default_factory=dict)
    decision_policy: DecisionPolicy = Field(default_factory=DecisionPolicy)

    # Phase 3: LLM-compiled selector candidates (ranked, validated against snapshot).
    # Runtime Tier 1 tries these in order; runtime never calls LLM unless all fail.
    compiled_selectors: list[str] = Field(default_factory=list)
    semantic_description: str = ""        # "First Name input in Add Person dialog"
    snapshot_ref: str = ""                # which recorded DOM blob this step compiled against
    snapshot_dom_hash: str = ""           # for cross-compilation cache lookup


class WorkflowIntentStep(BaseModel):
    index: int
    intent: str = ""
    verification_anchor: str = ""


class WorkflowIntentGraph(BaseModel):
    """Compile-time semantic understanding of the workflow (Claude Browser-style)."""

    goal: str = ""
    steps: list[WorkflowIntentStep] = Field(default_factory=list)
    decision_points: list[dict[str, Any]] = Field(default_factory=list)
    expected_end_state: dict[str, Any] = Field(default_factory=dict)


class SkillBlock(BaseModel):
    name: str = "default"
    steps: list[SkillStep] = Field(default_factory=list)


class SkillPackage(BaseModel):
    meta: SkillMeta
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[SkillBlock] = Field(default_factory=list)
    policies: SkillPolicies = Field(default_factory=SkillPolicies)
    llm: dict[str, Any] = Field(default_factory=dict)

    # Phase 3: workflow-level semantic understanding (one LLM call per workflow).
    intent_graph: WorkflowIntentGraph = Field(default_factory=WorkflowIntentGraph)

    # Per-step confidence report + LLM router statistics from compile.
    # Required: must contain status, steps_total, min_confidence, llm_router_stats, steps.
    compile_report: dict[str, Any]

    @model_validator(mode="after")
    def _validate_compile_report(self) -> "SkillPackage":
        required = {"status", "steps_total", "min_confidence", "llm_router_stats", "steps"}
        missing = required - set(self.compile_report.keys())
        if missing:
            raise ValueError(
                f"SkillPackage.compile_report missing required keys: {sorted(missing)}"
            )
        return self
