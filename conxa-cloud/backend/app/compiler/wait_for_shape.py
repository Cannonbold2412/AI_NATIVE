"""validation.wait_for: legacy leaf, top-level {op, conditions}, or nested groups (recursive AND/OR)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

WaitOp = Literal["and", "or"]


def is_wait_group(w: dict[str, Any] | None) -> bool:
    """True when ``w`` is a boolean group ``{op, conditions}`` (not a single leaf)."""
    if not w or not isinstance(w, dict):
        return False
    op = str(w.get("op") or "").strip().lower()
    return op in {"and", "or"} and isinstance(w.get("conditions"), list) and len(w.get("conditions") or []) > 0


def leaf_wait_type(leaf: dict[str, Any]) -> str:
    return str(leaf.get("type") or "none").strip().lower() or "none"


def leaf_wait_for_conditions(wf: dict[str, Any] | None) -> list[dict[str, Any]]:
    """All leaf wait dicts (flatten nested groups)."""

    def walk(node: dict[str, Any], out: list[dict[str, Any]]) -> None:
        if is_wait_group(node):
            for item in node.get("conditions") or []:
                if isinstance(item, dict):
                    walk(item, out)
        else:
            out.append(dict(node))

    if not wf or not isinstance(wf, dict):
        return [{"type": "none", "target": "", "timeout": 5000}]
    if is_wait_group(wf):
        out: list[dict[str, Any]] = []
        walk(wf, out)
        return out if out else [{"type": "none", "target": "", "timeout": 5000}]
    return [dict(wf)]


def wait_for_combinator(wf: dict[str, Any] | None) -> WaitOp | None:
    """Top-level combinator when root is a group; ``None`` for a legacy leaf dict."""
    if is_wait_group(wf):
        return str(wf.get("op") or "or").strip().lower()  # type: ignore[return-value]
    return None


def _node_non_trivial_for_destructive(node: dict[str, Any] | None) -> bool:
    """Whether this subtree guarantees a non-none wait (for destructive gate)."""
    if not node or not isinstance(node, dict):
        return False
    if is_wait_group(node):
        op = str(node.get("op") or "").strip().lower()
        kids = [c for c in (node.get("conditions") or []) if isinstance(c, dict)]
        if not kids:
            return False
        if op == "and":
            return all(_node_non_trivial_for_destructive(c) for c in kids)
        if op == "or":
            return any(_node_non_trivial_for_destructive(c) for c in kids)
        return False
    return leaf_wait_type(node) not in {"", "none"}


def destructive_wait_for_is_non_none(wf: dict[str, Any] | None) -> bool:
    """Destructive steps require a non-trivial wait tree (recursive AND/OR)."""
    if not wf or not isinstance(wf, dict):
        return False
    if is_wait_group(wf):
        return _node_non_trivial_for_destructive(wf)
    return leaf_wait_type(wf) not in {"", "none"}


def scan_wait_for_binding_targets(wf: dict[str, Any] | None, base_path: str, scan: Callable[[str, str], None]) -> None:
    """Emit ``{{var}}`` scan paths for every leaf ``target`` under ``wait_for``."""
    if not wf or not isinstance(wf, dict):
        return
    if is_wait_group(wf):
        for i, c in enumerate(wf.get("conditions") or []):
            if isinstance(c, dict):
                scan_wait_for_binding_targets(c, f"{base_path}.conditions[{i}]", scan)
    else:
        scan(f"{base_path}.target", str(wf.get("target") or ""))
