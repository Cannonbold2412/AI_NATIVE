"""Raw payload cleanup, workflow discovery, and visual asset collection."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.storage.skill_packages import VISUAL_IMAGE_SUFFIXES

from .common import (
    _INPUT_DECLARATION_KEYS,
    _METADATA_KEYS,
    _STEP_CONTAINER_KEYS,
    _STEP_LIST_KEYS,
    _STEP_SCREENSHOT_URL_KEYS,
    _STEP_VISUAL_KEYS,
    _TITLE_KEYS,
    _get_mapping,
    _first_text_from_keys,
    _json_text,
)
from .models import RawWorkflow

_logger = logging.getLogger(__name__)

_NOISE_ACTION_TYPES = frozenset({
    "hover", "mousemove", "mousedown", "mouseup",
    "pointerover", "pointermove", "focus", "blur",
    "keydown", "keyup", "pointerdown", "pointerup",
})
_EXTRAS_NOISE_KEYS = frozenset({
    "session_id", "sequence", "ordinal", "pipeline_version",
    "content_fp", "primary_selector_kind", "fallback_selector_order",
    "selector_signature",
})
_MAX_INNER_TEXT = 120
_MAX_NORMALIZED_TEXT = 200
_MAX_PARENT_TEXT = 100
_MAX_SIBLING_TEXT = 80
_MAX_SIBLINGS = 2


def _get_step_action_type(step: dict[str, Any]) -> str:
    """Extract action type from step regardless of format (flat, simple, or nested)."""
    t = step.get("type") or step.get("action")
    if isinstance(t, str):
        return t.lower()
    if isinstance(t, dict):
        return str(t.get("action") or "").lower()
    return ""


def _trim_str(value: Any, max_chars: int) -> Any:
    """Trim string to max_chars if it exceeds the limit."""
    return value[:max_chars] if isinstance(value, str) and len(value) > max_chars else value


def preprocess_skill_pack_declarations(value: Any) -> Any:
    """Return a deep copy with unused declaration blocks removed from the whole tree.

    Drops ``inputs`` / ``parameters`` / ``params`` / ``variables`` everywhere — the
    pack builder does not use them for ``inputs.json`` (only ``{{placeholders}}`` in
    structured steps matter). Screenshot and session fields are left intact so
    ``_collect_visual_assets`` can still resolve ``visuals/`` files.
    """

    root = copy.deepcopy(value)
    _preprocess_declaration_blocks_in_place(root)
    return root


def preprocess_plugin_json(plugin_json: dict) -> dict:
    """Return a normalized plugin JSON copy with redundant aliases removed.

    Keeps semantic workflow fields intact while collapsing screenshot aliases to
    ``screenshot.full_url`` when a usable fallback exists.
    """

    if plugin_json is None or plugin_json == {}:
        return plugin_json
    if not isinstance(plugin_json, dict):
        return plugin_json

    def _json_size_bytes(value: Any) -> int:
        """Return the compact UTF-8 JSON size for logging."""

        return len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )

    def _resolve_screenshot_full_url(step: dict[str, Any]) -> str | None:
        """Return the preferred screenshot URL from direct or nested fallback fields."""

        screenshot = step.get("screenshot")
        if isinstance(screenshot, dict):
            for key in ("full_url", "scroll_url", "element_url"):
                value = screenshot.get(key)
                if value:
                    return str(value)

        visual = step.get("visual")
        if isinstance(visual, dict):
            value = visual.get("full_screenshot")
            if value:
                return str(value)

        signals = step.get("signals")
        if isinstance(signals, dict):
            nested_visual = signals.get("visual")
            if isinstance(nested_visual, dict):
                value = nested_visual.get("full_screenshot")
                if value:
                    return str(value)

        return None

    original_size = _json_size_bytes(plugin_json)
    cleaned = copy.deepcopy(plugin_json)

    for key in ("name", "id", "slug", "workflow_name", "workflowName", "label"):
        cleaned.pop(key, None)

    for key in ("metadata", "package_meta", "package_metadata"):
        cleaned.pop(key, None)

    steps = cleaned.get("steps")
    if "steps" not in cleaned:
        _logger.warning(
            "Plugin JSON preprocessing skipped step normalization because 'steps' is missing."
        )
    elif isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue

            screenshot_full_url = _resolve_screenshot_full_url(step)
            had_screenshot = isinstance(step.get("screenshot"), dict)

            step.pop("visual", None)
            step.pop("signals", None)

            if screenshot_full_url:
                step["screenshot"] = {"full_url": screenshot_full_url}
            elif had_screenshot:
                screenshot = copy.deepcopy(step["screenshot"])
                screenshot.pop("scroll_url", None)
                screenshot.pop("element_url", None)
                step["screenshot"] = screenshot

    cleaned_size = _json_size_bytes(cleaned)
    _logger.info(
        f"Plugin JSON preprocessed. Size reduction: {original_size} → {cleaned_size} bytes"
    )
    return cleaned


def _preprocess_declaration_blocks_in_place(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _preprocess_declaration_blocks_in_place(item)
        return
    if not isinstance(node, dict):
        return

    for key in list(node.keys()):
        if key in _INPUT_DECLARATION_KEYS:
            del node[key]

    for child in list(node.values()):
        _preprocess_declaration_blocks_in_place(child)


def sanitize_raw_steps_for_llm(raw_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce input token size by filtering noise actions and removing low-value fields.

    Filters out non-semantic actions (hover, focus, mousemove, etc.), removes volatile
    identifiers and operational metadata, trims long text fields, and deduplicates
    consecutive navigate steps to the same URL. Preserves semantic context needed for
    LLM structuring while minimizing token usage.
    """
    sanitized = [
        cleaned
        for step in raw_steps
        if isinstance(step, dict)
        for cleaned in [_sanitize_recording_step_for_llm(step)]
        if cleaned is not None
    ]

    result: list[dict[str, Any]] = []
    for step in sanitized:
        if (
            _get_step_action_type(step) == "navigate"
            and result
            and _get_step_action_type(result[-1]) == "navigate"
            and step.get("url") == result[-1].get("url")
        ):
            continue
        result.append(step)
    return result


