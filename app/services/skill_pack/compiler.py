"""Structured step validation, deterministic execution, recovery, and docs generation."""

from __future__ import annotations

import base64
import copy
import json
import logging
import re
import tempfile
import time
from collections.abc import Callable, Iterable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

from app.compiler.action_policy import RECOVERY_ACTION_TYPES
from app.services.skill_pack_build_log import skill_pack_build_log_scope, skill_pack_log_append
from app.services.skill_pack.llm import _call_structuring_llm
from app.services.skill_pack.payload import sanitize_raw_steps_for_llm
from app.services.skill_pack.models import RawWorkflow, CompiledWorkflow, PersistedWorkflow
from app.storage.skill_packages import (
    VISUAL_IMAGE_SUFFIXES,
    _bundle_folder_name,
    _bundle_write_lock,
    _sanitize_segment,
    _write_bundle_index,
    bundle_root_dir,
    format_plugin_index_json,
    format_plugin_readme_text,
    read_skill_package_visual_asset_bytes,
    resolve_workflow_dir,
    validate_bundle_slug,
    write_skill_package_files_unlocked,
)

from .common import (
    _ALLOWED_STRUCTURED_TYPES,
    _CHECK_KINDS,
    _DESTRUCTIVE_TEXT,
    _GENERIC_LABELS,
    _GENERIC_SELECTORS,
    _INPUT_CONTAINER_KEYS,
    _INPUT_DECLARATION_KEYS,
    _INPUT_NAME_KEYS,
    _INPUT_NAME_RE,
    _LOGIN_TEXT,
    _METADATA_KEYS,
    _RECOVERY_VISUAL_SUFFIXES,
    _SELECTOR_ONLY_STEP_TYPES,
    _SENSITIVE_HINTS,
    _STEP_CONTAINER_KEYS,
    _STEP_LIST_KEYS,
    _STEP_SCREENSHOT_URL_KEYS,
    _STEP_VISUAL_KEYS,
    _TEXT_INPUT_STEP_TYPES,
    _TEXT_SELECTOR_RE,
    _TITLE_KEYS,
    _VAR_PATTERN,
    _first_text_from_keys,
    _get_mapping,
    _humanize_name,
    _json_text,
    _normalize_name,
    _parse_json_text,
    _slugify_name,
    slugify_skill_bundle_name,
    slugify_skill_package_folder_name,
)


_URL_DYNAMIC_SEG = re.compile(
    r"^(?:[0-9]+|[0-9a-f]{8,}|[A-Za-z0-9_-]{16,})$"
)
_URL_VOLATILE_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ts", "_", "t", "ref",
})


def _normalize_url_pattern(url: str) -> str:
    """Convert a literal URL into a stable regex pattern for runtime validation.

    Rules:
    - Path segments matching a numeric, hex-hash, or long-alphanumeric ID are replaced with [^/]+.
    - Volatile query params (utm_*, ts, _, t, ref) are dropped.
    - Host and scheme are kept literal (regex-escaped).
    - Returns empty string for empty/invalid input.
    """
    url = str(url or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        host_part = re.escape(parsed.scheme + "://" + parsed.netloc)
        segments = parsed.path.split("/")
        normalized = [
            "[^/]+" if _URL_DYNAMIC_SEG.match(seg) else re.escape(seg)
            for seg in segments
        ]
        path_pattern = "/".join(normalized)
        qs = [(k, v) for k, v in parse_qsl(parsed.query) if k not in _URL_VOLATILE_PARAMS and not k.startswith("utm_")]
        query_suffix = ("\\?" + re.escape(urlencode(qs))) if qs else ""
        return f"^{host_part}{path_pattern}{query_suffix}$"
    except Exception:
        return ""


def _selector_text(selector: str) -> str:
    match = _TEXT_SELECTOR_RE.match(selector or "")
    if match:
        return " ".join(
            next(group for group in match.groups() if group is not None).strip().split()
        )
    match = _INPUT_NAME_RE.search(selector or "")
    if match:
        return _humanize_name(_normalize_name(match.group(1)))
    return ""


def _is_xpath(selector: str) -> bool:
    text = (selector or "").strip()
    return (
        text.startswith("/")
        or text.startswith("./")
        or text.startswith("//")
        or text.lower().startswith("xpath=")
    )


def _is_generic_selector(selector: str) -> bool:
    return (selector or "").strip().lower() in _GENERIC_SELECTORS


def _validate_selector(selector: str, *, step_type: str) -> str:
    text = str(selector or "").strip()
    if not text:
        raise ValueError(f"{step_type} step is missing selector.")
    if _is_xpath(text) or "xpath" in text.lower():
        raise ValueError("Selectors must not contain XPath.")
    if _is_generic_selector(text):
        raise ValueError(f"Generic selector is not allowed: {text}")
    if step_type == "fill" and not _INPUT_NAME_RE.search(text):
        # Repair: text=Foo → input[placeholder="Foo"] (LLM often parrots text selectors for inputs)
        m = _TEXT_SELECTOR_RE.match(text)
        if m:
            label = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if label:
                repaired = f'input[placeholder="{label}"]'
                skill_pack_log_append({
                    "kind": "debug_fill_selector_repaired",
                    "original": text,
                    "repaired": repaired,
                })
                text = repaired
            else:
                skill_pack_log_append({
                    "kind": "debug_fill_selector_rejected",
                    "selector": text,
                    "reason": "text= selector had empty label",
                })
                raise ValueError(
                    "Fill selectors must use input[name=...], input[aria-label=...], or input[placeholder=...]."
                )
        else:
            skill_pack_log_append({
                "kind": "debug_fill_selector_rejected",
                "selector": text,
                "reason": "not input[name/aria-label/placeholder] and not text= pattern",
            })
            raise ValueError(
                "Fill selectors must use input[name=...], input[aria-label=...], or input[placeholder=...]."
            )
    if step_type == "click" and text.lower() == "button":
        raise ValueError("Click selectors must use visible text, such as text=Sign in.")
    return text


def _normalize_check_kind(kind: Any) -> str:
    text = _json_text(kind or "url").strip().lower().replace("-", "_")
    if text in {"url_must_be", "url_must", "exact_url"}:
        return "url_exact"
    return text


def _parse_optional_float(
    value: Any, *, step_type: str, field: str, index: int
) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{step_type} step at index {index}: {field} must be a number."
        ) from exc


