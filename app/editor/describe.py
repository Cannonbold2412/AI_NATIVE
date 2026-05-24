"""Deterministic human-readable step descriptions for the editor UI."""

from __future__ import annotations

import re
from typing import Any

from app.compiler.action_semantics import action_name
from app.compiler.intent_access import get_effective_intent_from_skill_step


def _visible_label(step: dict[str, Any]) -> str:
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    dom = signals.get("dom") if isinstance(signals.get("dom"), dict) else {}
    target = step.get("target") if isinstance(step.get("target"), dict) else {}
    semantic = signals.get("semantic") if isinstance(signals.get("semantic"), dict) else {}
    text = str(dom.get("inner_text") or target.get("inner_text") or semantic.get("normalized_text") or "").strip()
    if len(text) > 72:
        return text[:69] + "…"
    return text


def _selector_has_template(sel: str) -> bool:
    return "{{" in sel and "}}" in sel


# Playwright-style text locator embedded in stored primary_selector, e.g. text="{{db_name}}"
_PLAYWRIGHT_TEXT_EQ_DOUBLE = re.compile(r'^\s*text\s*=\s*"([^"]*)"\s*$', re.IGNORECASE)
_PLAYWRIGHT_TEXT_EQ_SINGLE = re.compile(r"^\s*text\s*=\s*'([^']*)'\s*$", re.IGNORECASE)


def _strip_playwright_text_equals(sel: str) -> str | None:
    """If selector is exclusively `text="..."` or `text='...'`, return the inner literal."""
    m = _PLAYWRIGHT_TEXT_EQ_DOUBLE.match(sel.strip())
    if m:
        return m.group(1).strip()
    m = _PLAYWRIGHT_TEXT_EQ_SINGLE.match(sel.strip())
    if m:
        return m.group(1).strip()
    return None


def _click_display_from_selector(primary_selector: str) -> str | None:
    """Stable label for parameterized clicks; unwraps text= wrappers to avoid ugly nested quotes."""
    ps = primary_selector.strip()
    if not ps:
        return None
    inner = _strip_playwright_text_equals(ps)
    candidate = inner if inner is not None else ps
    if not _selector_has_template(candidate):
        return None
    if len(candidate) > 72:
        return candidate[:69] + "…"
    return candidate


def _enquote_click_label(label: str) -> str:
    """Prefer double quotes around the label; fall back when that would nest badly."""
    if "'" in label and '"' in label:
        return f"[{label}]"
    if '"' in label:
        return f"'{label}'"
    return f'"{label}"'


def _click_list_label(recorded_label: str, primary_selector: str) -> str:
    """Prefer parameterized primary_selector for UI copy over frozen recording text."""
    from_sel = _click_display_from_selector(primary_selector)
    if from_sel is not None:
        return from_sel
    return recorded_label


def describe_step(step: dict[str, Any], step_index: int) -> str:
    n = step_index + 1
    act = action_name(step).lower()
    intent = get_effective_intent_from_skill_step(step) or str(step.get("intent") or "").strip()
    label = _visible_label(step)
    sel = str((step.get("target") or {}).get("primary_selector") or "").strip()

    if act == "scroll":
        return f"Step {n}: Scroll the page"
    if act == "navigate" or act == "goto":
        action = step.get("action") if isinstance(step.get("action"), dict) else {}
        direct_url = str((action or {}).get("url") or step.get("url") or "").strip() if isinstance(action, dict) else str(step.get("url") or "").strip()
        if direct_url:
            return f"Step {n}: Go to {direct_url[:80]}{'…' if len(direct_url) > 80 else ''}"
        ctx = (step.get("signals") or {}).get("context") or {}
        url = str(ctx.get("page_url") or "").strip()
        if url:
            return f"Step {n}: Go to {url[:80]}{'…' if len(url) > 80 else ''}"
        return f"Step {n}: Navigate"
    if act == "fill":
        v = step.get("value")
        tail = f' "{label}"' if label else ""
        if v is not None and str(v):
            return f"Step {n}: Fill{tail} with value"
        return f"Step {n}: Fill{tail}"
    if act in {"click", "dblclick", "right_click"}:
        list_label = _click_list_label(label, sel)
        quoted = _enquote_click_label(list_label) if list_label else ""
        intent_part = f" ({intent})" if intent else ""
        verb = {"click": "Click on", "dblclick": "Double click", "right_click": "Right click"}.get(act, "Click on")
        if quoted:
            return f"Step {n}: {verb} {quoted}{intent_part}".strip()
        if sel:
            return f"Step {n}: {verb} target {sel}{intent_part}".strip()
        return f"Step {n}: {verb}{intent_part}".strip()
    if act == "hover":
        list_label = _click_list_label(label, sel)
        quoted = _enquote_click_label(list_label) if list_label else ""
        intent_part = f" ({intent})" if intent else ""
        if quoted:
            return f"Step {n}: Hover over {quoted}{intent_part}".strip()
        if sel:
            return f"Step {n}: Hover over target {sel}{intent_part}".strip()
        return f"Step {n}: Hover{intent_part}".strip()
    if act == "focus":
        quoted = _enquote_click_label(_click_list_label(label, sel)) if (label or sel) else ""
        return f"Step {n}: Focus {quoted or sel}".strip()
    marker_labels = {
        "tab_open": "Recorded tab open",
        "tab_switch": "Recorded tab switch",
        "popup": "Recorded popup",
        "frame_enter": "Recorded frame enter",
        "frame_exit": "Recorded frame exit",
        "download_observed": "Recorded download",
        "dialog_appeared": "Recorded dialog",
        "dialog_accept": "Accepted dialog",
        "dialog_dismiss": "Dismissed dialog",
        "file_chooser_opened": "Recorded file chooser",
        "clipboard_copy": "Recorded clipboard copy",
        "clipboard_paste": "Recorded clipboard paste",
    }
    if act in marker_labels:
        return f"Step {n}: {marker_labels[act]}"
    if act:
        extra = f" — {intent}" if intent else ""
        return f"Step {n}: {act}{extra}".strip()
    return f"Step {n}: {intent or 'Recorded action'}".strip()
