"""LLM-first Skill Package generator.

Pipeline:

``raw skills.json -> declaration cleanup -> LLM structuring (trimmed steps) -> compiler -> package files``.

The LLM is the only layer that interprets messy recordings. This module only
validates structured output, compiles allowed runtime actions, and writes the
package artifacts.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import tempfile
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from zipfile import ZIP_DEFLATED, ZipFile

from app.config import settings
from app.services.skill_pack_build_log import skill_pack_build_log_scope, skill_pack_log_append
from app.services.skill_pack.common import (
    _VAR_PATTERN,
    _HYPHEN_COLLAPSE_RE,
    _CAMEL_BOUNDARY,
    _NON_WORD,
    _TEXT_SELECTOR_RE,
    _INPUT_NAME_RE,
    _STEP_LIST_KEYS,
    _STEP_CONTAINER_KEYS,
    _METADATA_KEYS,
    _TITLE_KEYS,
    _INPUT_CONTAINER_KEYS,
    _INPUT_DECLARATION_KEYS,
    _INPUT_NAME_KEYS,
    _STEP_VISUAL_KEYS,
    _STEP_SCREENSHOT_URL_KEYS,
    _GENERIC_SELECTORS,
    _GENERIC_LABELS,
    _SENSITIVE_HINTS,
    _LOGIN_TEXT,
    _DESTRUCTIVE_TEXT,
    _RECOVERY_VISUAL_SUFFIXES,
    _ALLOWED_STRUCTURED_TYPES,
    _parse_json_text,
    _normalize_name,
    _humanize_name,
    _slugify_name,
    slugify_skill_package_folder_name,
    slugify_skill_bundle_name,
    hyphen_skill_plugin_name,
    skill_package_agent_plugin_name,
    _json_text,
    _get_mapping,
    _first_text_from_keys,
)
from app.services.skill_pack.compiler import (
    _validate_structured_output,
    compile_execution,
    generate_recovery,
    parse_inputs,
    build_manifest,
    generate_skill_markdown,
    _normalize_manifest_json,
    _manifest_description,
    get_visual_ref,
    _validate_execution_plan,
)
from app.services.skill_pack.llm import _call_structuring_llm
from app.services.skill_pack.payload import (
    collect_visual_assets_for_structured_steps,
    sanitize_raw_steps_for_llm,
)
from app.services.skill_pack.models import RawWorkflow, CompiledWorkflow, PersistedWorkflow
from app.storage.skill_packages import (
    VISUAL_IMAGE_SUFFIXES,
    _bundle_write_lock,
    _sanitize_segment,
    _write_bundle_index,
    bundle_root_dir,
    format_credentials_example_json_text,
    format_plugin_index_json,
    format_plugin_readme_text,
    format_test_cases_stub_json_text,
    infer_auth_config,
    format_auth_json_text,
    read_skill_package_visual_asset_bytes,
    resolve_workflow_dir,
    validate_bundle_slug,
    write_skill_package_files_unlocked,
)

_logger = logging.getLogger(__name__)


class SkillPackBuildUserError(ValueError):
    """Validation or LLM failure with any ``build_log`` rows gathered so far."""

    def __init__(self, message: str, build_log: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.build_log = build_log


def _json_size_bytes(value: Any) -> int:
    """Return the compact UTF-8 JSON size for logging."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


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


def preprocess_plugin_json(plugin_json: dict | None) -> dict | None:
    """Return a normalized plugin JSON copy with redundant aliases removed.

    Keeps semantic workflow fields intact while collapsing screenshot aliases to
    ``screenshot.full_url`` when a usable fallback exists.
    """
    if plugin_json is None or plugin_json == {}:
        return plugin_json

    original_size = _json_size_bytes(plugin_json)
    cleaned = copy.deepcopy(plugin_json)

    for key in ("name", "id", "slug", "workflow_name", "workflowName", "label"):
        cleaned.pop(key, None)

    for key in ("metadata", "package_meta", "package_metadata"):
        cleaned.pop(key, None)

    steps = cleaned.get("steps")
    if "steps" not in cleaned:
        _logger.warning("Plugin JSON preprocessing skipped step normalization because 'steps' is missing.")
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
    _logger.info("Plugin JSON preprocessed. Size reduction: %s → %s bytes", original_size, cleaned_size)
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
        return [RawWorkflow(title="generated_skill", payload=payload, steps=steps)] if steps else []

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
                workflows.append(RawWorkflow(title=_raw_workflow_title(item, index), payload=item, steps=steps))
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
                        title=_first_text_from_keys(item, _TITLE_KEYS) or str(name) or f"workflow_{index}",
                        payload=item,
                        steps=steps,
                    )
                )
            if workflows:
                return workflows

    steps = _extract_steps(payload)
    return [RawWorkflow(title=_package_title(payload), payload=payload, steps=steps)] if steps else []


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
        for container in (*(_get_mapping(payload.get(key)) for key in _METADATA_KEYS), payload):
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
    for visual_like in (_get_mapping(signals.get("visual")), _get_mapping(step.get("visual"))):
        for key in _STEP_VISUAL_KEYS:
            rel = _relative_visual_asset_path(visual_like.get(key))
            if rel:
                extras = _get_mapping(step.get("extras"))
                session_id = str(extras.get("session_id") or "").strip() or session_id_fallback
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