def _canonical_navigate_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    url = _json_text(step.get("url"))
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError(
            f"Navigate step at index {index} requires an absolute HTTP(S) URL."
        )
    return {"type": "navigate", "url": url}


def _canonical_text_input_step(
    step: dict[str, Any], step_type: str, index: int
) -> dict[str, Any]:
    raw_selector = _json_text(step.get("selector"))
    skill_pack_log_append({
        "kind": "debug_fill_step_incoming",
        "index": index,
        "raw_selector": raw_selector,
        "value_preview": str(_json_text(step.get("value")))[:60],
    })
    selector = _validate_selector(raw_selector, step_type="fill")
    value = _json_text(step.get("value"))
    if not value:
        raise ValueError(f"{step_type} step at index {index} requires a value.")
    return {"type": step_type, "selector": selector, "value": value}


def _canonical_selector_only_step(
    step: dict[str, Any], step_type: str
) -> dict[str, Any]:
    selector = _validate_selector(_json_text(step.get("selector")), step_type="click")
    out = {"type": step_type, "selector": selector}
    if step_type == "select":
        value = _json_text(step.get("value"))
        if value:
            out["value"] = value
    return out


def _canonical_scroll_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    selector_raw = _json_text(step.get("selector")).strip()
    dy = _parse_optional_float(
        step.get("delta_y"), step_type="Scroll", field="delta_y", index=index
    )
    dx = _parse_optional_float(
        step.get("delta_x", 0), step_type="Scroll", field="delta_x", index=index
    )
    dx = dx or 0.0

    has_selector = bool(selector_raw)
    has_wheel = (dy is not None and dy != 0.0) or dx != 0.0
    if not has_selector and not has_wheel:
        raise ValueError(
            f"Scroll step at index {index} requires a selector and/or non-zero delta_y / delta_x."
        )

    out: dict[str, Any] = {"type": "scroll"}
    if has_selector:
        out["selector"] = _validate_selector(selector_raw, step_type="click")
        return out
    if dy is not None:
        out["delta_y"] = dy
    if dx != 0.0:
        out["delta_x"] = dx
    return out


def _canonical_wait_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    selector_raw = _json_text(step.get("selector")).strip()
    if selector_raw:
        raise ValueError(f"Wait step at index {index} must not include selector.")
    out: dict[str, Any] = {"type": "wait"}
    raw_ms = step.get("ms", step.get("value"))
    if raw_ms not in (None, ""):
        try:
            out["ms"] = max(0, int(raw_ms))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Wait step at index {index}: ms must be an integer.") from exc
    return out


def _canonical_check_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    kind = _normalize_check_kind(step.get("kind") or step.get("check_kind") or "url")
    if kind not in _CHECK_KINDS:
        raise ValueError(f"Check step at index {index} has unsupported kind: {kind}")

    out: dict[str, Any] = {"type": "check", "kind": kind}
    if kind == "url":
        pattern = _json_text(step.get("pattern") or step.get("check_pattern"))
        if not pattern:
            raise ValueError(f"Check url step at index {index} requires pattern.")
        out["pattern"] = pattern
    elif kind == "url_exact":
        expected_url = _json_text(
            step.get("url")
            or step.get("expected_url")
            or step.get("pattern")
            or step.get("check_pattern")
        )
        if not expected_url:
            raise ValueError(f"Check url_exact step at index {index} requires url.")
        out["url"] = expected_url
    elif kind == "snapshot":
        threshold = _parse_optional_float(
            step.get("threshold", step.get("check_threshold", 0.9)),
            step_type="Check snapshot",
            field="threshold",
            index=index,
        )
        if threshold is None:
            raise ValueError(
                f"Check snapshot step at index {index}: threshold must be a number."
            )
        out["threshold"] = threshold
    elif kind == "selector":
        out["selector"] = _validate_selector(
            _json_text(step.get("selector") or step.get("check_selector")),
            step_type="click",
        )
    elif kind == "text":
        text = _json_text(step.get("text") or step.get("check_text"))
        if not text:
            raise ValueError(f"Check text step at index {index} requires text.")
        out["text"] = text
    return out


def _canonical_click_step(step: dict[str, Any]) -> dict[str, Any]:
    selector = _validate_selector(_json_text(step.get("selector")), step_type="click")
    return {"type": "click", "selector": selector}


def _canonical_v2_step(step: dict[str, Any]) -> dict[str, Any]:
    """Generic passthrough for v2 action kinds — preserves type, selector, and value."""
    step_type = str(step.get("type") or "").strip().lower()
    out: dict[str, Any] = {"type": step_type}
    selector = _json_text(step.get("selector"))
    if selector:
        out["selector"] = selector
    value = step.get("value")
    if value is not None:
        out["value"] = value
    return out