def _sanitize_recording_step_for_llm(step: dict[str, Any]) -> dict[str, Any] | None:
    """Filter noise actions and remove low-value fields from a single step.

    Returns None for noise-action steps (hover, focus, etc.). Otherwise deep-copies
    and removes: volatile identifiers (id, classes), operational metadata (timing,
    timestamps, session_id, sequence, pipeline_version, etc.), XPath selectors (LLM
    told never to use), and trims long text fields.
    """
    if _get_step_action_type(step) in _NOISE_ACTION_TYPES:
        return None

    c = copy.deepcopy(step)

    c.pop("screenshot", None)
    c.pop("visual", None)
    c.pop("signals", None)
    c.pop("timing", None)

    action_block = c.get("action")
    if isinstance(action_block, dict):
        action_block.pop("timestamp", None)
        if action_block.get("value") is None:
            action_block.pop("value", None)

    target = c.get("target")
    if isinstance(target, dict):
        target.pop("id", None)
        target.pop("classes", None)
        if "inner_text" in target:
            target["inner_text"] = _trim_str(target["inner_text"], _MAX_INNER_TEXT)

    selectors = c.get("selectors")
    if isinstance(selectors, dict):
        selectors.pop("xpath", None)
        if not any(v for v in selectors.values()):
            c.pop("selectors", None)

    context = c.get("context")
    if isinstance(context, dict):
        context.pop("index_in_parent", None)
        if "parent" in context:
            context["parent"] = _trim_str(context["parent"], _MAX_PARENT_TEXT)
        siblings = context.get("siblings")
        if isinstance(siblings, list):
            trimmed = [_trim_str(s, _MAX_SIBLING_TEXT) for s in siblings[:_MAX_SIBLINGS]]
            context["siblings"] = trimmed if trimmed else None
            if not context.get("siblings"):
                context.pop("siblings", None)
        if not any(v for v in context.values() if v is not None):
            c.pop("context", None)

    semantic = c.get("semantic")
    if isinstance(semantic, dict):
        if "normalized_text" in semantic:
            semantic["normalized_text"] = _trim_str(semantic["normalized_text"], _MAX_NORMALIZED_TEXT)

    page = c.get("page")
    if isinstance(page, dict):
        page.pop("title", None)
        if not any(v for v in page.values() if v is not None):
            c.pop("page", None)

    state_change = c.get("state_change")
    if isinstance(state_change, dict):
        state_change.pop("before", None)
        if not any(v for v in state_change.values() if v is not None):
            c.pop("state_change", None)

    extras = c.get("extras")
    if isinstance(extras, dict):
        for key in _EXTRAS_NOISE_KEYS:
            extras.pop(key, None)
        if not extras:
            c.pop("extras", None)

    anchors = c.get("anchors")
    if isinstance(anchors, list) and not anchors:
        c.pop("anchors", None)

    return c