_BUNDLE_SKILL_FILE_PATH = "orchestration/index.md"


def _resolve_bundle_slug(explicit: str | None) -> str:
    slug = slugify_skill_bundle_name(explicit)
    if not validate_bundle_slug(slug):
        raise ValueError(f'Invalid skill package name "{explicit}". Reserved or malformed slugs are not allowed.')
    return slug


def structure_steps_with_llm(raw_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert messy browser logs into validated structured steps via LLM."""
    if not raw_steps:
        raise ValueError("No workflow steps detected in JSON.")
    structured = _call_structuring_llm(sanitize_raw_steps_for_llm(raw_steps))
    return _validate_structured_output(structured)


def generate_execution_plan(payload: Any, inputs: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]]]:
    structured = (
        _validate_structured_output(payload)
        if isinstance(payload, dict) and "goal" in payload
        else structure_steps_with_llm(_extract_steps(payload))
    )
    plan = compile_execution(structured)
    lines = ["# Execution Plan", ""]
    for index, step in enumerate(plan, start=1):
        step_type = step["type"]
        if step_type == "navigate":
            lines.append(f"{index}. navigate {step['url']}")
        elif step_type == "fill":
            lines.append(f"{index}. fill {step['selector']} {step['value']}")
        elif step_type == "click":
            lines.append(f"{index}. click {step['selector']}")
        elif step_type == "scroll":
            scroll_parts: list[str] = []
            if step.get("selector"):
                scroll_parts.append(f"into_view {step['selector']}")
            if step.get("delta_y") is not None:
                scroll_parts.append(f"delta_y={step['delta_y']}")
            if step.get("delta_x"):
                scroll_parts.append(f"delta_x={step['delta_x']}")
            suffix = "; ".join(scroll_parts)
            lines.append(f"{index}. scroll" + (f" {suffix}" if suffix else ""))
        elif step_type == "check":
            kind = step.get("kind", "url")
            lines.append(f"{index}. check {kind}")
        elif step_type in {"type", "select", "focus"}:
            lines.append(f"{index}. {step_type} {step.get('selector', '')}")
    return "\n".join(lines).rstrip() + "\n", plan


def _pipeline_phase_append(phase: str, state: str, **fields: Any) -> None:
    row: dict[str, Any] = {"kind": "pipeline_phase", "phase": phase, "state": state}
    row.update(fields)
    skill_pack_log_append(row)


def _write_visual_assets_to_temp_dir(visual_assets: dict[str, bytes], parent: Path) -> Path:
    visuals_dir = parent / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in sorted(visual_assets.items()):
        safe_name = Path(filename).name
        if safe_name:
            (visuals_dir / safe_name).write_bytes(content)
    return visuals_dir


def _generate_recovery_with_visuals(structured: dict[str, Any], visual_assets: dict[str, bytes]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        visuals_dir = _write_visual_assets_to_temp_dir(visual_assets, Path(tmp))
        return generate_recovery(structured, visuals_dir)


def _serialize_workflow_artifacts(
    *,
    inputs: list[dict[str, Any]],
    manifest: dict[str, Any],
    execution_plan: list[dict[str, Any]],
    recovery_map: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2),
        json.dumps(manifest, ensure_ascii=False, indent=2),
        json.dumps(execution_plan, ensure_ascii=False, indent=2),
        json.dumps(recovery_map, ensure_ascii=False, indent=2),
    )


def _fix_execution_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Post-process execution plan to fix common issues found in render-plugin.

    Fixes:
    1. Add wait steps after fills before clicks (React state timing)
    2. Relax URL checks after redirects (login, delete, submit actions)
    3. Keep exact URL checks for direct navigation
    """
    if not plan:
        return plan

    fixed: list[dict[str, Any]] = []
    redirect_action_keywords = {"sign in", "login", "submit", "confirm", "delete", "logout"}

    for i, step in enumerate(plan):
        step_copy = copy.deepcopy(step)

        # Fix 1: Relax URL checks only after redirect-causing actions (login, delete, etc.)
        # Keep exact checks for direct navigation
        if step_copy.get("kind") in ("url_exact", "url_must_be") and i > 0:
            prev_step = plan[i - 1]
            prev_selector = (prev_step.get("selector") or "").lower()

            # Check if previous step was a redirect-causing action
            is_after_redirect_action = (
                prev_step.get("type") == "click"
                and any(keyword in prev_selector for keyword in redirect_action_keywords)
            )

            if is_after_redirect_action:
                # Relax to pattern matching (domain-only)
                step_copy["kind"] = "url"
                url_value = step_copy.get("url") or step_copy.get("pattern") or ""
                if "://" in url_value:
                    domain = url_value.split("://")[1].split("/")[0]
                    step_copy["pattern"] = domain
                    step_copy.pop("url", None)

        fixed.append(step_copy)

        # Fix 2: Add wait step after fill if next step is click/select (React timing)
        # This handles the case where filling an input enables a button via React state
        if (
            step_copy.get("type") in ("fill", "type")
            and i + 1 < len(plan)
            and plan[i + 1].get("type") in ("click", "select", "focus")
        ):
            # Check if this looks like a confirmation/command input (common pattern)
            selector = step_copy.get("selector", "").lower()
            is_command_like = "command" in selector or "confirm" in selector or "sudo" in selector

            if is_command_like:
                # Add 3-second wait for React state cycle and button re-render
                fixed.append({
                    "type": "wait",
                    "ms": 3000,
                })

    return fixed


def _align_recovery_step_ids(recovery_map: dict[str, Any], execution_plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Ensure recovery.json step_ids exactly match execution.json step numbers.

    Matches each recovery entry to its execution step by selector, then updates
    step_id to the actual 1-based execution position. This handles wait steps
    inserted by _fix_execution_plan shifting all subsequent indices.

    The executor does: recovery.steps.find(e => e.step_id === currentStep)
    A single mismatch silently disables recovery for that step.
    """
    if not isinstance(recovery_map, dict) or not isinstance(recovery_map.get("steps"), list):
        return recovery_map
    if not execution_plan:
        return recovery_map

    recovery_copy = copy.deepcopy(recovery_map)

    # Build selector → list of execution step indices (1-based, in order)
    # Keeps all occurrences so duplicate selectors (e.g. two "Delete" buttons) are
    # assigned in the order they appear, not collapsed to the first hit.
    recoverable_types = {"fill", "type", "click", "select", "focus"}
    selector_to_exec_indices: dict[str, list[int]] = {}
    for exec_idx, exec_step in enumerate(execution_plan, start=1):
        if exec_step.get("type") not in recoverable_types:
            continue
        sel = (exec_step.get("selector") or "").strip()
        if sel:
            selector_to_exec_indices.setdefault(sel, []).append(exec_idx)

    # Cursor tracks how many times each selector has been consumed
    selector_cursor: dict[str, int] = {}

    def _next_exec_idx_for_selector(sel: str) -> int | None:
        indices = selector_to_exec_indices.get(sel)
        if not indices:
            return None
        cursor = selector_cursor.get(sel, 0)
        if cursor >= len(indices):
            return None
        selector_cursor[sel] = cursor + 1
        return indices[cursor]

    # Update each recovery entry's step_id to match execution position
    unmatched: list[dict[str, Any]] = []
    for entry in recovery_copy["steps"]:
        primary = (entry.get("selector_context") or {}).get("primary", "").strip()
        new_id = _next_exec_idx_for_selector(primary) if primary else None

        if new_id is None:
            # Try alternatives in order
            alternatives = (entry.get("selector_context") or {}).get("alternatives") or []
            for alt in alternatives:
                alt = (alt or "").strip()
                new_id = _next_exec_idx_for_selector(alt) if alt else None
                if new_id is not None:
                    break

        if new_id is not None:
            entry["step_id"] = new_id
            if isinstance(entry.get("visual_metadata"), dict):
                entry["visual_metadata"]["step_id"] = new_id
        else:
            unmatched.append(entry)

    if unmatched:
        _logger.warning(
            "_align_recovery_step_ids: %d recovery entries could not be matched to execution steps "
            "(selectors not found in execution plan). step_ids left as-is for: %s",
            len(unmatched),
            [e.get("intent") for e in unmatched],
        )

    return recovery_copy


def _compile_workflow_payload(
    payload: Any,
    raw_steps: list[dict[str, Any]],
    package_name: str | None = None,
    source_title: str = "",
) -> CompiledWorkflow:
    if not raw_steps:
        raise ValueError("No workflow steps detected in JSON.")
    workflow_title = str(source_title or "").strip() or "workflow"
    _pipeline_phase_append("llm_structure", "start", workflow_title=workflow_title, raw_step_count=len(raw_steps))
    t_llm = time.perf_counter()
    structured = structure_steps_with_llm(raw_steps)
    _pipeline_phase_append(
        "llm_structure",
        "done",
        workflow_title=workflow_title,
        elapsed_ms=round((time.perf_counter() - t_llm) * 1000, 2),
        canonical_step_count=len(structured["steps"]),
        goal_chars=len(str(structured.get("goal") or "")),
    )
    workflow_slug = _slugify_name(package_name or source_title or _package_title(payload, structured=None) or "generated_skill")
    _pipeline_phase_append(
        "deterministic_compile",
        "start",
        workflow_title=workflow_title,
        package_name=workflow_slug,
    )
    t_det = time.perf_counter()
    inputs = parse_inputs(structured)
    execution_plan = compile_execution(structured)
    _validate_execution_plan(execution_plan)

    # Apply fixes: timing, selectors, URL checks
    execution_plan = _fix_execution_plan(execution_plan)

    manifest = build_manifest(inputs, workflow_slug, str(structured.get("goal") or ""))
    skill_md = generate_skill_markdown(
        workflow_slug,
        structured,
        inputs,
        document_title=(source_title or "").strip() or None,
    )
    _pipeline_phase_append(
        "deterministic_compile",
        "done",
        workflow_title=workflow_title,
        elapsed_ms=round((time.perf_counter() - t_det) * 1000, 2),
        execution_plan_steps=len(execution_plan),
        input_slots=len(inputs),
        skill_md_chars=len(skill_md),
    )
    visual_assets = collect_visual_assets_for_structured_steps(structured["steps"], payload)
    viz_count = len(visual_assets) if isinstance(visual_assets, dict) else 0
    _pipeline_phase_append("recovery_map", "start", workflow_title=workflow_title, visual_assets=viz_count)
    t_rec = time.perf_counter()
    recovery_map = _generate_recovery_with_visuals(structured, visual_assets)

    # Align recovery step IDs with execution plan (critical for recovery activation)
    recovery_map = _align_recovery_step_ids(recovery_map, execution_plan)

    rec_items = recovery_map.get("steps") if isinstance(recovery_map, dict) else []
    rec_n = len(rec_items) if isinstance(rec_items, list) else 0
    _pipeline_phase_append(
        "recovery_map",
        "done",
        workflow_title=workflow_title,
        elapsed_ms=round((time.perf_counter() - t_rec) * 1000, 2),
        recovery_entries=rec_n,
    )
    _pipeline_phase_append("serialize_artifacts", "start", workflow_title=workflow_title)
    t_ser = time.perf_counter()
    inputs_json, manifest_json, execution_json, recovery_json = _serialize_workflow_artifacts(
        inputs=inputs,
        manifest=manifest,
        execution_plan=execution_plan,
        recovery_map=recovery_map,
    )
    chars_total = len(inputs_json) + len(manifest_json) + len(execution_json) + len(recovery_json)
    _pipeline_phase_append(
        "serialize_artifacts",
        "done",
        workflow_title=workflow_title,
        elapsed_ms=round((time.perf_counter() - t_ser) * 1000, 2),
        json_chars=chars_total,
    )

    return CompiledWorkflow(
        name=workflow_slug,
        execution_json=execution_json,
        recovery_json=recovery_json,
        inputs_json=inputs_json,
        manifest_json=manifest_json,
        skill_md=skill_md,
        inputs=inputs,
        step_count=len(execution_plan),
        visual_assets=visual_assets,
    )


def _compile_skill_package_payloads(payload: Any, package_name: str | None = None) -> list[CompiledWorkflow]:
    from concurrent.futures import ThreadPoolExecutor

    raw_workflows = _enumerate_raw_workflows(payload)
    if not raw_workflows:
        raise ValueError("No workflow steps detected in JSON.")
    total = len(raw_workflows)
    skill_pack_log_append({"kind": "bundle_compile_outline", "workflow_count": total})

    def _compile_single_workflow(index: int, raw_workflow: RawWorkflow) -> CompiledWorkflow:
        label = str(raw_workflow.title or f"workflow_{index}")
        skill_pack_log_append(
            {
                "kind": "workflow_compile_start",
                "index": index,
                "total": total,
                "title": label,
                "raw_steps": len(raw_workflow.steps),
            }
        )
        result = _compile_workflow_payload(
            raw_workflow.payload,
            raw_workflow.steps,
            package_name=None,
            source_title=label,
        )
        skill_pack_log_append(
            {"kind": "workflow_compile_complete", "index": index, "total": total, "package_name": result.name}
        )
        return result

    if total == 1:
        return [_compile_single_workflow(1, raw_workflows[0])]

    max_workers = min(4, total)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_compile_single_workflow, index, raw_workflow)
            for index, raw_workflow in enumerate(raw_workflows, start=1)
        ]
        compiled = [future.result() for future in futures]

    return compiled


def _generate_claude_md_text(plugin_slug: str, skill_names: list[str]) -> str:
    """Generate CLAUDE.md — execution agent instructions for the plugin."""
    plugin_name = plugin_slug.replace("_", " ").title()
    skill_list = "\n".join(f"- `{name}`" for name in skill_names) if skill_names else "- (none yet)"

    return (
        f"# {plugin_name} Plugin — Execution Agent Instructions\n\n"
        "You are an execution agent for this automation plugin. When the user asks you to do anything, "
        "you MUST execute it using the plugin — never explain, never offer manual steps, never ask "
        '"what kind of help do you want?".\n\n'
        "## How to Handle Any User Request\n\n"
        f"1. Read `{plugin_slug}.json` to see available skills and their input requirements\n"
        "2. Match the user request to the correct skill(s)\n"
        "3. Read `skills/<skill-name>/input.json` for each required skill to see what inputs are needed\n"
        "4. Ask the user ONCE for any missing inputs (credentials, names, values, etc.)\n"
        "5. Create `_plan.json` using PowerShell (NEVER use the Write tool — it requires a prior Read):\n"
        '   ```powershell\n'
        '   Set-Content -Path "C:\\path\\to\\plugin\\_plan.json" -Value \'[{"skill":"...","inputs":{...}}]\'\n'
        '   ```\n'
        "   Use the absolute path to the plugin folder. Validate the JSON is well-formed before writing.\n"
        "6. Run: `node execution/executor.js --plan _plan.json` (from the plugin directory)\n"
        "7. Read `EXECUTION_PLAN_RESULT.json` and report pass/fail to the user\n\n"
        "## Plan File Format\n\n"
        "```json\n"
        "[\n"
        "  {\n"
        '    "skill": "skill_name",\n'
        '    "inputs": {\n'
        '      "input_name": "value"\n'
        "    }\n"
        "  }\n"
        "]\n"
        "```\n\n"
        "## Critical Rules\n\n"
        "- ALWAYS execute via `executor.js` — never provide manual instructions or API code\n"
        "- DO NOT ask \"do you want me to automate this?\" — assume yes, always\n"
        "- Ask for inputs ONCE, not repeatedly\n"
        f"- ONLY use skills listed in `{plugin_slug}.json`\n"
        "- After execution, show the user a summary from `EXECUTION_PLAN_RESULT.json`\n\n"
        "## Available Skills\n\n"
        f"{skill_list}\n\n"
        f"Full details in `{plugin_slug}.json` and `orchestration/`.\n"
    )


def _generate_setup_md_text(plugin_slug: str) -> str:
    """Generate SETUP.md — setup and usage guide for end users."""
    plugin_name = plugin_slug.replace("_", " ").title()

    return (
        f"# {plugin_name} Plugin — Setup Guide\n\n"
        "## What This Plugin Does\n\n"
        "This is an automation plugin that runs real workflows on services you use. "
        "It uses browser automation (Playwright) to execute recorded workflows.\n\n"
        "## Prerequisites (one-time setup)\n\n"
        "1. **Node.js** (v18+) installed — https://nodejs.org\n"
        "2. **Claude Code** CLI installed — `npm install -g @anthropic-ai/claude-code`\n"
        "3. Unzip the plugin folder anywhere (e.g., `~/plugins/{}`)\n\n".format(plugin_slug) +
        "## Installation\n\n"
        "```bash\n"
        f"cd {plugin_slug}\n"
        "npm install          # installs Playwright\n"
        "npx playwright install chromium   # downloads Chromium browser\n"
        "```\n\n"
        "## Running with Claude (Recommended)\n\n"
        "```bash\n"
        f"cd {plugin_slug}\n"
        "claude   # opens Claude Code in this folder\n"
        "```\n\n"
        "Then tell Claude what you want to do. Examples:\n"
        "- *\"Execute task X\"*\n"
        "- *\"Run the workflow with these inputs\"*\n\n"
        "Claude will:\n"
        "1. Read the plugin files to understand available skills\n"
        "2. Ask for any missing inputs\n"
        "3. Generate a `_plan.json` file\n"
        "4. Run `node execution/executor.js --plan _plan.json`\n"
        "5. Report results from `EXECUTION_PLAN_RESULT.json`\n\n"
        "## Running Manually (Without Claude)\n\n"
        "### Single skill\n"
        "```bash\n"
        "node execution/executor.js --skill skill_name --inputs inputs.json\n"
        "```\n\n"
        "### Multiple skills (plan mode)\n"
        "```bash\n"
        "node execution/executor.js --plan plan.json\n"
        "```\n\n"
        "### Debug mode (see browser)\n"
        "```bash\n"
        "node execution/executor.js --plan plan.json --headless 0\n"
        "```\n\n"
        "## File Format Examples\n\n"
        "### inputs.json\n"
        "```json\n"
        "{\n"
        '  "user_email": "you@example.com",\n'
        '  "user_password": "password",\n'
        '  "resource_name": "my-resource"\n'
        "}\n"
        "```\n\n"
        "### plan.json\n"
        "```json\n"
        "[\n"
        "  {\n"
        '    "skill": "login",\n'
        '    "inputs": { "user_email": "you@example.com", "user_password": "pass" }\n'
        "  },\n"
        "  {\n"
        '    "skill": "delete_resource",\n'
        '    "inputs": { "user_email": "you@example.com", "user_password": "pass", "resource_name": "my-resource" }\n'
        "  }\n"
        "]\n"
        "```\n\n"
        "## Results\n\n"
        "After execution, check:\n"
        "- `EXECUTION_RESULT.json` — single skill result\n"
        "- `EXECUTION_PLAN_RESULT.json` — multiple skill result\n\n"
        "## Troubleshooting\n\n"
        "**Browser won't open**: Make sure Playwright Chromium is installed: `npx playwright install chromium`\n\n"
        "**Skill fails with 'element not found'**: The UI may have changed. Recovery layers will attempt to fix it. "
        "If it still fails, the skill may need re-recording.\n\n"
        "**Credentials errors**: Verify your inputs.json has correct values for all required fields.\n"
    )


def _workflow_file_payload(compiled: CompiledWorkflow) -> dict[str, str]:
    return {
        "execution.json": compiled.execution_json,
        "recovery.json": compiled.recovery_json,
        "input.json": compiled.inputs_json,
        "manifest.json": compiled.manifest_json,
        "SKILL.md": compiled.skill_md,
        "tests/test-cases.json": format_test_cases_stub_json_text(compiled.inputs),
    }


def _persist_skill_package_artifacts(compiled: CompiledWorkflow, bundle_slug: str) -> PersistedWorkflow:
    write_skill_package_files_unlocked(
        bundle_slug,
        compiled.name,
        _workflow_file_payload(compiled),
        visual_assets=compiled.visual_assets,
    )
    index_json = _build_plugin_index_json(bundle_slug)

    return PersistedWorkflow(
        name=compiled.name,
        bundle_slug=bundle_slug,
        index_json=index_json,
        execution_json=compiled.execution_json,
        recovery_json=compiled.recovery_json,
        inputs_json=compiled.inputs_json,
        manifest_json=compiled.manifest_json,
        input_count=compiled.input_count,
        step_count=compiled.step_count,
        used_llm=compiled.used_llm,
        warnings=list(compiled.warnings),
    )


def _build_plugin_index_json(bundle_slug: str) -> str:
    """Read plugin index from disk, falling back to empty structure."""
    bundle_root = bundle_root_dir(bundle_slug)
    slug = _sanitize_segment(bundle_slug)
    if bundle_root:
        index_path = bundle_root / f"{slug}.json"
        if index_path.is_file():
            return index_path.read_text(encoding="utf-8")
    return json.dumps({"plugin": slug, "version": "1.0.0", "skills": []}, indent=2)


def _refresh_bundle_runtime_files(bundle_slug: str) -> str:
    bundle_root = bundle_root_dir(bundle_slug)
    if bundle_root is None or not bundle_root.is_dir():
        slug = _sanitize_segment(bundle_slug)
        return json.dumps({"plugin": slug, "version": "1.0.0", "skills": []}, indent=2)
    _write_bundle_index(bundle_root, bundle_slug)
    return _build_plugin_index_json(bundle_slug)


def _prepare_skill_package_payload(json_text: str) -> Any:
    """Parse user JSON and normalize noisy declaration fields before compilation."""
    payload = _parse_json_text(json_text)
    if isinstance(payload, dict):
        title_hint = _package_title(payload)
        source_session_id = _source_session_id(payload)
        payload = preprocess_plugin_json(payload)
        if payload and isinstance(payload, dict):
            if title_hint and title_hint != "generated_skill" and not _first_text_from_keys(payload, _TITLE_KEYS):
                payload["title"] = title_hint
            if source_session_id and not _source_session_id(payload):
                payload["package_meta"] = {**_get_mapping(payload.get("package_meta")), "source_session_id": source_session_id}
    return preprocess_skill_pack_declarations(payload)


def _log_persist_phase_start(bundle_slug: str, package_name: str | None) -> None:
    skill_pack_log_append(
        {
            "kind": "persist_phase",
            "state": "start",
            "bundle_slug": bundle_slug,
            "workflow_package_hint": package_name,
        }
    )


def _persist_compiled_workflows(compiled_workflows: list[CompiledWorkflow], bundle_slug: str) -> list[PersistedWorkflow]:
    persisted: list[PersistedWorkflow] = []
    try:
        for compiled in compiled_workflows:
            persisted.append(_persist_skill_package_artifacts(compiled, bundle_slug))

        # Write plugin-level documentation to bundle root
        skill_names = [p.name for p in persisted]
        bundle_root = bundle_root_dir(bundle_slug)
        if bundle_root and bundle_root.is_dir():
            (bundle_root / "CLAUDE.md").write_text(
                _generate_claude_md_text(bundle_slug, skill_names), encoding="utf-8"
            )
            (bundle_root / "SETUP.md").write_text(
                _generate_setup_md_text(bundle_slug), encoding="utf-8"
            )

        return persisted
    except Exception:
        import shutil
        for persisted_item in persisted:
            try:
                workflow_dir = resolve_workflow_dir(bundle_slug, persisted_item.name)
                if workflow_dir and workflow_dir.is_dir():
                    shutil.rmtree(workflow_dir)
            except Exception as exc:
                _logger.warning("Rollback cleanup failed for %s: %s", persisted_item.name, exc)
        raise


def _ensure_new_workflow_names(bundle_slug: str, compiled_workflows: list[CompiledWorkflow]) -> None:
    for compiled in compiled_workflows:
        if resolve_workflow_dir(bundle_slug, compiled.name):
            raise ValueError(f'Workflow "{compiled.name}" already exists in bundle "{bundle_slug}".')


def _read_bundle_skill_markdown(bundle_slug: str) -> str:
    bundle_root = bundle_root_dir(bundle_slug)
    if bundle_root is None:
        return ""

    skill_path = bundle_root / _BUNDLE_SKILL_FILE_PATH
    if not skill_path.is_file():
        return ""
    return skill_path.read_text(encoding="utf-8")


def _format_persisted_result(
    persisted_workflows: list[PersistedWorkflow],
    *,
    bundle_slug: str,
    index_json: str,
    build_log: list[dict[str, Any]],
) -> dict[str, Any]:
    """Format compiled or appended workflows as a response dictionary."""
    if not persisted_workflows:
        raise ValueError("No workflows were persisted.")

    result = persisted_workflows[0].to_response_dict()
    result["index_json"] = index_json
    result["skill_md"] = _read_bundle_skill_markdown(bundle_slug)
    result["workflow_names"] = [item.name for item in persisted_workflows]
    result["build_log"] = build_log
    return result


def _build_skill_package_transaction(
    json_text: str,
    package_name: str | None,
    bundle_slug: str | None,
    build_log: list[dict[str, Any]],
) -> dict[str, Any]:
    skill_pack_log_append({"kind": "preprocess_phase", "state": "start", "input_bytes": len(json_text.encode("utf-8"))})
    payload = _prepare_skill_package_payload(json_text)
    payload_json = json.dumps(payload, ensure_ascii=False)
    skill_pack_log_append({
        "kind": "preprocess_phase",
        "state": "done",
        "output_bytes": len(payload_json.encode("utf-8")),
        "before_chars": len(json_text),
        "after_chars": len(payload_json),
        "removed_chars": len(json_text) - len(payload_json),
    })
    resolved_bundle_slug = _resolve_bundle_slug(bundle_slug)

    _log_persist_phase_start(resolved_bundle_slug, package_name)

    compiled_workflows = _compile_skill_package_payloads(payload, package_name=package_name)
    _ensure_new_workflow_names(resolved_bundle_slug, compiled_workflows)

    with _bundle_write_lock(resolved_bundle_slug):
        persisted_workflows = _persist_compiled_workflows(compiled_workflows, resolved_bundle_slug)
        refreshed_index_json = _refresh_bundle_runtime_files(resolved_bundle_slug)

    result = _format_persisted_result(
        persisted_workflows,
        bundle_slug=resolved_bundle_slug,
        index_json=refreshed_index_json,
        build_log=build_log,
    )
    skill_pack_log_append({"kind": "persist_phase", "state": "done", "workflow_names": result["workflow_names"]})
    return result


def build_skill_package(
    json_text: str,
    package_name: str | None = None,
    *,
    bundle_slug: str | None = None,
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    with skill_pack_build_log_scope(realtime_sink=realtime_sink) as build_log:
        try:
            return _build_skill_package_transaction(json_text, package_name, bundle_slug, build_log)
        except SkillPackBuildUserError:
            raise
        except (ValueError, OSError) as exc:
            raise SkillPackBuildUserError(str(exc), list(build_log)) from exc


def _decode_visual_assets_from_package_files(files: dict[str, str]) -> dict[str, bytes]:
    decoded: dict[str, bytes] = {}
    for filename, encoded in files.items():
        if not filename.startswith("visuals/"):
            continue
        leaf = Path(filename).name
        if not leaf or leaf.startswith("."):
            continue
        if Path(leaf).suffix.lower() not in VISUAL_IMAGE_SUFFIXES:
            continue
        try:
            decoded[leaf] = base64.standard_b64decode(encoded)
        except Exception:
            continue
    return decoded


def _parse_existing_inputs(inputs_raw: str) -> list[dict[str, Any]]:
    if not str(inputs_raw or "").strip():
        return []
    try:
        parsed = _parse_json_text(inputs_raw)
    except ValueError:
        return []
    if isinstance(parsed, dict):
        items = parsed.get("inputs")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def append_workflow_to_skill_package(
    bundle_slug: str,
    json_text: str,
    appended_package_name: str | None = None,
    *,
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    slug = _resolve_bundle_slug(bundle_slug)
    bundle_root = bundle_root_dir(slug)
    if bundle_root is None or not bundle_root.is_dir():
        raise ValueError("Skill package bundle not found.")

    with skill_pack_build_log_scope(realtime_sink=realtime_sink) as build_log:
        try:
            payload = _prepare_skill_package_payload(json_text)
            compiled_workflows = _compile_skill_package_payloads(payload, package_name=appended_package_name)
            _ensure_new_workflow_names(slug, compiled_workflows)
            for compiled in compiled_workflows:
                compiled.warnings = [f'Added workflow "{compiled.name}" to bundle "{slug}".']
            with _bundle_write_lock(slug):
                persisted = _persist_compiled_workflows(compiled_workflows, slug)
                index_json = _refresh_bundle_runtime_files(slug)
            return _format_persisted_result(
                persisted,
                bundle_slug=slug,
                index_json=index_json,
                build_log=build_log,
            )
        except SkillPackBuildUserError:
            raise
        except ValueError as exc:
            raise SkillPackBuildUserError(str(exc), list(build_log)) from exc


def build_skill_package_zip(
    package_name: str,
    skill_md: str,
    inputs_json: str,
    manifest_json: str,
    execution_json: str = "",
    recovery_json: str = "",
    *,
    skill_pack_bundle: str | None = None,
) -> tuple[str, bytes]:
    from app.storage.skill_packages import (
        _EXECUTOR_JS,
        _PACKAGE_JSON,
        _RECOVERY_JS,
        _TRACKER_JS,
        _VALIDATOR_JS,
        _ORCHESTRATION_SCHEMA_JSON,
        _orchestration_index_md,
        _orchestration_planner_md,
        _bundle_folder_name,
    )

    name = _slugify_name(package_name)
    bundle_segment = _resolve_bundle_slug(skill_pack_bundle)
    bundle_folder = _bundle_folder_name(bundle_segment)
    if not inputs_json.strip() or not manifest_json.strip():
        raise ValueError("inputs.json and manifest.json are required for export.")
    if not execution_json.strip() or not recovery_json.strip():
        raise ValueError("execution.json and recovery.json are required for export.")
    manifest_json = _normalize_manifest_json(manifest_json, inputs_json, name)
    visual_assets = read_skill_package_visual_asset_bytes(bundle_segment, name)

    try:
        parsed_plan = _parse_json_text(execution_json)
    except ValueError as exc:
        raise ValueError("execution.json must be valid JSON.") from exc
    if not isinstance(parsed_plan, list):
        raise ValueError("execution.json must be a JSON array.")
    if not all(isinstance(step, dict) for step in parsed_plan):
        raise ValueError("execution.json steps must be objects.")
    _validate_execution_plan(parsed_plan)

    inputs_list = _parse_existing_inputs(inputs_json)
    auth_config = infer_auth_config(inputs_list)
    sensitive = [i for i in inputs_list if i.get("sensitive")]
    description = _manifest_description(name, json.loads(manifest_json).get("description", ""))

    plugin_index = format_plugin_index_json(
        bundle_segment,
        [{"name": name, "description": description}],
    )
    readme = format_plugin_readme_text(bundle_segment, [{"name": name, "description": description}])
    test_cases = format_test_cases_stub_json_text(inputs_list)

    heading = description or name.replace("_", " ").title()
    skill_md_lines = [f"# {heading}", "", "## Inputs"]
    if inputs_list:
        for item in inputs_list:
            suffix = " Keep this value secure." if item.get("sensitive") else ""
            skill_md_lines.append(f"- `{{{{{item['name']}}}}}`: Enter {item['name'].replace('_', ' ')}.{suffix}")
    else:
        skill_md_lines.append("- No runtime inputs are required.")
    skill_md_lines.extend(["", "Execution: `../../execution/executor.js`"])
    per_skill_skill_md = "\n".join(skill_md_lines).strip() + "\n"

    orch_index = _orchestration_index_md(
        bundle_segment.replace("_", " ").title(), bundle_segment, [name]
    )
    orch_planner = _orchestration_planner_md(bundle_segment)

    buffer = BytesIO()
    skill_root = f"{bundle_folder}/skills/{name}"
    plugin_slug = bundle_segment
    skill_names = [name]
    claude_md = _generate_claude_md_text(plugin_slug, skill_names)
    setup_md = _generate_setup_md_text(plugin_slug)

    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(f"{bundle_folder}/{bundle_segment}.json", plugin_index)
        archive.writestr(f"{bundle_folder}/README.md", readme)
        archive.writestr(f"{bundle_folder}/CLAUDE.md", claude_md)
        archive.writestr(f"{bundle_folder}/SETUP.md", setup_md)
        archive.writestr(f"{bundle_folder}/auth/auth.json", format_auth_json_text(auth_config))
        archive.writestr(f"{bundle_folder}/auth/credentials.example.json", format_credentials_example_json_text(sensitive))
        archive.writestr(f"{bundle_folder}/orchestration/index.md", orch_index)
        archive.writestr(f"{bundle_folder}/orchestration/planner.md", orch_planner)
        archive.writestr(f"{bundle_folder}/orchestration/schema.json", _ORCHESTRATION_SCHEMA_JSON + "\n")
        archive.writestr(f"{bundle_folder}/package.json", _PACKAGE_JSON)
        archive.writestr(f"{bundle_folder}/execution/executor.js", _EXECUTOR_JS)
        archive.writestr(f"{bundle_folder}/execution/recovery.js", _RECOVERY_JS)
        archive.writestr(f"{bundle_folder}/execution/tracker.js", _TRACKER_JS)
        archive.writestr(f"{bundle_folder}/execution/validator.js", _VALIDATOR_JS)
        archive.writestr(f"{skill_root}/SKILL.md", per_skill_skill_md)
        archive.writestr(f"{skill_root}/manifest.json", manifest_json)
        archive.writestr(f"{skill_root}/execution.json", execution_json)
        archive.writestr(f"{skill_root}/input.json", inputs_json)
        archive.writestr(f"{skill_root}/recovery.json", recovery_json)
        archive.writestr(f"{skill_root}/tests/test-cases.json", test_cases)
        if visual_assets:
            for filename, content in sorted(visual_assets.items()):
                archive.writestr(f"{skill_root}/visuals/{Path(filename).name}", content)
    archive_name_root = bundle_segment.replace("/", "_").replace("\\", "_")
    return f"{archive_name_root}_{name}.zip", buffer.getvalue()


def zip_skill_bundle_from_disk(bundle_slug: str) -> tuple[str, bytes]:
    """Write every file under ``output/skill_package/<bundle_slug>/`` into one ZIP.

    Archive paths are rooted at ``<bundle_slug>/`` (the skill package name), matching the download filename
    ``<slug>.zip``. On-disk layout under ``output/skill_package/`` is not recreated inside the ZIP.
    """
    slug = _resolve_bundle_slug(bundle_slug)
    bundle_path = bundle_root_dir(slug)
    if bundle_path is None or not bundle_path.is_dir():
        raise ValueError("Skill package bundle not found.")
    zip_prefix = slug
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(bundle_path.rglob("*")):
            if path.is_file():
                rel = path.relative_to(bundle_path).as_posix()
                while rel.startswith(f"{slug}/"):
                    rel = rel[len(slug) + 1:]
                arcname = f"{zip_prefix}/{rel}"
                archive.write(path, arcname)
    return f"{slug}.zip", buffer.getvalue()
