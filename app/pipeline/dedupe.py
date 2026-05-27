"""Collapse redundant consecutive events (deterministic)."""

from __future__ import annotations

from typing import Any

_ELEMENT_ACTIONS = frozenset({
    "click", "dblclick", "right_click", "type", "fill",
    "set_checkbox", "set_radio", "select", "select_option",
})
_FOCUS_LOOKAHEAD = 3


def _selector_key(ev: dict[str, Any]) -> str:
    """Return a stable same-element key. Empty string means not enough info to identify."""
    selectors = ev.get("selectors") or {}
    for key in ("aria", "text_based"):
        val = str(selectors.get(key) or "").strip()
        if val:
            return val
    css = str(selectors.get("css") or "").strip()
    if css:
        return css
    target = ev.get("target") or {}
    # Tag alone is not discriminating enough — require at least one stable attribute
    discriminators = list(filter(None, [
        str(target.get("id") or ""),
        str(target.get("aria_label") or ""),
        str(target.get("name") or ""),
    ]))
    if not discriminators:
        return ""
    tag = str(target.get("tag") or "")
    return "|".join(filter(None, [tag] + discriminators))


def drop_superseded_focus_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop focus events immediately superseded by a click/type/fill on the same element.

    A focus event is superseded when any of the next _FOCUS_LOOKAHEAD events is
    an element action (click, type, fill, …) targeting the same element.
    Standalone focus events (no matching action ahead) are kept.
    """
    out: list[dict[str, Any]] = []
    for i, ev in enumerate(events):
        if (ev.get("action") or {}).get("action") != "focus":
            out.append(ev)
            continue
        focus_key = _selector_key(ev)
        superseded = False
        for j in range(i + 1, min(i + 1 + _FOCUS_LOOKAHEAD, len(events))):
            nxt = events[j]
            nxt_action = (nxt.get("action") or {}).get("action")
            if nxt_action not in _ELEMENT_ACTIONS:
                continue
            if focus_key and _selector_key(nxt) == focus_key:
                superseded = True
                break
        if not superseded:
            out.append(ev)
    return out


def dedupe_scroll_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop consecutive scroll events with identical fingerprints and scroll offsets."""
    out: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("action", {}).get("action") != "scroll":
            out.append(ev)
            continue
        if out and out[-1].get("action", {}).get("action") == "scroll":
            prev = out[-1]
            same_scroll = prev.get("visual", {}).get("scroll_position") == ev.get("visual", {}).get(
                "scroll_position"
            )
            same_fp = prev.get("state_change", {}).get("after") == ev.get("state_change", {}).get(
                "after"
            )
            if same_scroll and same_fp:
                continue
        out.append(ev)
    return out
