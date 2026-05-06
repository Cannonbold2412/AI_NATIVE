"""Pydantic models for raw recorder events (multi-signal, high fidelity)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ActionKind = Literal["click", "type", "scroll", "select", "check"]


class ActionMeta(BaseModel):
    action: ActionKind
    timestamp: str
    value: str | None = None


class TargetDom(BaseModel):
    tag: str
    id: str | None = None
    classes: list[str] = Field(default_factory=list)
    inner_text: str = ""
    role: str | None = None
    aria_label: str | None = None
    name: str | None = None


class Selectors(BaseModel):
    css: str
    xpath: str
    text_based: str
    aria: str


class DomContext(BaseModel):
    parent: str
    siblings: list[str] = Field(default_factory=list)
    index_in_parent: int = 0
    form_context: str | None = None


class SemanticFeatures(BaseModel):
    normalized_text: str
    role: str
    input_type: str | None = None
    intent_hint: str


class AnchorRelation(BaseModel):
    element: str
    relation: Literal["below", "above", "inside", "near"]


class VisualFeatures(BaseModel):
    full_screenshot: str | None = None
    element_snapshot: str | None = None
    bbox: dict[str, int]
    viewport: str
    scroll_position: str


class PageContext(BaseModel):
    url: str
    title: str


class StateChange(BaseModel):
    before: str
    after: str


class Timing(BaseModel):
    wait_for: str = "load"
    timeout: int = 5000


class RecordedEvent(BaseModel):
    """Single user action with all attached signals (paths, not bytes)."""

    action: ActionMeta
    target: TargetDom
    selectors: Selectors
    context: DomContext
    semantic: SemanticFeatures
    anchors: list[AnchorRelation] = Field(default_factory=list)
    visual: VisualFeatures
    page: PageContext
    state_change: StateChange
    timing: Timing
    extras: dict[str, Any] = Field(default_factory=dict)
