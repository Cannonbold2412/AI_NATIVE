"""Pydantic models for raw recorder events (multi-signal, high fidelity)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ActionKind = Literal[
    # pointer interactions
    "click", "dblclick", "right_click", "hover",
    # text / form
    "type", "fill", "set_checkbox", "set_radio", "select", "select_option", "date_pick",
    # drag / keyboard
    "drag_drop", "keyboard_shortcut",
    # scroll / navigation
    "scroll", "navigate",
    # browser context
    "tab_open", "tab_switch", "popup", "frame_enter", "frame_exit",
    # file I/O affordances
    "upload_intent", "upload", "download_observed",
    "dialog_appeared", "dialog_accept", "dialog_dismiss",
    "file_chooser_opened",
    "clipboard_copy", "clipboard_paste",
    # control
    "wait", "assert", "screenshot",
    # legacy
    "focus", "check",
]


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
    placeholder: str | None = None
    label_text: str | None = None


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


class FrameContext(BaseModel):
    """Iframe chain for actions captured inside child documents."""

    chain: list[dict[str, Any]] = Field(default_factory=list)


class Ancestor(BaseModel):
    """One ancestor element in the chain up to <body>."""

    tag: str
    id: str | None = None
    classes: list[str] = Field(default_factory=list)
    outer_html: str = ""  # truncated by bridge.js to keep payloads bounded


class SnapshotRef(BaseModel):
    """Pointer to a deduplicated DOM+a11y blob captured at compile time."""

    ref: str = ""  # uuid assigned by session.py on first capture of this hash
    dom_hash: str = ""  # sha256 of full HTML
    a11y_path: str | None = None  # relative blob path
    dom_path: str | None = None   # relative blob path


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
    frame: FrameContext = Field(default_factory=FrameContext)

    # Phase 2: compile-time signals for LLM-based selector generation (REQUIRED).
    # Recordings without these cannot validate; must be re-recorded.
    ancestors: list[Ancestor]
    surrounding_text: str
    snapshot: SnapshotRef
