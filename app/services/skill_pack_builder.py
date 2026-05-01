"""Build reusable Skill Package artifacts from workflow JSON."""

from __future__ import annotations

import json
import re
from io import BytesIO
from collections.abc import Iterable
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from app.llm.skill_pack_llm import generate_skill_markdown_with_llm
from app.storage.skill_packages import write_skill_package_files

_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^a-zA-Z0-9]+")
_URL_KEYS = (
    "start_url",
    "startUrl",
    "entry_url",
    "entryUrl",
    "initial_url",
    "initialUrl",
    "base_url",
    "baseUrl",
    "url",
    "href",
    "current_url",
    "currentUrl",
)
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
_SENSITIVE_HINTS = (
    "password",
    "passcode",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "auth",
    "otp",
    "pin",
)
_EXECUTION_MODE_HEADING = "## Execution Mode (High Performance)"
_EXECUTION_MODE_BLOCK = """## Execution Mode (High Performance)

You are an execution engine. Your goal is to execute this skill as fast and efficiently as possible.

### Core Rules

* Do NOT explain your actions
* Do NOT think step-by-step out loud
* Do NOT generate reasoning, plans, or commentary
* Do NOT create task lists or todos
* Do NOT repeat previous steps or context

### Execution Behavior

* Execute steps directly using available tools (e.g., browser automation)
* Prefer direct actions over analysis
* Minimize delays between steps
* Only wait when absolutely necessary (e.g., waiting for a page or element to load)

### Waiting Strategy

* Do NOT use generic waits like "wait for page load"
* Only wait for specific, required elements

### Input Handling

* Replace all {{variables}} before execution
* If a required input is missing:
  → Ask the user briefly and continue immediately

### Failure Handling

* If a step fails:
  → Retry once silently using an alternative interpretation
* If it still fails:
  → Ask the user for clarification

### Vision Usage (If Available)

* Do NOT use vision by default
* Use vision ONLY if:

  * element is not found
  * confidence is low
  * retry is required

### Output Rules

* Output ONLY:

  * tool execution steps
  * or final status: "done"

* Do NOT include:

  * explanations
  * logs
  * reasoning
  * step summaries

### Performance Goal

* Minimize token usage
* Minimize execution time
* Avoid unnecessary LLM calls

### Final Objective

Execute the full workflow reliably with minimal overhead, behaving like a fast deterministic system rather than a conversational agent.
"""


def _parse_json_text(json_text: str) -> Any:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, (dict, list)):
        raise ValueError("JSON root must be an object or array.")
    return payload


def _normalize_name(raw: str) -> str:
    text = _CAMEL_BOUNDARY.sub(r"\1_\2", str(raw or "").strip())
    text = _NON_WORD.sub("_", text).strip("_").lower()
    if not text:
        return "input_value"
    if text[0].isdigit():
        return f"input_{text}"
    return text


def _humanize_name(name: str) -> str:
    return name.replace("_", " ").strip()


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _SENSITIVE_HINTS)


def _replace_variable_refs(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return "{{" + _normalize_name(match.group(1)) + "}}"

    return _VAR_PATTERN.sub(replace, text)


def _canonicalize_variable_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize_variable_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize_variable_refs(item) for item in value]
    if isinstance(value, str):
        return _replace_variable_refs(value)
    return value


def _iter_existing_input_names(payload: Any) -> Iterable[str]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("inputs")
    if not isinstance(items, list):
        return []
    found: list[str] = []
    for item in items:
        if isinstance(item, str):
            found.append(item)
            continue
        if not isinstance(item, dict):
            continue
        for key in ("name", "id", "key", "label"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                found.append(value)
                break
    return found


def parse_inputs(payload: Any) -> list[dict[str, Any]]:
    payload = _canonicalize_variable_refs(payload)
    text = json.dumps(payload, ensure_ascii=False)
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in _VAR_PATTERN.findall(text):
        name = _normalize_name(raw)
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    for raw in _iter_existing_input_names(payload):
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


def _extract_steps(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    direct = payload.get("steps")
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, dict)]
    steps: list[dict[str, Any]] = []
    skills = payload.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, dict) and isinstance(skill.get("steps"), list):
                steps.extend(item for item in skill["steps"] if isinstance(item, dict))
    return steps