def _canonical_upload_step(step: dict[str, Any]) -> dict[str, Any]:
    """Transform upload_intent → upload with a {{variable}} the caller fills with a file path."""
    selector = _json_text(step.get("selector"))
    var_name = "file_path"
    raw_value = step.get("value") or ""
    if raw_value:
        try:
            files = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            if isinstance(files, list) and files:
                fname = str(files[0].get("name") or "")
                if fname:
                    base = fname.rsplit(".", 1)[0] if "." in fname else fname
                    var_name = _normalize_name(base) or "file_path"
        except Exception:
            pass
    out: dict[str, Any] = {"type": "upload", "value": f"{{{{{var_name}}}}}"}
    if selector:
        out["selector"] = selector
    return out


def _canonical_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    step_type = str(step.get("type") or "").strip().lower()
    if step_type not in _ALLOWED_STRUCTURED_TYPES:
        raise ValueError(
            f"Unsupported structured step type at index {index}: {step.get('type')}"
        )
    if step_type == "navigate":
        out = _canonical_navigate_step(step, index)
    elif step_type in _TEXT_INPUT_STEP_TYPES:
        out = _canonical_text_input_step(step, step_type, index)
    elif step_type in _SELECTOR_ONLY_STEP_TYPES:
        out = _canonical_selector_only_step(step, step_type)
    elif step_type == "scroll":
        out = _canonical_scroll_step(step, index)
    elif step_type == "wait":
        out = _canonical_wait_step(step, index)
    elif step_type == "check":
        out = _canonical_check_step(step, index)
    elif step_type == "click":
        out = _canonical_click_step(step)
    elif step_type == "upload_intent":
        out = _canonical_upload_step(step)
    else:
        out = _canonical_v2_step(step)
    frame = _sanitize_runtime_frame(step.get("frame"))
    if frame:
        out["frame"] = frame
    return out


def _validate_structured_output(structured: dict[str, Any]) -> dict[str, Any]:
    goal = _json_text(structured.get("goal"))
    raw_steps = structured.get("steps")
    if not goal:
        raise ValueError("LLM structured output must include a goal.")
    if not isinstance(raw_steps, list):
        raise ValueError("LLM structured output must include steps array.")

    steps = [
        _canonical_step(step, index)
        for index, step in enumerate(raw_steps, start=1)
        if isinstance(step, dict)
    ]
    if len(steps) != len(raw_steps):
        raise ValueError("Every LLM structured step must be a JSON object.")
    if not steps:
        raise ValueError("LLM structured output contains no executable steps.")
    return {"goal": goal, "steps": steps}


def _append_step(plan: list[dict[str, Any]], step: dict[str, Any]) -> None:
    if plan and plan[-1] == step:
        return
    plan.append(step)