def _extract_steps(payload: Any) -> list[dict[str, Any]]:
    """Extract raw recording objects without interpreting their semantics."""

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in _STEP_LIST_KEYS:
        direct = payload.get(key)
        if isinstance(direct, list):
            steps = [item for item in direct if isinstance(item, dict)]
            if steps:
                return steps

    out: list[dict[str, Any]] = []
    for container_key in _STEP_CONTAINER_KEYS:
        container = payload.get(container_key)
        if isinstance(container, list):
            for item in container:
                out.extend(_extract_steps(item))
        elif isinstance(container, dict):
            out.extend(_extract_steps(container))
    if out:
        return out

    for value in payload.values():
        if isinstance(value, dict):
            out.extend(_extract_steps(value))
    return out


def _raw_workflow_title(item: dict[str, Any], fallback_index: int) -> str:
    return (
        _first_text_from_keys(item, _TITLE_KEYS)
        or _first_text_from_keys(_get_mapping(item.get("meta")), _TITLE_KEYS)
        or f"workflow_{fallback_index}"
    )


def _enumerate_raw_workflows(payload: Any) -> list[RawWorkflow]:
    if not isinstance(payload, dict):
        steps = _extract_steps(payload)
        return (
            [RawWorkflow(title="generated_skill", payload=payload, steps=steps)]
            if steps
            else []
        )

    for key in _STEP_CONTAINER_KEYS:
        container = payload.get(key)
        if isinstance(container, list):
            workflows: list[RawWorkflow] = []
            for index, item in enumerate(container, start=1):
                if not isinstance(item, dict):
                    continue
                steps = _extract_steps(item)
                if not steps:
                    continue
                workflows.append(
                    RawWorkflow(
                        title=_raw_workflow_title(item, index),
                        payload=item,
                        steps=steps,
                    )
                )
            if workflows:
                return workflows
        if isinstance(container, dict):
            workflows = []
            for index, (name, item) in enumerate(container.items(), start=1):
                if not isinstance(item, dict):
                    continue
                steps = _extract_steps(item)
                if not steps:
                    continue
                workflows.append(
                    RawWorkflow(
                        title=_first_text_from_keys(item, _TITLE_KEYS)
                        or str(name)
                        or f"workflow_{index}",
                        payload=item,
                        steps=steps,
                    )
                )
            if workflows:
                return workflows

    steps = _extract_steps(payload)
    return (
        [RawWorkflow(title=_package_title(payload), payload=payload, steps=steps)]
        if steps
        else []
    )


def _primary_skill_sheet_title(payload: dict[str, Any]) -> str:
    """Prefer a human workflow title nested under skills[] instead of root skill_* ids."""

    raw = payload.get("skills")
    if not isinstance(raw, list):
        return ""
    for item in raw:
        if not isinstance(item, dict):
            continue
        for key in ("title", "name"):
            text = _json_text(item.get(key))
            if text and text != "default":
                return text
    return ""


