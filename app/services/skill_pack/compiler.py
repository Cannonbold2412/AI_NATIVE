"""Structured step validation, deterministic execution, recovery, and docs generation."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.compiler.action_policy import RECOVERY_ACTION_TYPES

from .common import (
    _ALLOWED_STRUCTURED_TYPES,
    _CHECK_KINDS,
    _DESTRUCTIVE_TEXT,
    _GENERIC_LABELS,
    _GENERIC_SELECTORS,
    _INPUT_CONTAINER_KEYS,
    _INPUT_NAME_KEYS,
    _INPUT_NAME_RE,
    _LOGIN_TEXT,
    _METADATA_KEYS,
    _RECOVERY_VISUAL_SUFFIXES,
    _SELECTOR_ONLY_STEP_TYPES,
    _SENSITIVE_HINTS,
    _TEXT_INPUT_STEP_TYPES,
    _TEXT_SELECTOR_RE,
    _VAR_PATTERN,
    _first_text_from_keys,
    _get_mapping,
    _humanize_name,
    _json_text,
    _normalize_name,
    _parse_json_text,
)


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
        raise ValueError("Fill selectors must use input[name=...].")
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
    selector = _validate_selector(_json_text(step.get("selector")), step_type="fill")
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


def _canonical_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    step_type = str(step.get("type") or "").strip().lower()
    if step_type not in _ALLOWED_STRUCTURED_TYPES:
        raise ValueError(
            f"Unsupported structured step type at index {index}: {step.get('type')}"
        )
    if step_type == "navigate":
        return _canonical_navigate_step(step, index)
    if step_type in _TEXT_INPUT_STEP_TYPES:
        return _canonical_text_input_step(step, step_type, index)
    if step_type in _SELECTOR_ONLY_STEP_TYPES:
        return _canonical_selector_only_step(step, step_type)
    if step_type == "scroll":
        return _canonical_scroll_step(step, index)
    if step_type == "check":
        return _canonical_check_step(step, index)
    return _canonical_click_step(step)


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
