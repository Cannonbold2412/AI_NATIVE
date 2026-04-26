"""Workflow step dependency inference and deterministic topological ordering."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable

Step = dict[str, Any]


def _action_name(step: Step) -> str:
    action = step.get("action") or {}
    if isinstance(action, dict):
        return str(action.get("action") or "")
    return str(action)


def _target_group_key(step: Step) -> str:
    target = step.get("target") or {}
    selectors = step.get("selectors") or {}
    semantic = step.get("semantic") or {}
    return "|".join(
        [
            str(target.get("name") or ""),
            str(target.get("id") or ""),
            str(target.get("tag") or ""),
            str(target.get("aria_label") or ""),
            str(target.get("placeholder") or ""),
            str(selectors.get("aria") or ""),
            str(selectors.get("css") or ""),
            str(selectors.get("text_based") or ""),
            str(semantic.get("role") or ""),
            str(semantic.get("input_type") or ""),
        ]
    )


def _form_context(step: Step) -> str:
    ctx = step.get("context") or {}
    return str(ctx.get("form_context") or "")


def _is_editable_field_target(step: Step) -> bool:
    target = step.get("target") or {}
    tag = str(target.get("tag") or "").lower()
    return tag in {"input", "textarea", "select"}


def _is_prep_pointer_on_editable(step: Step, is_submit: Callable[[Step], bool]) -> bool:
    """Focus-equivalent acquisition on an editable control (not form submit)."""
    if _action_name(step).lower() != "click":
        return False
    if is_submit(step):
        return False
    return _is_editable_field_target(step)


def _default_dep_ranks() -> dict[str, int]:
    return {
        "focus": 0,
        "prep_editable_click": 0,
        "type": 1,
        "fill": 1,
        "click": 2,
        "scroll": 3,
        "submit_click": 4,
        "navigate": 0,
        "go_to": 0,
        "open": 0,
        "default": 2,
    }


def _action_dep_rank(step: Step, is_submit: Callable[[Step], bool], policy: dict[str, Any] | None) -> int:
    wf = (policy or {}).get("workflow") if isinstance((policy or {}).get("workflow"), dict) else {}
    raw = wf.get("dependency_ranks")
    ranks = dict(_default_dep_ranks())
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                ranks[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    action = _action_name(step).lower()
    if action == "focus":
        return int(ranks.get("focus", 0))
    if _is_prep_pointer_on_editable(step, is_submit):
        return int(ranks.get("prep_editable_click", 0))
    if action in {"type", "fill"}:
        return int(ranks.get("type" if action == "type" else "fill", 1))
    if action == "click" and is_submit(step):
        return int(ranks.get("submit_click", 4))
    if action == "click":
        return int(ranks.get("click", 2))
    if action in {"navigate", "go_to", "open"}:
        return int(ranks.get(action, 0))
    if action == "scroll":
        return int(ranks.get("scroll", 3))
    return int(ranks.get("default", 2))


def _build_edges(
    steps: list[Step], is_submit: Callable[[Step], bool], policy: dict[str, Any] | None = None
) -> list[tuple[int, int]]:
    """Return edges i -> j meaning step i must precede step j."""
    n = len(steps)
    edges_set: set[tuple[int, int]] = set()
    submit_indices = [i for i in range(n) if is_submit(steps[i])]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            gi, gj = _target_group_key(steps[i]), _target_group_key(steps[j])
            if gi != gj or not gi:
                continue
            ri, rj = _action_dep_rank(steps[i], is_submit, policy), _action_dep_rank(
                steps[j], is_submit, policy
            )
            if ri < rj:
                edges_set.add((i, j))

    for sidx in submit_indices:
        fc_s = _form_context(steps[sidx])
        for i in range(n):
            if i == sidx or is_submit(steps[i]):
                continue
            ai = _action_name(steps[i]).lower()
            if ai not in {"type", "fill", "focus", "click"}:
                continue
            if fc_s and _form_context(steps[i]) == fc_s:
                edges_set.add((i, sidx))
            elif (not fc_s) and _target_group_key(steps[i]) and _target_group_key(steps[i]) == _target_group_key(
                steps[sidx]
            ):
                edges_set.add((i, sidx))

    return list(edges_set)


def _toposort(n: int, edges: list[tuple[int, int]], original_index: list[int]) -> list[int]:
    adj: dict[int, list[int]] = defaultdict(list)
    indeg = [0] * n
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1
    q = deque(sorted([i for i in range(n) if indeg[i] == 0], key=lambda k: original_index[k]))
    out: list[int] = []
    while q:
        u = q.popleft()
        out.append(u)
        for v in sorted(adj[u], key=lambda k: original_index[k]):
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    if len(out) != n:
        return sorted(range(n), key=lambda k: original_index[k])
    return out


def infer_step_order(
    steps: list[Step], is_submit: Callable[[Step], bool], policy: dict[str, Any] | None = None
) -> list[Step]:
    """Reorder steps using dependency edges; ties broken by first occurrence index."""
    if not steps:
        return []
    original_index = list(range(len(steps)))
    edges = _build_edges(steps, is_submit, policy)
    order = _toposort(len(steps), edges, original_index)
    return [steps[i] for i in order]
