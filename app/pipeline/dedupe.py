"""Collapse redundant consecutive events (deterministic)."""

from __future__ import annotations

from typing import Any


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
