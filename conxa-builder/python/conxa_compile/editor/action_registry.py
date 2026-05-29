"""Shared Human Edit action contract.

The recorder and skill-package compiler know more actions than the original
editor UI exposed. Keep the editor, saved export, and patch validation aligned
through this registry instead of scattering allowlists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from conxa_compile.compiler.action_policy import RECOVERY_ACTION_TYPES


ACTION_KIND_ORDER = (
    "navigate",
    "click",
    "dblclick",
    "right_click",
    "hover",
    "focus",
    "type",
    "fill",
    "set_checkbox",
    "set_radio",
    "select",
    "select_option",
    "date_pick",
    "drag_drop",
    "keyboard_shortcut",
    "scroll",
    "check",
    "assert",
    "wait",
    "screenshot",
    "upload_intent",
    "upload",
    "tab_open",
    "tab_switch",
    "popup",
    "frame_enter",
    "frame_exit",
    "download_observed",
    "dialog_appeared",
    "dialog_accept",
    "dialog_dismiss",
    "file_chooser_opened",
    "clipboard_copy",
    "clipboard_paste",
)

MARKER_ACTIONS = frozenset(
    {
        "tab_open",
        "tab_switch",
        "popup",
        "frame_enter",
        "frame_exit",
        "download_observed",
        "dialog_appeared",
        "dialog_accept",
        "dialog_dismiss",
        "file_chooser_opened",
        "clipboard_copy",
        "clipboard_paste",
    }
)

INSERTABLE_ACTIONS = frozenset(
    {
        "navigate",
        "click",
        "dblclick",
        "right_click",
        "hover",
        "focus",
        "type",
        "fill",
        "set_checkbox",
        "set_radio",
        "select",
        "select_option",
        "date_pick",
        "drag_drop",
        "keyboard_shortcut",
        "scroll",
        "check",
        "assert",
        "wait",
        "screenshot",
        "upload",
    }
)

SELECTOR_ACTIONS = frozenset(
    {
        "click",
        "dblclick",
        "right_click",
        "hover",
        "focus",
        "type",
        "fill",
        "set_checkbox",
        "set_radio",
        "select",
        "select_option",
        "date_pick",
        "drag_drop",
        "upload",
    }
)

VALUE_ACTIONS = frozenset(
    {
        "type",
        "fill",
        "set_checkbox",
        "set_radio",
        "select",
        "select_option",
        "date_pick",
        "drag_drop",
        "keyboard_shortcut",
        "wait",
        "upload",
    }
)

ACTION_LABELS = {
    "navigate": "Navigate",
    "click": "Click",
    "dblclick": "Double click",
    "right_click": "Right click",
    "hover": "Hover",
    "focus": "Focus",
    "type": "Type",
    "fill": "Fill",
    "set_checkbox": "Set checkbox",
    "set_radio": "Set radio",
    "select": "Select",
    "select_option": "Select option",
    "date_pick": "Date pick",
    "drag_drop": "Drag and drop",
    "keyboard_shortcut": "Keyboard shortcut",
    "scroll": "Scroll",
    "check": "Check",
    "assert": "Assert",
    "wait": "Wait",
    "screenshot": "Screenshot",
    "upload_intent": "Upload intent",
    "upload": "Upload",
    "tab_open": "Tab open",
    "tab_switch": "Tab switch",
    "popup": "Popup",
    "frame_enter": "Frame enter",
    "frame_exit": "Frame exit",
    "download_observed": "Download observed",
    "dialog_appeared": "Dialog appeared",
    "dialog_accept": "Dialog accept",
    "dialog_dismiss": "Dialog dismiss",
    "file_chooser_opened": "File chooser opened",
    "clipboard_copy": "Clipboard copy",
    "clipboard_paste": "Clipboard paste",
}

CATEGORIES = {
    "navigate": "flow",
    "scroll": "flow",
    "check": "validation",
    "assert": "validation",
    "wait": "validation",
    "screenshot": "validation",
    "click": "pointer",
    "dblclick": "pointer",
    "right_click": "pointer",
    "hover": "pointer",
    "focus": "pointer",
    "type": "input",
    "fill": "input",
    "set_checkbox": "input",
    "set_radio": "input",
    "select": "input",
    "select_option": "input",
    "date_pick": "input",
    "drag_drop": "advanced",
    "keyboard_shortcut": "advanced",
    "upload": "advanced",
    "upload_intent": "advanced",
}

VALUE_LABELS = {
    "type": "Value",
    "fill": "Value",
    "set_checkbox": "Checked (true or false)",
    "set_radio": "Value",
    "select": "Option value",
    "select_option": "Option value",
    "date_pick": "Date value",
    "drag_drop": "Drag payload JSON",
    "keyboard_shortcut": "Shortcut JSON or key combo",
    "wait": "Milliseconds",
    "upload": "File path input",
}


@dataclass(frozen=True)
class ActionSpec:
    kind: str
    label: str
    category: str
    insertable: bool
    marker: bool
    selectors: bool
    value: bool
    value_label: str
    recovery: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_action_kind(kind: Any) -> str:
    text = str(kind or "").strip().lower().replace("-", "_")
    if text == "input":
        return "type"
    return text


def action_spec(kind: Any) -> ActionSpec:
    normalized = normalize_action_kind(kind)
    if normalized not in ACTION_KIND_ORDER:
        return ActionSpec(
            kind=normalized,
            label=normalized.replace("_", " ").title() if normalized else "Unknown",
            category="unknown",
            insertable=False,
            marker=False,
            selectors=False,
            value=False,
            value_label="Value",
            recovery=False,
        )
    marker = normalized in MARKER_ACTIONS
    return ActionSpec(
        kind=normalized,
        label=ACTION_LABELS.get(normalized, normalized.replace("_", " ").title()),
        category="marker" if marker else CATEGORIES.get(normalized, "advanced"),
        insertable=normalized in INSERTABLE_ACTIONS,
        marker=marker,
        selectors=normalized in SELECTOR_ACTIONS,
        value=normalized in VALUE_ACTIONS,
        value_label=VALUE_LABELS.get(normalized, "Value"),
        recovery=normalized in RECOVERY_ACTION_TYPES,
    )


def action_spec_dict(kind: Any) -> dict[str, Any]:
    return action_spec(kind).to_dict()


def is_supported_action(kind: Any) -> bool:
    return normalize_action_kind(kind) in ACTION_KIND_ORDER


def is_marker_action(kind: Any) -> bool:
    return normalize_action_kind(kind) in MARKER_ACTIONS


def manual_action_kinds() -> tuple[str, ...]:
    return tuple(kind for kind in ACTION_KIND_ORDER if kind in INSERTABLE_ACTIONS)


def default_action_value(kind: str) -> Any:
    normalized = normalize_action_kind(kind)
    if normalized == "set_checkbox":
        return "true"
    if normalized == "keyboard_shortcut":
        return '{"key":"Enter","modifiers":{"ctrl":false,"shift":false,"alt":false,"meta":false}}'
    if normalized == "drag_drop":
        return '{"src_selector":"","dst_selector":""}'
    if normalized == "wait":
        return "1000"
    if normalized == "upload":
        return "{{file_path}}"
    if normalized in {"type", "fill", "select", "select_option", "date_pick", "set_radio"}:
        return ""
    return None