def compile_execution(
    structured_steps: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compile validated structured steps into runtime execution steps."""

    steps = (
        structured_steps.get("steps", [])
        if isinstance(structured_steps, dict)
        else structured_steps
    )
    if not isinstance(steps, list):
        raise ValueError(
            "Structured steps must be a list or an object containing steps."
        )

    plan: list[dict[str, Any]] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            raise ValueError("Structured execution step must be an object.")
        step = _canonical_step(raw_step, len(plan) + 1)
        _append_step(plan, step)
    return plan


def _selector_target(step: dict[str, Any]) -> dict[str, str]:
    selector = str(step.get("selector") or "")
    text = _selector_text(selector)
    role = "textbox" if step.get("type") in {"fill", "type"} else ""
    return {"text": text, "role": role}


def _recovery_slug_from_step(step: dict[str, Any]) -> str:
    target = _selector_target(step)
    raw = " ".join(
        part
        for part in (
            str(step.get("type") or ""),
            target["text"] or target["role"] or "action",
        )
        if part
    )
    return _normalize_name(raw)


def _fallback_text_variants(text: str) -> list[str]:
    variants: list[str] = []
    if text:
        variants.append(text)
    lowered = text.lower()
    if "delete" in lowered:
        variants.extend(["Delete", "Remove"])
    elif "remove" in lowered:
        variants.extend(["Remove", "Delete"])
    elif any(token in lowered for token in _LOGIN_TEXT):
        variants.extend(["Sign in", "Log in"])
    elif "continue" in lowered:
        variants.extend(["Continue", "Next"])
    elif "next" in lowered:
        variants.extend(["Next", "Continue"])
    elif "save" in lowered:
        variants.extend(["Save", "Update"])

    out: list[str] = []
    for item in variants:
        clean = " ".join(item.split())
        if clean and clean.lower() not in _GENERIC_LABELS and clean not in out:
            out.append(clean)
    return out[:4]


def _sanitize_recovery_label(value: Any) -> str:
    clean = " ".join(str(value or "").split())
    if not clean:
        return ""
    if clean.lower() in _GENERIC_LABELS:
        return ""
    return clean


def _sanitize_recovery_selector(selector: Any) -> str:
    text = str(selector or "").strip()
    if not text:
        return ""
    if _is_xpath(text) or "xpath" in text.lower():
        return ""
    lowered = text.lower()
    if lowered.startswith(".") or "[class" in lowered or "class=" in lowered:
        return ""
    return text


def _selector_alternatives(step: dict[str, Any], target: dict[str, str]) -> list[str]:
    selector = _sanitize_recovery_selector(step.get("selector"))
    if not selector:
        return []
    out: list[str] = []
    text = _sanitize_recovery_label(target.get("text"))
    if selector.lower().startswith("text=") and text:
        out.append(f"text={json.dumps(text)}")
    if step.get("type") in {"fill", "type"}:
        match = _INPUT_NAME_RE.search(selector)
        if match:
            name = match.group(1).strip()
            out.append(f'input[name="{name}"]')
    deduped: list[str] = []
    seen: set[str] = set()
    for item in out:
        clean = _sanitize_recovery_selector(item)
        if clean and clean != selector and clean not in seen:
            seen.add(clean)
            deduped.append(clean)
    return deduped


def _anchors_for_step(
    step: dict[str, Any], target: dict[str, str]
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    target_text = _sanitize_recovery_label(target.get("text"))
    lowered = target_text.lower()
    if any(token in lowered for token in _LOGIN_TEXT):
        anchors.append({"text": "Login", "priority": 1})
    if any(token in lowered for token in _DESTRUCTIVE_TEXT):
        anchors.append({"text": "Danger Zone", "priority": 1})
    if step.get("type") in {"fill", "type"} and target_text:
        anchors.append({"text": target_text, "priority": 2})
    elif step.get("type") in {"click", "select", "focus"} and target_text:
        anchors.append({"text": target_text, "priority": 2})
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in anchors:
        text = _sanitize_recovery_label(anchor.get("text"))
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append({"text": text, "priority": int(anchor.get("priority") or 1)})
    return deduped[:4]


def get_visual_ref(step_id: int, visuals_dir: Path) -> str | None:
    for suffix in _RECOVERY_VISUAL_SUFFIXES:
        path = visuals_dir / f"Image_{step_id}{suffix}"
        if path.is_file():
            return f"visuals/{path.name}"
    return None


def _build_recovery_entry(
    step: dict[str, Any], step_id: int, visuals_dir: Path | None
) -> dict[str, Any]:
    from app.config import settings

    selector = _sanitize_recovery_selector(step.get("selector"))
    if not selector:
        raise ValueError(f"Recovery step {step_id} is missing a valid selector.")
    target = _selector_target(step)
    target_text = _sanitize_recovery_label(target.get("text"))
    fallback_role = target.get("role") or ""

    anchors = _anchors_for_step(step, target)

    if settings.pack_recovery_vision_enabled and visuals_dir is not None:
        from app.llm.anchor_vision_llm import generate_anchors_from_image_bytes
        from app.policy.bundle import get_policy_bundle

        visual_ref = get_visual_ref(step_id, visuals_dir)
        if visual_ref:
            try:
                image_path = visuals_dir / f"Image_{step_id}.*"
                for suffix in _RECOVERY_VISUAL_SUFFIXES:
                    candidate = visuals_dir / f"Image_{step_id}{suffix}"
                    if candidate.is_file():
                        image_bytes = candidate.read_bytes()
                        intent = _recovery_slug_from_step(step)
                        pol = get_policy_bundle().data
                        vision_anchors = generate_anchors_from_image_bytes(
                            image_bytes, intent, step_id, policy=pol
                        )
                        if vision_anchors:
                            anchors = vision_anchors + anchors
                        break
            except Exception:
                pass

    entry: dict[str, Any] = {
        "step_id": step_id,
        "intent": _recovery_slug_from_step(step),
        "target": {
            "text": target_text,
            "role": target.get("role") or "",
        },
        "anchors": anchors,
        "fallback": {
            "text_variants": _fallback_text_variants(target_text),
            "role": fallback_role,
        },
        "selector_context": {
            "primary": selector,
            "alternatives": _selector_alternatives(step, target),
        },
        "visual_metadata": {
            "step_id": step_id,
            "source": "stored_step_visual",
            "available": False,
        },
        "recovery_metadata": {
            "mode": "tiered",
            "action_type": str(step.get("type") or ""),
            "generated_by": "skill_pack_builder",
        },
    }
    if visuals_dir is not None:
        visual_ref = get_visual_ref(step_id, visuals_dir)
        if visual_ref:
            entry["visual_ref"] = visual_ref
            entry["visual_metadata"]["available"] = True
    return entry


def _validate_recovery_entries(
    compiled: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    visuals_dir: Path | None,
) -> None:
    actionable_steps = [
        index
        for index, step in enumerate(compiled, start=1)
        if str(step.get("type") or "") in RECOVERY_ACTION_TYPES
    ]
    if len(entries) != len(actionable_steps):
        raise ValueError(
            "Every compiled recovery-eligible step must have exactly one recovery entry."
        )
    by_step_id: dict[int, list[dict[str, Any]]] = {}
    for entry in entries:
        by_step_id.setdefault(int(entry.get("step_id") or 0), []).append(entry)
        if not str(entry.get("intent") or "").strip():
            raise ValueError("Recovery entries must include intent.")
        anchors = entry.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise ValueError("Recovery entries must include anchors.")
        if not all(
            _sanitize_recovery_label(_get_mapping(anchor).get("text"))
            for anchor in anchors
        ):
            raise ValueError("Recovery anchors must use non-generic text labels.")
        fallback = _get_mapping(entry.get("fallback"))
        text_variants = fallback.get("text_variants")
        if not isinstance(text_variants, list) or not text_variants:
            raise ValueError("Recovery fallback.text_variants is required.")
        if not all(_sanitize_recovery_label(item) for item in text_variants):
            raise ValueError(
                "Recovery fallback.text_variants must be non-generic labels."
            )
        selector_context = _get_mapping(entry.get("selector_context"))
        primary = _sanitize_recovery_selector(selector_context.get("primary"))
        alternatives = selector_context.get("alternatives")
        if not primary or not isinstance(alternatives, list):
            raise ValueError(
                "Recovery selector_context must include primary and alternatives."
            )
        if any(not _sanitize_recovery_selector(item) for item in alternatives):
            raise ValueError(
                "Recovery selector_context alternatives must be valid selectors."
            )
        if "validation" in json.dumps(entry, ensure_ascii=False).lower():
            raise ValueError("Recovery entries must not include validation data.")
        if "scroll" in json.dumps(entry, ensure_ascii=False).lower():
            raise ValueError("Recovery entries must not include scroll data.")
        if visuals_dir is None:
            if "visual_ref" in entry:
                raise ValueError("visual_ref requires an existing visuals directory.")
        else:
            expected_ref = get_visual_ref(int(entry["step_id"]), visuals_dir)
            actual_ref = entry.get("visual_ref")
            if actual_ref and actual_ref != expected_ref:
                raise ValueError(
                    "visual_ref must point to the matching Image_<step_id> asset."
                )
            if expected_ref is None and actual_ref:
                raise ValueError(
                    "visual_ref must be omitted when the step image is missing."
                )
            if expected_ref is not None and actual_ref != expected_ref:
                raise ValueError(
                    "visual_ref must be present only for matching step images."
                )
    for step_id in actionable_steps:
        if len(by_step_id.get(step_id, [])) != 1:
            raise ValueError(
                "Every compiled recovery-eligible step must have exactly one recovery entry."
            )


def generate_recovery(
    structured_steps: dict[str, Any] | list[dict[str, Any]],
    visuals_dir: Path | None = None,
) -> dict[str, Any]:
    compiled = compile_execution(structured_steps)
    entries: list[dict[str, Any]] = []
    for index, step in enumerate(compiled, start=1):
        if str(step.get("type") or "") not in RECOVERY_ACTION_TYPES:
            continue
        entries.append(_build_recovery_entry(step, index, visuals_dir))
    _validate_recovery_entries(compiled, entries, visuals_dir)
    return {"steps": entries}


def _iter_declared_input_names(payload: Any) -> Iterable[str]:
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    for container in (
        payload,
        *(_get_mapping(payload.get(key)) for key in _METADATA_KEYS),
    ):
        for input_key in _INPUT_CONTAINER_KEYS:
            items = container.get(input_key)
            if isinstance(items, dict):
                found.extend(str(key) for key in items.keys())
                items = list(items.values())
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        found.append(item)
                    elif isinstance(item, dict):
                        value = _first_text_from_keys(item, _INPUT_NAME_KEYS)
                        if value:
                            found.append(value)
    return found


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _SENSITIVE_HINTS)


def parse_inputs(payload: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    ordered: list[str] = []

    for raw in _VAR_PATTERN.findall(json.dumps(payload, ensure_ascii=False)):
        name = _normalize_name(raw)
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    for raw in _iter_declared_input_names(payload):
        name = _normalize_name(raw)
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    out: list[dict[str, Any]] = []
    for name in ordered:
        row: dict[str, Any] = {
            "name": name,
            "type": "string",
            "description": f"Enter {_humanize_name(name)}",
        }
        if _is_sensitive_name(name):
            row["sensitive"] = True
        out.append(row)
    return out


def _manifest_description(package_name: str, description: str = "") -> str:
    clean = " ".join(str(description or "").split())
    if clean:
        return clean
    return f"Run the {package_name.replace('_', ' ')} workflow."


def build_manifest(
    inputs: list[dict[str, Any]], package_name: str, description: str = ""
) -> dict[str, Any]:
    return {
        "name": package_name,
        "description": _manifest_description(package_name, description),
        "version": "1.0.0",
        "entry": {
            "execution": "./execution.json",
            "recovery": "./recovery.json",
            "input": "./input.json",
        },
        "execution_mode": "deterministic",
        "recovery_mode": "tiered",
        "vision_enabled": True,
        "llm_required": False,
        "inputs": [
            {
                "name": str(item.get("name") or ""),
                "type": str(item.get("type") or "string"),
                **({"sensitive": True} if item.get("sensitive") else {}),
            }
            for item in inputs
            if str(item.get("name") or "").strip()
        ],
    }


generate_manifest = build_manifest


def _normalize_manifest_json(
    manifest_json: str, inputs_json: str, package_name: str, description: str = ""
) -> str:
    try:
        manifest = _parse_json_text(manifest_json) if manifest_json.strip() else {}
    except ValueError as exc:
        raise ValueError("manifest.json must be valid JSON.") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must be a JSON object.")

    parsed_inputs: list[dict[str, Any]] = []
    if inputs_json.strip():
        try:
            inputs_payload = _parse_json_text(inputs_json)
        except ValueError as exc:
            raise ValueError("inputs.json must be valid JSON.") from exc
        raw_inputs = (
            inputs_payload.get("inputs")
            if isinstance(inputs_payload, dict)
            else inputs_payload
        )
        if isinstance(raw_inputs, list):
            parsed_inputs = [item for item in raw_inputs if isinstance(item, dict)]

    normalized = build_manifest(
        parsed_inputs,
        str(manifest.get("name") or package_name),
        str(manifest.get("description") or description),
    )
    if isinstance(manifest.get("inputs"), list) and not parsed_inputs:
        normalized["inputs"] = manifest["inputs"]
    return json.dumps(normalized, ensure_ascii=False, indent=2)


def _instruction_for_step(step: dict[str, Any]) -> str:
    if step["type"] == "navigate":
        return (
            "Open login page"
            if any(token in step["url"].lower() for token in _LOGIN_TEXT)
            else f"Open {step['url']}"
        )
    if step["type"] == "scroll":
        sel_raw = str(step.get("selector") or "").strip()
        dy_val = step.get("delta_y")
        dx_val = float(step.get("delta_x") or 0)
        phrases: list[str] = []
        if sel_raw:
            label = _selector_text(sel_raw) or sel_raw
            phrases.append(
                f"Scroll to reveal {label}" if label else "Scroll element into view"
            )
        if dy_val is not None and float(dy_val) != 0.0:
            dy_f = float(dy_val)
            if dx_val != 0.0:
                phrases.append(f"Wheel scroll (Δy={dy_f:g}, Δx={dx_val:g})")
            else:
                phrases.append(f"Wheel scroll (Δy={dy_f:g})")
        elif dx_val != 0.0:
            phrases.append(f"Wheel scroll (Δx={dx_val:g})")
        return "; ".join(phrases) if phrases else "Scroll"
    target = _selector_target(step)
    text = target.get("text", "")
    if step["type"] in {"fill", "type"}:
        value = step.get("value", "")
        if value.startswith("{{") and value.endswith("}}"):
            return f"Enter {value}"
        return f"Enter {value}" if not text else f"Enter {value} in {text}"
    if step["type"] == "click":
        lowered = text.lower()
        if text.startswith("{{") and text.endswith("}}"):
            return f"Select {text}"
        if any(token in lowered for token in _DESTRUCTIVE_TEXT):
            return text
        return f'Click "{text or step["selector"]}"'
    if step["type"] == "select":
        return f"Select {step.get('value') or text or step['selector']}"
    if step["type"] == "focus":
        return f"Focus {text or step['selector']}"
    if step["type"] == "check":
        kind = str(step.get("kind") or "url")
        if kind == "url_exact":
            return "Check URL must be"
        return f"Check {kind}"
    return ""


def generate_skill_markdown(
    package_name: str,
    structured_steps: dict[str, Any],
    inputs: list[dict[str, Any]],
    *,
    document_title: str | None = None,
) -> str:
    heading = (document_title or "").strip() or _humanize_name(package_name).title()
    lines = [f"# {heading}", "", "## Inputs"]
    if inputs:
        for item in inputs:
            suffix = " Keep this value secure." if item.get("sensitive") else ""
            lines.append(f"- `{{{{{item['name']}}}}}`: {item['description']}.{suffix}")
    else:
        lines.append("- No runtime inputs are required.")

    lines.extend(["", "## Steps"])
    for index, step in enumerate(structured_steps["steps"], start=1):
        instruction = _instruction_for_step(step)
        if instruction:
            lines.append(f"{index}. {instruction}")
    return "\n".join(lines).strip() + "\n"


def _validate_execution_plan(plan: list[dict[str, Any]]) -> None:
    if not plan:
        raise ValueError("execution.json has no steps after LLM structuring.")
    has_click = False
    has_fill = False
    for index, step in enumerate(plan, start=1):
        if not isinstance(step, dict):
            raise ValueError("execution.json steps must be objects.")
        canonical = _canonical_step(step, index)
        step_type = canonical["type"]
        if step_type in _TEXT_INPUT_STEP_TYPES:
            has_fill = True
        elif step_type == "click":
            has_click = True
    serialized = json.dumps(plan, ensure_ascii=False).lower()
    if '"type": "wait"' in serialized or '"type":"wait"' in serialized:
        raise ValueError("execution.json must not contain wait steps.")
    if "xpath" in serialized or re.search(
        r'"selector"\s*:\s*"(?:/|//|\./)', serialized
    ):
        raise ValueError("execution.json must not contain XPath selectors.")
    if not has_click or not has_fill:
        raise ValueError(
            "execution.json must contain at least one click and one fill step."
        )


_logger = logging.getLogger(__name__)


class SkillPackBuildUserError(ValueError):
    """Validation or LLM failure with any ``build_log`` rows gathered so far."""

    def __init__(self, message: str, build_log: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.build_log = build_log


def _json_size_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _resolve_screenshot_full_url(step: dict[str, Any]) -> str | None:
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
    """Return a deep copy with unused declaration blocks removed from the whole tree."""
    root = copy.deepcopy(value)
    _preprocess_declaration_blocks_in_place(root)
    return root


def preprocess_plugin_json(plugin_json: dict | None) -> dict | None:
    """Return a normalized plugin JSON copy with redundant aliases removed."""
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


def _sanitize_runtime_frame(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    chain = raw.get("chain")
    if not isinstance(chain, list):
        return {}
    out_chain: list[dict[str, Any]] = []
    for item in chain:
        if not isinstance(item, dict):
            continue
        selector = str(item.get("selector") or "").strip()
        if not selector:
            continue
        fallbacks = [
            str(fb).strip()
            for fb in (item.get("fallback_selectors") or [])
            if str(fb or "").strip()
        ][:5]
        url = str(item.get("url") or "").strip()
        out_chain.append(
            {
                "selector": selector,
                "fallback_selectors": fallbacks,
                "url": url,
                "url_pattern": str(item.get("url_pattern") or _normalize_url_pattern(url)).strip(),
            }
        )
    return {"chain": out_chain} if out_chain else {}


def _extract_raw_frame(raw_step: dict[str, Any]) -> dict[str, Any]:
    return _sanitize_runtime_frame(raw_step.get("frame"))


def _selector_candidates_for_context_match(step: dict[str, Any]) -> list[str]:
    out: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip().lower()
        if text and text not in out:
            out.append(text)

    add(step.get("selector"))
    add(step.get("css_selector"))
    target = step.get("target") if isinstance(step.get("target"), dict) else {}
    add(target.get("primary_selector"))
    name = str(target.get("name") or "").strip()
    if name:
        add(f'input[name="{name}"]')
    aria = str(target.get("aria_label") or "").strip()
    if aria:
        add(f'input[aria-label="{aria}"]')
    placeholder = str(target.get("placeholder") or "").strip()
    if placeholder:
        add(f'input[placeholder="{placeholder}"]')
    selectors = step.get("selectors") if isinstance(step.get("selectors"), dict) else {}
    add(selectors.get("selector"))
    add(selectors.get("text_based"))
    add(selectors.get("css"))
    add(selectors.get("aria"))
    return out


def _selector_context_score(exec_step: dict[str, Any], raw_step: dict[str, Any]) -> float:
    exec_candidates = _selector_candidates_for_context_match(exec_step)
    raw_candidates = _selector_candidates_for_context_match(raw_step)
    best = 0.0
    for left in exec_candidates:
        for right in raw_candidates:
            if left == right:
                best = max(best, 1.0)
            elif left and right and (left in right or right in left):
                best = max(best, 0.5)
    return best


def _raw_context_for_execution_step(
    exec_step: dict[str, Any],
    raw_steps: list[dict[str, Any]],
    used_indices: set[int],
    fallback_index: int,
) -> tuple[int | None, dict[str, Any] | None]:
    best_index: int | None = None
    best_score = 0.0
    for idx, raw_step in enumerate(raw_steps):
        if idx in used_indices or not isinstance(raw_step, dict):
            continue
        score = _selector_context_score(exec_step, raw_step)
        if score > best_score:
            best_score = score
            best_index = idx
    if best_index is not None and best_score > 0:
        used_indices.add(best_index)
        return best_index, raw_steps[best_index]
    if 0 <= fallback_index < len(raw_steps):
        idx = fallback_index
        used_indices.add(idx)
        return idx, raw_steps[idx]
    return None, None


def _attach_recorded_frame_context_for_steps(
    execution_plan: list[dict[str, Any]],
    raw_steps: list[dict[str, Any]],
    _skill_name: str,
) -> list[dict[str, Any]]:
    usable_raw = [
        s
        for s in raw_steps
        if isinstance(s, dict) and _extract_raw_frame(s)
    ]

    augmented: list[dict[str, Any]] = []
    n_exec = len(execution_plan)
    used_raw_indices: set[int] = set()

    for exec_idx, step in enumerate(execution_plan, start=1):
        step_copy = copy.deepcopy(step)

        if usable_raw:
            ratio = (exec_idx - 1) / max(n_exec - 1, 1)
            fallback_idx = round(ratio * (len(usable_raw) - 1))
            _, raw_step = _raw_context_for_execution_step(
                step_copy,
                usable_raw,
                used_raw_indices,
                fallback_idx,
            )
            frame = _extract_raw_frame(raw_step or {})
            if frame:
                step_copy["frame"] = frame

        augmented.append(step_copy)

    return augmented


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
    """Post-process execution plan to fix common issues found in render-plugin."""
    if not plan:
        return plan

    fixed: list[dict[str, Any]] = []
    redirect_action_keywords = {"sign in", "login", "submit", "confirm", "delete", "logout"}

    for i, step in enumerate(plan):
        step_copy = copy.deepcopy(step)

        if step_copy.get("kind") in ("url_exact", "url_must_be") and i > 0:
            prev_step = plan[i - 1]
            prev_selector = (prev_step.get("selector") or "").lower()

            is_after_redirect_action = (
                prev_step.get("type") == "click"
                and any(keyword in prev_selector for keyword in redirect_action_keywords)
            )

            if is_after_redirect_action:
                step_copy["kind"] = "url"
                url_value = step_copy.get("url") or step_copy.get("pattern") or ""
                if "://" in url_value:
                    domain = url_value.split("://")[1].split("/")[0]
                    step_copy["pattern"] = domain
                    step_copy.pop("url", None)

        fixed.append(step_copy)

        if (
            step_copy.get("type") in ("fill", "type")
            and i + 1 < len(plan)
            and plan[i + 1].get("type") in ("click", "select", "focus")
        ):
            selector = step_copy.get("selector", "").lower()
            is_command_like = "command" in selector or "confirm" in selector or "sudo" in selector

            if is_command_like:
                fixed.append({
                    "type": "wait",
                    "ms": 3000,
                })

    return fixed


def _align_recovery_step_ids(recovery_map: dict[str, Any], execution_plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Ensure recovery.json step_ids exactly match execution.json step numbers."""
    if not isinstance(recovery_map, dict) or not isinstance(recovery_map.get("steps"), list):
        return recovery_map
    if not execution_plan:
        return recovery_map

    recovery_copy = copy.deepcopy(recovery_map)

    recoverable_types = {"fill", "type", "click", "select", "focus"}
    selector_to_exec_indices: dict[str, list[int]] = {}
    for exec_idx, exec_step in enumerate(execution_plan, start=1):
        if exec_step.get("type") not in recoverable_types:
            continue
        sel = (exec_step.get("selector") or "").strip()
        if sel:
            selector_to_exec_indices.setdefault(sel, []).append(exec_idx)

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

    unmatched: list[dict[str, Any]] = []
    for entry in recovery_copy["steps"]:
        primary = (entry.get("selector_context") or {}).get("primary", "").strip()
        new_id = _next_exec_idx_for_selector(primary) if primary else None

        if new_id is None:
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

    execution_plan = _fix_execution_plan(execution_plan)

    execution_plan = _attach_recorded_frame_context_for_steps(execution_plan, raw_steps, workflow_slug)

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
    visual_assets = _collect_visual_assets(payload)
    viz_count = len(visual_assets) if isinstance(visual_assets, dict) else 0
    _pipeline_phase_append("recovery_map", "start", workflow_title=workflow_title, visual_assets=viz_count)
    t_rec = time.perf_counter()
    recovery_map = _generate_recovery_with_visuals(structured, visual_assets)

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
        single = raw_workflows[0]
        label = str(single.title or "workflow_1")
        skill_pack_log_append({"kind": "workflow_compile_start", "index": 1, "total": 1, "title": label, "raw_steps": len(single.steps)})
        result = _compile_workflow_payload(single.payload, single.steps, package_name=package_name, source_title=label)
        skill_pack_log_append({"kind": "workflow_compile_complete", "index": 1, "total": 1, "package_name": result.name})
        return [result]

    max_workers = min(4, total)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_compile_single_workflow, index, raw_workflow)
            for index, raw_workflow in enumerate(raw_workflows, start=1)
        ]
        compiled = []
        for future in futures:
            try:
                compiled.append(future.result())
            except Exception as exc:
                skill_pack_log_append({"kind": "workflow_compile_failed", "error": str(exc)})

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
        "6. Run the executor **in the background** (REQUIRED — so you can respond to L4 recovery signals while it runs):\n"
        "   Use `run_in_background: true` on the Bash tool:\n"
        "   ```\n"
        "   cd \"C:\\path\\to\\plugin\" && node execution/executor.js --plan _plan.json\n"
        "   ```\n"
        "7. **Watch stdout for `[recovery] L4 agent recovery`**. When you see it:\n"
        "   - Read `RECOVERY_CONTEXT.json` and `RECOVERY_SCREENSHOT.jpeg`\n"
        "   - Identify the correct Playwright selector from the DOM snapshot\n"
        "   - Write `RECOVERY_RESPONSE.json` immediately (executor is paused, browser is open):\n"
        "     ```powershell\n"
        "     Set-Content -Path \"C:\\path\\to\\plugin\\RECOVERY_RESPONSE.json\" -Value '{\"selectors\":[\"...correct selector...\"]}'`\n"
        "     ```\n"
        "   - The executor picks it up, retries only that step, and continues — no rerun from start\n"
        "8. After the background process finishes, read `EXECUTION_PLAN_RESULT.json` and report pass/fail\n\n"
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
    files: dict[str, str] = {
        "execution.json": compiled.execution_json,
        "recovery.json": compiled.recovery_json,
        "SKILL.md": compiled.skill_md,
    }
    return files


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

        skill_names = [p.name for p in persisted]
        bundle_root = bundle_root_dir(bundle_slug)
        if bundle_root and bundle_root.is_dir():
            (bundle_root / "CLAUDE.md").write_text(
                _generate_claude_md_text(bundle_slug, skill_names), encoding="utf-8"
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
    if not compiled_workflows:
        raise ValueError("All workflow compilations failed. See build log for details.")

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
    description = _manifest_description(name, json.loads(manifest_json).get("description", ""))

    plugin_index = format_plugin_index_json(
        bundle_segment,
        [{"name": name, "description": description}],
    )
    readme = format_plugin_readme_text(bundle_segment, [{"name": name, "description": description}])

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

    buffer = BytesIO()
    skill_root = f"{bundle_folder}/skills/{name}"
    plugin_slug = bundle_segment
    skill_names = [name]
    claude_md = _generate_claude_md_text(plugin_slug, skill_names)

    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(f"{bundle_folder}/{bundle_segment}.json", plugin_index)
        archive.writestr(f"{bundle_folder}/README.md", readme)
        archive.writestr(f"{bundle_folder}/CLAUDE.md", claude_md)
        archive.writestr(f"{skill_root}/SKILL.md", per_skill_skill_md)
        archive.writestr(f"{skill_root}/execution.json", execution_json)
        archive.writestr(f"{skill_root}/recovery.json", recovery_json)
        if visual_assets:
            for filename, content in sorted(visual_assets.items()):
                archive.writestr(f"{skill_root}/visuals/{Path(filename).name}", content)
    archive_name_root = bundle_segment.replace("/", "_").replace("\\", "_")
    return f"{archive_name_root}_{name}.zip", buffer.getvalue()


def zip_skill_bundle_from_disk(bundle_slug: str) -> tuple[str, bytes]:
    """Write every file under ``output/skill_package/<bundle_slug>/`` into one ZIP."""
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
                if rel.startswith("auth/"):
                    continue
                arcname = f"{zip_prefix}/{rel}"
                archive.write(path, arcname)
    return f"{slug}.zip", buffer.getvalue()