def _package_title(payload: Any, structured: dict[str, Any] | None = None) -> str:
    goal = _json_text((structured or {}).get("goal"))
    if goal:
        return goal
    if isinstance(payload, dict):
        nested = _primary_skill_sheet_title(payload)
        if nested:
            return nested
        for container in (
            *(_get_mapping(payload.get(key)) for key in _METADATA_KEYS),
            payload,
        ):
            value = _first_text_from_keys(container, _TITLE_KEYS)
            if value:
                return value
    return "generated_skill"


def _source_session_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("meta", "package_meta"):
        container = _get_mapping(payload.get(key))
        session_id = str(container.get("source_session_id") or "").strip()
        if session_id:
            return session_id
    return ""


def _relative_visual_asset_path(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    query_path = parse_qs(parsed.query).get("path", [])
    for candidate in query_path:
        rel = str(candidate or "").strip()
        if rel:
            return rel.replace("\\", "/")
    if parsed.scheme and parsed.netloc:
        return ""
    rel = text.replace("\\", "/")
    if not rel or rel.startswith("/") or ".." in rel:
        return ""
    return rel


def _persist_visual_asset_path(rel_path: str, session_id_fallback: str = "") -> str:
    rel = str(rel_path or "").strip().replace("\\", "/")
    if not rel or ".." in rel:
        return ""
    if rel.startswith("sessions/"):
        return rel
    if session_id_fallback:
        return f"sessions/{session_id_fallback}/{rel}"
    return rel


def _step_visual_asset_path(step: dict[str, Any], session_id_fallback: str = "") -> str:
    screenshot = _get_mapping(step.get("screenshot"))
    for key in _STEP_SCREENSHOT_URL_KEYS:
        rel = _relative_visual_asset_path(screenshot.get(key))
        if rel:
            return _persist_visual_asset_path(rel, session_id_fallback)

    signals = _get_mapping(step.get("signals"))
    for visual_like in (
        _get_mapping(signals.get("visual")),
        _get_mapping(step.get("visual")),
    ):
        for key in _STEP_VISUAL_KEYS:
            rel = _relative_visual_asset_path(visual_like.get(key))
            if rel:
                extras = _get_mapping(step.get("extras"))
                session_id = (
                    str(extras.get("session_id") or "").strip() or session_id_fallback
                )
                return _persist_visual_asset_path(rel, session_id)
    return ""


def _read_visual_asset_bytes(rel_path: str) -> tuple[str, bytes] | None:
    from app.editor.assets import resolve_skill_asset

    try:
        asset_path = resolve_skill_asset(rel_path)
    except ValueError:
        return None
    if not asset_path.is_file():
        return None
    suffix = asset_path.suffix.lower()
    if suffix not in VISUAL_IMAGE_SUFFIXES:
        return None
    return suffix, asset_path.read_bytes()


def _launch_visual_asset_path(session_id: str) -> str:
    if not session_id:
        return ""
    from app.storage.session_events import read_session_events

    for event in read_session_events(session_id):
        if not isinstance(event, dict):
            continue
        rel = _step_visual_asset_path(event, session_id)
        if rel:
            return rel
    return ""


def _collect_visual_assets(payload: Any) -> dict[str, bytes]:
    session_id = _source_session_id(payload)
    out: dict[str, bytes] = {}

    launch_rel = _launch_visual_asset_path(session_id)
    if launch_rel:
        launch_asset = _read_visual_asset_bytes(launch_rel)
        if launch_asset is not None:
            suffix, content = launch_asset
            out[f"Image_0{suffix}"] = content

    for index, step in enumerate(_extract_steps(payload), start=1):
        rel = _step_visual_asset_path(step, session_id)
        if not rel:
            continue
        asset = _read_visual_asset_bytes(rel)
        if asset is None:
            continue
        suffix, content = asset
        out[f"Image_{index}{suffix}"] = content
    return out