def _package_title(payload: Any) -> str:
    if isinstance(payload, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            for key in ("title", "name", "id"):
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key in ("title", "name", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        skills = payload.get("skills")
        if isinstance(skills, list) and skills:
            first = skills[0]
            if isinstance(first, dict):
                value = first.get("name")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return "generated_skill"


def _slugify_name(value: str) -> str:
    slug = _NON_WORD.sub("_", value.strip().lower()).strip("_")
    return slug or "generated_skill"


def _action_name(step: dict[str, Any]) -> str:
    action = step.get("action")
    if isinstance(action, dict):
        value = action.get("action")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    if isinstance(action, str) and action.strip():
        return action.strip().lower()
    return "interact"


def _action_payload(step: dict[str, Any]) -> dict[str, Any]:
    action = step.get("action")
    return action if isinstance(action, dict) else {}


def _step_value(step: dict[str, Any]) -> Any:
    action = _action_payload(step)
    for key in ("value", "text", "query", "option", "url", "href"):
        if key in action:
            return action.get(key)
    for key in ("value", "text", "query", "option", "url", "href"):
        if key in step:
            return step.get(key)
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_mapping_text(mapping: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _target_hint(step: dict[str, Any]) -> str:
    target = step.get("target")
    signals = step.get("signals")
    dom = signals.get("dom") if isinstance(signals, dict) else None
    semantic = signals.get("semantic") if isinstance(signals, dict) else None
    return _first_text(
        _first_mapping_text(
            target,
            ("label", "name", "text", "inner_text", "aria_label", "placeholder", "title", "alt"),
        ),
        _first_mapping_text(dom, ("label", "name", "text", "inner_text", "aria_label", "placeholder", "title")),
        _first_mapping_text(semantic, ("label", "text", "anchor_text", "visible_text", "target_text")),
        _first_mapping_text(target, ("role", "tag")),
        _first_mapping_text(dom, ("role", "tag")),
    )


def _context_hint(step: dict[str, Any]) -> str:
    target = step.get("target")
    signals = step.get("signals")
    semantic = signals.get("semantic") if isinstance(signals, dict) else None
    return _first_text(
        _first_mapping_text(target, ("section", "region", "container", "parent_text", "nearby_text")),
        _first_mapping_text(semantic, ("section", "region", "container", "nearby_text", "context")),
    )


def _step_variables(step: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    for raw in _VAR_PATTERN.findall(json.dumps(_step_value(step), ensure_ascii=False)):
        name = _normalize_name(raw)
        if name not in seen:
            seen.add(name)
            names.append(name)

    for raw in _VAR_PATTERN.findall(json.dumps(step, ensure_ascii=False)):
        name = _normalize_name(raw)
        if name not in seen:
            seen.add(name)
            names.append(name)

    input_binding = step.get("input_binding")
    if isinstance(input_binding, str) and input_binding.strip():
        name = _normalize_name(input_binding)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _intent_hint(step: dict[str, Any]) -> str:
    recovery = step.get("recovery")
    semantic = step.get("signals", {}).get("semantic") if isinstance(step.get("signals"), dict) else None
    return _first_text(
        step.get("intent"),
        recovery.get("final_intent") if isinstance(recovery, dict) else "",
        recovery.get("intent") if isinstance(recovery, dict) else "",
        semantic.get("final_intent") if isinstance(semantic, dict) else "",
    )


def _wait_target_hint(wait_for: dict[str, Any]) -> str:
    return _first_text(
        str(wait_for.get("target") or "").strip(),
        str(wait_for.get("selector") or "").strip(),
        str(wait_for.get("text") or "").strip(),
        str(wait_for.get("value") or "").strip(),
    )


def _validation_phrase_from_wait(wait_for: Any) -> str:
    if not isinstance(wait_for, dict):
        return ""

    conditions = wait_for.get("conditions")
    if isinstance(conditions, list):
        phrases = [_validation_phrase_from_wait(item) for item in conditions]
        phrases = [phrase for phrase in phrases if phrase]
        if phrases:
            return "; ".join(phrases)

    wait_type = str(wait_for.get("type") or wait_for.get("wait_for") or "state_change").strip().lower()
    target = _wait_target_hint(wait_for)
    not_contains = _first_text(wait_for.get("not_contains"), wait_for.get("url_not_contains"))
    contains = _first_text(wait_for.get("contains"), wait_for.get("url_contains"))

    if "url" in wait_type and ("not" in wait_type or not_contains):
        value = not_contains or target
        return f"Ensure the URL does not contain {value}." if value else "Ensure the URL has left the previous page."
    if "url" in wait_type and contains:
        return f"Ensure the URL contains {contains}."
    if wait_type in {"load", "page_load", "loaded", "network_idle"}:
        return "Wait until the page finishes loading."
    if wait_type in {"element_appear", "visible", "element_visible", "text_appear"}:
        return f"Wait until {target} appears." if target else "Wait until the expected content appears."
    if wait_type in {"element_disappear", "hidden", "element_hidden", "text_disappear"}:
        return f"Wait until {target} is no longer visible." if target else "Wait until the previous content is no longer visible."
    if wait_type in {"dom_change", "state_change", "mutation"}:
        return "Wait until the page updates."
    if wait_type in {"none", "no_wait"}:
        return ""
    return f"Wait until {wait_type.replace('_', ' ')} completes."


def _validation_phrase(step: dict[str, Any]) -> str:
    validation = step.get("validation")
    wait_for = validation.get("wait_for") if isinstance(validation, dict) else None
    phrase = _validation_phrase_from_wait(wait_for)
    return phrase or "Confirm the expected UI state before continuing."


def _quote_label(label: str) -> str:
    clean = " ".join(str(label or "").split())
    return f'"{clean}"' if clean else ""


def _field_label(step: dict[str, Any], variable: str = "") -> str:
    target = _target_hint(step)
    lowered = target.lower()
    if not target or lowered in {"textbox", "input", "textarea", "combobox"}:
        return _humanize_name(variable) if variable else "the required field"
    return target


def _step_url(step: dict[str, Any]) -> str:
    value = _step_value(step)
    if isinstance(value, str) and _looks_like_url(value):
        return value.strip()
    action = _action_payload(step)
    for key in _URL_KEYS:
        raw = action.get(key) if key in action else step.get(key)
        if isinstance(raw, str) and _looks_like_url(raw):
            return raw.strip()
    return ""


def _looks_like_url(value: str) -> bool:
    text = str(value or "").strip()
    if not re.match(r"^https?://", text, re.IGNORECASE):
        return False
    lowered = text.lower().split("?", 1)[0]
    return not lowered.endswith(_IMAGE_EXTENSIONS)


def _extract_entry_url(payload: Any) -> str:
    def from_mapping(mapping: dict[str, Any]) -> str:
        for key in _URL_KEYS:
            value = mapping.get(key)
            if isinstance(value, str) and _looks_like_url(value):
                return value.strip()
        return ""

    if not isinstance(payload, (dict, list)):
        return ""
    if isinstance(payload, dict):
        for key in ("meta", "package_meta", "recording", "session"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                found = from_mapping(nested)
                if found:
                    return found
        found = from_mapping(payload)
        if found:
            return found
    for step in _extract_steps(payload):
        if _action_name(step) in {"navigate", "goto", "open"}:
            found = _step_url(step)
            if found:
                return found
    items = payload.values() if isinstance(payload, dict) else payload
    for item in items:
        if isinstance(item, (dict, list)):
            found = _extract_entry_url(item)
            if found:
                return found
    return ""


def _step_instruction(step: dict[str, Any], index: int) -> str:
    action = _action_name(step)
    target = _target_hint(step)
    context = _context_hint(step)
    intent = _humanize_name(_normalize_name(_intent_hint(step)))
    variables = _step_variables(step)
    target_phrase = _quote_label(target) if target else "the intended control"
    if action in {"type", "fill", "input"}:
        variable = variables[0] if variables else ""
        value_hint = f" using {{{{{variable}}}}}" if variable else ""
        field_hint = _field_label(step, variable)
        return f"Enter {field_hint}{value_hint}."
    if action in {"click", "tap", "press"}:
        base = f"Click {target_phrase}"
        if context:
            base += f" in the {context} section"
        return base + "."
    elif action == "select":
        variable = variables[0] if variables else ""
        value_hint = f" using {{{{{variable}}}}}" if variable else ""
        base = f"Choose the required option from {target_phrase}{value_hint}."
    elif action in {"navigate", "goto"}:
        url = _step_url(step)
        base = f"Open {url}." if url else "Open the intended page."
    elif action in {"scroll", "focus"}:
        return ""
    elif action == "focus":
        return ""
    else:
        base = f"Perform the {action} action on {target_phrase}."
    if intent:
        return f"{base} Intent: {intent}."
    return base


def _render_markdown_steps(steps: list[dict[str, Any]], entry_url: str = "") -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    if entry_url:
        rendered.append(
            {
                "instruction": f"Open {entry_url}.",
                "validation": "Wait until the page finishes loading.",
            }
        )
    for step in steps:
        action = _action_name(step)
        if action in {"focus", "scroll"}:
            continue
        if action in {"navigate", "goto", "open"} and entry_url and _step_url(step) == entry_url:
            continue
        instruction = _step_instruction(step, len(rendered) + 1)
        if not instruction:
            continue
        rendered.append({"instruction": instruction, "validation": _validation_phrase(step)})
    return rendered


def _step_summary(step: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "step": index,
        "action": _action_name(step),
        "intent": _intent_hint(step),
        "target_hint": _target_hint(step),
        "variables": _step_variables(step),
        "validation": _validation_phrase(step),
    }


def _build_llm_summary(
    payload: Any,
    inputs: list[dict[str, Any]],
    package_name: str,
    rendered_steps: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "package_name": package_name,
        "inputs": inputs,
        "steps": rendered_steps,
        "rules": [
            "Do not mention focus steps.",
            "Do not mention scroll steps.",
            "Use only variables listed in inputs.",
            "Use natural UI language such as Enter email and Click \"Save\".",
        ],
    }


def _strip_code_fences(markdown: str) -> str:
    text = markdown.strip()
    match = re.match(r"^```(?:markdown|md)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    return match.group(1).strip() if match else text


def _build_skill_markdown_fallback(
    package_name: str,
    inputs: list[dict[str, Any]],
    rendered_steps: list[dict[str, str]],
) -> str:
    lines = [f"# {package_name}", "", "## Inputs"]
    if inputs:
        for index, item in enumerate(inputs, start=1):
            suffix = " Keep this value secure." if item.get("sensitive") else ""
            lines.append(f"{index}. `{{{{{item['name']}}}}}`: {item['description']}.{suffix}")
    else:
        lines.append("1. This workflow does not declare runtime inputs.")

    lines.extend(["", "## Steps"])
    for index, item in enumerate(rendered_steps, start=1):
        lines.append(f"{index}. {item['instruction']}")

    lines.extend(["", "## Validation"])
    validations = [item.get("validation", "").strip() for item in rendered_steps]
    validations = [item for item in validations if item]
    if validations:
        for index, validation in enumerate(validations, start=1):
            lines.append(f"{index}. {validation}")
    else:
        lines.append("1. Confirm the expected UI state before finishing.")

    lines.extend(["", "## Input Handling"])
    if inputs:
        for item in inputs:
            lines.append(f"- Use `{{{{{item['name']}}}}}` for {_humanize_name(str(item['name']))}.")
    else:
        lines.append("- No runtime input substitution is required.")

    lines.extend(
        [
            "",
            "## Execution Rules",
            "1. Execute the workflow in order without skipping prerequisite steps.",
            "2. Replace each placeholder with the matching runtime input before acting.",
            "3. Use visible intent, labels, and surrounding context instead of raw selectors.",
            "4. Stop and report when the observed UI state does not match the expected outcome.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _ensure_execution_mode_block(markdown: str) -> str:
    text = (markdown or "").strip()
    if not text:
        return _EXECUTION_MODE_BLOCK + "\n"
    if _EXECUTION_MODE_HEADING in text:
        return text + "\n"

    block = _EXECUTION_MODE_BLOCK.strip()
    steps_match = re.search(r"^## Steps\s*$", text, re.MULTILINE)
    if steps_match:
        updated = text[: steps_match.start()].rstrip() + "\n\n" + block + "\n\n" + text[steps_match.start() :].lstrip()
        return updated.rstrip() + "\n"

    inputs_match = re.search(r"^## Inputs\s*$", text, re.MULTILINE)
    if inputs_match:
        next_heading = re.search(r"^##\s+", text[inputs_match.end() :], re.MULTILINE)
        insert_at = inputs_match.end() + next_heading.start() if next_heading else len(text)
        updated = text[:insert_at].rstrip() + "\n\n" + block + text[insert_at:]
        return updated.rstrip() + "\n"

    return text.rstrip() + "\n\n" + block + "\n"


def _strip_execution_mode_block(markdown: str) -> str:
    text = markdown or ""
    if _EXECUTION_MODE_HEADING not in text:
        return text
    return text.replace(_EXECUTION_MODE_BLOCK, "").replace(_EXECUTION_MODE_HEADING, "")


def _markdown_is_consistent(markdown: str, inputs: list[dict[str, Any]]) -> bool:
    text = _strip_execution_mode_block(markdown or "")
    lowered = text.lower()
    if re.search(r"\b(focus|activate|scroll)\b", lowered):
        return False
    input_names = {str(item.get("name") or "").strip() for item in inputs if str(item.get("name") or "").strip()}
    markdown_names = {_normalize_name(raw) for raw in _VAR_PATTERN.findall(text)}
    return markdown_names == input_names


def build_manifest(inputs: list[dict[str, Any]], package_name: str) -> dict[str, Any]:
    return {
        "name": package_name,
        "version": "1.0.0",
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


def build_skill_package(json_text: str) -> dict[str, Any]:
    payload = _canonicalize_variable_refs(_parse_json_text(json_text))
    steps = _extract_steps(payload)
    if not steps:
        raise ValueError("No workflow steps detected in JSON.")
    inputs = parse_inputs(payload)
    package_name = _slugify_name(_package_title(payload))
    rendered_steps = _render_markdown_steps(steps, _extract_entry_url(payload))
    summary = _build_llm_summary(payload, inputs, package_name, rendered_steps)
    llm_skill_md = generate_skill_markdown_with_llm(summary)
    skill_md = _strip_code_fences(llm_skill_md or "") if llm_skill_md else ""
    used_llm = bool(skill_md and _markdown_is_consistent(skill_md, inputs))
    if not used_llm:
        skill_md = _build_skill_markdown_fallback(package_name, inputs, rendered_steps)
    else:
        skill_md = _strip_code_fences(skill_md)
    skill_md = _ensure_execution_mode_block(skill_md)
    manifest = build_manifest(inputs, package_name)
    warnings: list[str] = []
    if not used_llm:
        warnings.append(
            "Skill Pack Builder used the deterministic renderer because SKILL_PACK_LLM_* is not configured or did not pass consistency checks."
        )
    skill_json = json.dumps(payload, ensure_ascii=False, indent=2)
    input_json = json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    write_skill_package_files(
        package_name,
        {
            "skill.md": skill_md,
            "skill.json": skill_json,
            "manifest.json": manifest_json,
            "inputs.json": input_json,
        },
    )
    return {
        "name": package_name,
        "skill_md": skill_md,
        "skill_json": skill_json,
        "input_json": input_json,
        "inputs_json": input_json,
        "manifest_json": manifest_json,
        "input_count": len(inputs),
        "step_count": len(steps),
        "used_llm": used_llm,
        "warnings": warnings,
    }


def build_skill_package_zip(
    package_name: str,
    skill_md: str,
    skill_json: str,
    input_json: str,
    manifest_json: str,
) -> tuple[str, bytes]:
    name = _slugify_name(package_name)
    if not skill_md.strip():
        raise ValueError("skill.md content is required for export.")
    if not skill_json.strip() or not input_json.strip() or not manifest_json.strip():
        raise ValueError("skill.json, inputs.json, and manifest.json are required for export.")
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(f"{name}/skill.md", skill_md)
        archive.writestr(f"{name}/skill.json", skill_json)
        archive.writestr(f"{name}/inputs.json", input_json)
        archive.writestr(f"{name}/manifest.json", manifest_json)
    return f"{name}.zip", buffer.getvalue()
