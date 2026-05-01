"""Attach a screenshot frame from the source recording to an editor step and re-run vision anchors."""

from __future__ import annotations

import urllib.parse
from typing import Any

from app.compiler.action_semantics import action_name
from app.compiler.build import _default_confidence_protocol, _merge_compile_warnings, _persisted_visual_asset_path
from app.compiler.decision_layer import rank_merged_anchors
from app.compiler.recovery_policy import merge_recovery_strategies_for_wait_shape
from app.config import settings
from app.editor.assets import resolve_skill_asset
from app.editor.step_view import skill_step_for_destructive_check
from app.llm.anchor_vision_llm import VisionAnchorGenerationError, generate_anchors_for_step_or_raise
from app.policy.bundle import PolicyBundle, get_policy_bundle

_STRIP_VISUAL_IMAGE_KEYS = ("full_screenshot", "element_snapshot", "scroll_screenshot", "bbox")


def screenshot_items_for_skill(
    skill_id: str,
    document: dict[str, Any],
    *,
    asset_base_url: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Return (session_id_or_none, items) for GET recording-screenshots."""
    meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    session_id = str(meta.get("source_session_id") or "").strip() or None
    if not session_id:
        return None, []

    from app.storage.session_events import read_session_events

    events = read_session_events(session_id)
    base = asset_base_url.rstrip("/")
    sid_q = urllib.parse.quote(skill_id, safe="")
    out: list[dict[str, Any]] = []

    for idx, ev in enumerate(events):
        vis = ev.get("visual") if isinstance(ev.get("visual"), dict) else {}
        rel = vis.get("full_screenshot")
        if not isinstance(rel, str) or not rel.strip():
            continue
        persisted_full = _persisted_visual_asset_path(
            dict(ev),
            rel,
            session_id_fallback=session_id,
        )
        if not persisted_full:
            continue
        extras = ev.get("extras") if isinstance(ev.get("extras"), dict) else {}
        seq_raw = extras.get("sequence")
        try:
            sequence = int(seq_raw) if seq_raw is not None else idx + 1
        except (TypeError, ValueError):
            sequence = idx + 1

        qs = urllib.parse.urlencode({"path": persisted_full})
        preview_url = f"{base}/skills/{sid_q}/assets?{qs}"

        out.append(
            {
                "event_index": idx,
                "sequence": sequence,
                "persisted_full_screenshot": persisted_full,
                "preview_url": preview_url,
                "viewport": str(vis.get("viewport") or ""),
                "has_element_snapshot": bool(
                    isinstance(vis.get("element_snapshot"), str) and str(vis.get("element_snapshot") or "").strip()
                ),
            }
        )

    return session_id, out


def _ev_rank_stub_from_step(step: dict[str, Any]) -> dict[str, Any]:
    """Minimal event-shaped dict for ``rank_merged_anchors`` (uses step semantics, not swapped frame copy)."""
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    return {
        "target": signals.get("dom") or {},
        "semantic": signals.get("semantic") or {},
        "context": signals.get("context") or {},
    }


def apply_recording_event_visual_to_step_or_raise(
    document: dict[str, Any],
    step_index: int,
    event_index: int,
    *,
    policy_bundle: PolicyBundle | None = None,
) -> dict[str, Any]:
    """Return a **new** document dict with swapped ``signals.visual``, fresh vision anchors, and bumped meta.version."""
    bundle = policy_bundle or get_policy_bundle()
    policy = bundle.data

    meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    session_id = str(meta.get("source_session_id") or "").strip()
    if not session_id:
        raise ValueError("no_source_session_id")

    from app.storage.session_events import read_session_events

    events = read_session_events(session_id)
    if event_index < 0 or event_index >= len(events):
        raise ValueError("event_index_out_of_range")

    ev_pick = dict(events[event_index])
    visual = dict(ev_pick.get("visual")) if isinstance(ev_pick.get("visual"), dict) else {}
    raw_full = visual.get("full_screenshot")
    if not isinstance(raw_full, str) or not raw_full.strip():
        raise ValueError("event_missing_full_screenshot")

    persisted_visual: dict[str, Any] = {
        "bbox": visual.get("bbox") if isinstance(visual.get("bbox"), dict) else {},
        "viewport": str(visual.get("viewport") or ""),
        "scroll_position": str(visual.get("scroll_position") or ""),
        "full_screenshot": _persisted_visual_asset_path(
            ev_pick,
            raw_full,
            session_id_fallback=session_id,
        ),
    }
    el_snap = visual.get("element_snapshot")
    if isinstance(el_snap, str) and el_snap.strip():
        persisted_visual["element_snapshot"] = _persisted_visual_asset_path(
            ev_pick,
            el_snap,
            session_id_fallback=session_id,
        )

    abs_check = resolve_skill_asset(persisted_visual["full_screenshot"])
    if not abs_check.is_file():
        raise ValueError("screenshot_file_missing_on_disk")

    doc = dict(document)
    skills = list(doc.get("skills") or [])
    if not skills:
        raise ValueError("no_skills_block")
    block = dict(skills[0])
    steps = list(block.get("steps") or [])
    if step_index < 0 or step_index >= len(steps):
        raise ValueError("step_index_out_of_range")

    step = dict(steps[step_index])
    if action_name(step).lower() == "scroll":
        raise ValueError("cannot_swap_visual_on_scroll_step")

    from app.compiler.intent_access import get_effective_intent_from_skill_step

    intent = get_effective_intent_from_skill_step(step) or str(step.get("intent") or "").strip()
    if not intent.strip():
        raise ValueError("intent_required_for_visual_swap")

    session_root = (settings.data_dir / "sessions" / session_id).resolve()
    ev_llm = {"visual": dict(persisted_visual)}
    anchors = generate_anchors_for_step_or_raise(
        ev_llm,
        session_root=session_root,
        final_intent=intent,
        policy=policy,
        step_index=step_index,
    )
    anchors = rank_merged_anchors(anchors, _ev_rank_stub_from_step(step), intent, policy)

    signals = dict(step.get("signals") or {})
    prev_vis = signals.get("visual") if isinstance(signals.get("visual"), dict) else {}
    merged_visual = dict(prev_vis)
    merged_visual.update(persisted_visual)
    signals["visual"] = merged_visual
    signals["anchors"] = list(anchors)
    step["signals"] = signals

    recovery = dict(step.get("recovery") or {})
    recovery["anchors"] = list(anchors)
    recovery["intent"] = intent
    recovery["final_intent"] = intent
    wf = (step.get("validation") or {}).get("wait_for") or {}
    recovery = merge_recovery_strategies_for_wait_shape(
        recovery,
        dict(wf) if isinstance(wf, dict) else {},
        policy,
    )
    step["recovery"] = recovery

    proto_base = dict(step.get("confidence_protocol") or _default_confidence_protocol(bundle))
    step["confidence_protocol"] = _merge_compile_warnings(
        proto_base,
        skill_step_for_destructive_check(step),
        anchors,
        policy,
    )

    steps[step_index] = step
    block["steps"] = steps
    skills[0] = block
    doc["skills"] = skills
    meta2 = dict(doc.get("meta") or {})
    meta2["version"] = int(meta2.get("version", 1)) + 1
    doc["meta"] = meta2
    return doc


def clear_step_visual_screenshots_or_raise(
    document: dict[str, Any],
    step_index: int,
    *,
    policy_bundle: PolicyBundle | None = None,
) -> dict[str, Any]:
    """Remove screenshot assets from ``signals.visual`` and clear vision anchors (no LLM)."""
    bundle = policy_bundle or get_policy_bundle()
    policy = bundle.data

    doc = dict(document)
    skills = list(doc.get("skills") or [])
    if not skills:
        raise ValueError("no_skills_block")
    block = dict(skills[0])
    steps = list(block.get("steps") or [])
    if step_index < 0 or step_index >= len(steps):
        raise ValueError("step_index_out_of_range")

    step = dict(steps[step_index])

    signals = dict(step.get("signals") or {})
    visual_prev = signals.get("visual") if isinstance(signals.get("visual"), dict) else {}
    visual = dict(visual_prev)
    for k in _STRIP_VISUAL_IMAGE_KEYS:
        visual.pop(k, None)
    signals["visual"] = visual
    signals["anchors"] = []
    step["signals"] = signals

    recovery = dict(step.get("recovery") or {})
    recovery["anchors"] = []
    from app.compiler.intent_access import get_effective_intent_from_skill_step

    intent_raw = (
        str(recovery.get("final_intent") or "").strip()
        or str(recovery.get("intent") or "").strip()
        or get_effective_intent_from_skill_step(step)
        or str(step.get("intent") or "").strip()
    )
    if intent_raw:
        recovery["intent"] = intent_raw
        recovery["final_intent"] = intent_raw
    wf = (step.get("validation") or {}).get("wait_for") or {}
    recovery = merge_recovery_strategies_for_wait_shape(
        recovery,
        dict(wf) if isinstance(wf, dict) else {},
        policy,
    )
    step["recovery"] = recovery

    proto_base = dict(step.get("confidence_protocol") or _default_confidence_protocol(bundle))
    step["confidence_protocol"] = _merge_compile_warnings(
        proto_base,
        skill_step_for_destructive_check(step),
        [],
        policy,
    )

    steps[step_index] = step
    block["steps"] = steps
    skills[0] = block
    doc["skills"] = skills
    meta = dict(doc.get("meta") or {})
    meta["version"] = int(meta.get("version", 1)) + 1
    doc["meta"] = meta
    return doc
