"""Pydantic DTOs for GET /skills/{id}/workflow and editor clients."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class StepFlags(BaseModel):
    is_destructive: bool = False
    is_scroll: bool = False
    generic_intent: bool = False


class StepScreenshotDTO(BaseModel):
    """Resolved asset URLs + geometry for bbox overlay in the client."""

    full_url: str | None = None
    element_url: str | None = None
    scroll_url: str | None = None
    bbox: dict[str, Any] = Field(default_factory=dict)
    viewport: str = ""
    scroll_position: str = ""


class StepEditorDTO(BaseModel):
    id: str
    step_index: int
    human_readable_description: str
    action_type: str = ""
    intent: str = ""
    final_intent: str = ""
    target: dict[str, Any] = Field(default_factory=dict)
    selectors: dict[str, Any] = Field(default_factory=dict)
    anchors_signals: list[dict[str, Any]] = Field(default_factory=list)
    anchors_recovery: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    recovery: dict[str, Any] = Field(default_factory=dict)
    value: Any = None
    input_binding: str | None = None
    screenshot: StepScreenshotDTO = Field(default_factory=StepScreenshotDTO)
    editable_fields: dict[str, bool] = Field(default_factory=dict)
    flags: StepFlags = Field(default_factory=StepFlags)
    parameter_bindings: list[dict[str, Any]] = Field(default_factory=list)


class SuggestionItem(BaseModel):
    step_index: int
    severity: Literal["info", "warn", "error"]
    code: str
    message: str


class SkillInputVariable(BaseModel):
    """Registry entry stored under SkillPackage.inputs."""

    id: str
    label: str = ""
    type: Literal["text", "select"] = "text"
    default: str | None = None
    options: list[str] = Field(default_factory=list)
    pattern: str | None = None


class WorkflowResponse(BaseModel):
    skill_id: str
    package_meta: dict[str, Any] = Field(default_factory=dict)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[StepEditorDTO] = Field(default_factory=list)
    suggestions: list[SuggestionItem] = Field(default_factory=list)
    asset_base_url: str = ""
