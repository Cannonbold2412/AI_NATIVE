"""LLM-first Skill Package generator.

Pipeline:

``raw skills.json -> LLM structuring -> deterministic compiler -> package files``.

The LLM is the only layer that interprets messy recordings. This module only
validates structured output, compiles allowed runtime actions, and writes the
package artifacts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import parse_qs, urlparse, urlunparse
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import settings
from app.llm.pack_llm_keys import configured_pack_keys, next_pack_api_key
from app.storage.skill_packages import (
    INDEX_FILENAME,
    SKILL_PACKAGE_DIRNAME,
    VISUAL_IMAGE_SUFFIXES,
    read_engine_files,
    read_skill_package_visual_asset_bytes,
    skill_package_readme,
    write_skill_package_files,
)

_PACK_LLM_TRANSIENT_HTTP = frozenset({502, 503, 504})

_STRUCTURING_SYSTEM_PROMPT = """You are an expert automation compiler.

Convert messy browser interaction logs into structured steps.

Rules:

* Remove focus and wait actions (never output `wait`).
* Fold redundant scroll jitter into purposeful `scroll` steps when scrolling clearly reveals UI.
* Merge redundant steps
* Infer user intent
* Replace hardcoded values with variables like {{user_email}}
* Use ONLY these types:

  * navigate
  * fill
  * click
  * scroll — when content only appears after scrolling:
    optional `selector` (scroll that element into view, same selector rules as `click`),
    optional `delta_y` (positive = down, negative = up, wheel pixels with `delta_x` defaulting to 0);
    supply at least one of `selector` or `delta_y` (non-zero).

Rules for selectors:

* Prefer text="..." for buttons
* Use input[name="..."] for fields
* NEVER output:

  * "input"
  * "button"
  * XPath

Output JSON ONLY:

{
"goal": "...",
"steps": [
{
"type": "navigate",
"url": "..."
},
{
"type": "fill",
"selector": "input[name=email]",
"value": "{{user_email}}"
},
{
"type": "click",
"selector": "text=Sign in"
},
{
"type": "scroll",
"selector": "text=Load more reviews"
},
{
"type": "scroll",
"delta_y": 480
}
]
}
"""

_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^a-zA-Z0-9]+")
_TEXT_SELECTOR_RE = re.compile(r"^\s*text\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|(.+?))\s*$", re.IGNORECASE)
_INPUT_NAME_RE = re.compile(r"input\s*\[\s*name\s*=\s*['\"]?([^'\"\]]+)['\"]?\s*\]", re.IGNORECASE)

_STEP_LIST_KEYS = ("steps", "actions", "events", "recorded_events", "interactions", "workflow_steps")
_STEP_CONTAINER_KEYS = ("skills", "workflows", "flows", "scenarios", "recordings")
_METADATA_KEYS = ("meta", "package_meta", "metadata", "package", "workflow", "recording", "session")
_TITLE_KEYS = ("title", "name", "id", "slug", "workflow_name", "workflowName")
_INPUT_CONTAINER_KEYS = ("inputs", "parameters", "params", "variables")
_INPUT_NAME_KEYS = ("name", "id", "key", "label", "input_name", "inputName", "field", "binding")
_STEP_VISUAL_KEYS = ("full_screenshot", "scroll_screenshot", "element_snapshot")
_STEP_SCREENSHOT_URL_KEYS = ("full_url", "scroll_url", "element_url")

_ALLOWED_STRUCTURED_TYPES = {"navigate", "fill", "click", "scroll"}
_ALLOWED_EXECUTION_TYPES = {"navigate", "fill", "click", "assert_visible", "scroll"}
_GENERIC_SELECTORS = {"input", "button", "textarea", "select"}
_SENSITIVE_HINTS = ("password", "passcode", "passwd", "secret", "token", "api_key", "apikey", "private_key", "credential", "auth", "otp", "pin")
_LOGIN_TEXT = ("sign in", "signin", "log in", "login")
_DESTRUCTIVE_TEXT = ("delete", "remove", "destroy", "drop", "archive", "reset", "disable", "revoke")


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
    return str(name or "").replace("_", " ").strip()


def _slugify_name(value: str) -> str:
    return _normalize_name(value) or "generated_skill"


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _get_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text_from_keys(mapping: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _json_text(mapping.get(key))
        if value:
            return value
    return ""


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


def _package_title(payload: Any, structured: dict[str, Any] | None = None) -> str:
    goal = _json_text((structured or {}).get("goal"))
    if goal:
        return goal
    if isinstance(payload, dict):
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


def _chat_completions_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        return endpoint
    if path.endswith("/v1"):
        path = f"{path}/chat/completions"
    elif not path:
        path = "/v1/chat/completions"
    else:
        path = f"{path}/chat/completions"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


def _extract_llm_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return str(first.get("text") or "").strip()
    content = message.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text") or ""))
        return "".join(chunks).strip()
    return str(content or "").strip()


def _extract_json_object_substring(raw: str) -> str | None:
    """First balanced `{...}` slice in raw (same idea as app.llm.client)."""
    lb = raw.find("{")
    if lb < 0:
        return None
    depth = 0
    for i in range(lb, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                return raw[lb : i + 1]
    return None


def _parse_strict_json_object(text: str) -> dict[str, Any]:
    """Parse model text into a dict; allow markdown fences and leading/trailing prose."""
    s = (text or "").strip()
    if not s:
        raise ValueError("LLM structuring must return a JSON object only.")

    last_err: json.JSONDecodeError | None = None

    def try_parse(chunk: str) -> dict[str, Any] | None:
        nonlocal last_err
        chunk = chunk.strip()
        if not chunk:
            return None
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError as exc:
            last_err = exc
            return None
        return parsed if isinstance(parsed, dict) else None

    got = try_parse(s)
    if got is not None:
        return got

    sub = _extract_json_object_substring(s)
    if sub:
        got = try_parse(sub)
        if got is not None:
            return got

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.I)
    if fence:
        inner = fence.group(1).strip()
        got = try_parse(inner)
        if got is not None:
            return got
        sub2 = _extract_json_object_substring(inner)
        if sub2:
            got = try_parse(sub2)
            if got is not None:
                return got

    if last_err is not None:
        raise ValueError(f"LLM structuring returned invalid JSON: {last_err.msg}") from last_err
    raise ValueError("LLM structuring must return a JSON object only.")


def _call_structuring_llm(raw_steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.pack_llm_enabled:
        raise ValueError("Skill package generation requires the LLM structuring layer; SKILL_PACK_LLM_ENABLED is disabled.")
    endpoint = str(settings.pack_llm_endpoint or "").strip()
    model = str(settings.pack_llm_model or "").strip()
    if not endpoint or not model:
        raise ValueError("Skill package generation requires SKILL_PACK_LLM_ENDPOINT and SKILL_PACK_LLM_MODEL.")

    parsed_ep = urlparse(endpoint)
    ep_host = (parsed_ep.netloc or "").lower()
    user_msg = json.dumps({"raw_steps": raw_steps}, ensure_ascii=False, separators=(",", ":"))
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _STRUCTURING_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": settings.pack_llm_structure_temperature,
    }
    if settings.pack_llm_structure_max_tokens is not None:
        body["max_tokens"] = settings.pack_llm_structure_max_tokens
    if settings.pack_llm_top_p is not None:
        body["top_p"] = settings.pack_llm_top_p
    # integrate.api.nvidia.com: runtime logs show repeated HTTP 504 ~300s with response_format=json_object;
    # omit strict JSON mode so the gateway/model can finish within upstream limits; prompt still requires JSON.
    if "integrate.api.nvidia.com" not in ep_host:
        body["response_format"] = {"type": "json_object"}
    raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    url = _chat_completions_url(endpoint)
    _timeout_s = max(0.2, settings.pack_llm_timeout_ms / 1000.0)
    keys_pool = configured_pack_keys()
    max_tries = min(5, max(1, len(keys_pool))) if keys_pool else 1

    raw = ""
    for attempt in range(max_tries):
        headers = {"Content-Type": "application/json"}
        pack_key, _, _ = next_pack_api_key()
        if pack_key:
            headers["Authorization"] = f"Bearer {pack_key}"

        req = request.Request(url, data=raw_body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=_timeout_s) as res:
                raw = res.read().decode("utf-8")
                break
        except error.HTTPError as exc:
            if exc.code in _PACK_LLM_TRANSIENT_HTTP and attempt < max_tries - 1:
                continue
            raise ValueError(
                f"LLM structuring request failed (HTTP {exc.code}: {exc.reason!s})."
            ) from exc
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ValueError("LLM structuring request failed.") from exc

    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM structuring provider returned invalid JSON.") from exc
    if not isinstance(response, dict):
        raise ValueError("LLM structuring provider returned an invalid response.")
    if "goal" in response and "steps" in response:
        return response
    return _parse_strict_json_object(_extract_llm_content(response))


def _selector_text(selector: str) -> str:
    match = _TEXT_SELECTOR_RE.match(selector or "")
    if match:
        return " ".join(next(group for group in match.groups() if group is not None).strip().split())
    match = _INPUT_NAME_RE.search(selector or "")
    if match:
        return _humanize_name(_normalize_name(match.group(1)))
    return ""


def _is_xpath(selector: str) -> bool:
    text = (selector or "").strip()
    return text.startswith("/") or text.startswith("./") or text.startswith("//") or text.lower().startswith("xpath=")


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


def _canonical_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    step_type = str(step.get("type") or "").strip().lower()
    if step_type not in _ALLOWED_STRUCTURED_TYPES:
        raise ValueError(f"Unsupported structured step type at index {index}: {step.get('type')}")
    if step_type == "navigate":
        url = _json_text(step.get("url"))
        if not re.match(r"^https?://", url, re.IGNORECASE):
            raise ValueError(f"Navigate step at index {index} requires an absolute HTTP(S) URL.")
        return {"type": "navigate", "url": url}
    if step_type == "fill":
        selector = _validate_selector(_json_text(step.get("selector")), step_type="fill")
        value = _json_text(step.get("value"))
        if not value:
            raise ValueError(f"Fill step at index {index} requires a value.")
        return {"type": "fill", "selector": selector, "value": value}
    if step_type == "scroll":
        selector_raw = _json_text(step.get("selector")).strip()
        raw_dy = step.get("delta_y")
        raw_dx = step.get("delta_x", 0)
        dy: float | None
        if raw_dy is None or raw_dy == "":
            dy = None
        else:
            try:
                dy = float(raw_dy)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Scroll step at index {index}: delta_y must be a number.") from exc
        try:
            dx = float(raw_dx) if raw_dx is not None and raw_dx != "" else 0.0
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Scroll step at index {index}: delta_x must be a number.") from exc

        has_selector = bool(selector_raw)
        has_wheel = (dy is not None and dy != 0.0) or dx != 0.0
        if not has_selector and not has_wheel:
            raise ValueError(
                f"Scroll step at index {index} requires a selector and/or non-zero delta_y / delta_x."
            )

        out: dict[str, Any] = {"type": "scroll"}
        if has_selector:
            out["selector"] = _validate_selector(selector_raw, step_type="click")
        if dy is not None:
            out["delta_y"] = dy
        if dx != 0.0:
            out["delta_x"] = dx
        return out
    selector = _validate_selector(_json_text(step.get("selector")), step_type="click")
    return {"type": "click", "selector": selector}


def _validate_structured_output(structured: dict[str, Any]) -> dict[str, Any]:
    goal = _json_text(structured.get("goal"))
    raw_steps = structured.get("steps")
    if not goal:
        raise ValueError("LLM structured output must include a goal.")
    if not isinstance(raw_steps, list):
        raise ValueError("LLM structured output must include steps array.")

    steps = [_canonical_step(step, index) for index, step in enumerate(raw_steps, start=1) if isinstance(step, dict)]
    if len(steps) != len(raw_steps):
        raise ValueError("Every LLM structured step must be a JSON object.")
    if not steps:
        raise ValueError("LLM structured output contains no executable steps.")
    return {"goal": goal, "steps": steps}


def structure_steps_with_llm(raw_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert messy browser logs into validated structured steps via LLM."""

    if not raw_steps:
        raise ValueError("No workflow steps detected in JSON.")
    structured = _call_structuring_llm(raw_steps)
    return _validate_structured_output(structured)


def _is_login_click(step: dict[str, Any]) -> bool:
    if step.get("type") != "click":
        return False
    text = _selector_text(str(step.get("selector") or "")).lower()
    return any(token in text for token in _LOGIN_TEXT)


def _is_destructive_click(step: dict[str, Any]) -> bool:
    if step.get("type") != "click":
        return False
    text = _selector_text(str(step.get("selector") or "")).lower()
    return any(token in text for token in _DESTRUCTIVE_TEXT)


def _append_step(plan: list[dict[str, Any]], step: dict[str, Any]) -> None:
    if plan and plan[-1] == step:
        return
    plan.append(step)


def compile_execution(structured_steps: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compile validated structured steps into runtime execution steps."""

    steps = structured_steps.get("steps", []) if isinstance(structured_steps, dict) else structured_steps
    if not isinstance(steps, list):
        raise ValueError("Structured steps must be a list or an object containing steps.")

    plan: list[dict[str, Any]] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            raise ValueError("Structured execution step must be an object.")
        step = _canonical_step(raw_step, len(plan) + 1)
        if step["type"] == "click" and _is_destructive_click(step):
            _append_step(plan, {"type": "assert_visible", "selector": step["selector"]})
        _append_step(plan, step)
        if _is_login_click(step):
            _append_step(plan, {"type": "assert_visible", "selector": "text=Dashboard"})
    return plan


def generateExecutionPlan(steps: Any) -> list[dict[str, Any]]:
    """Backward-compatible alias for callers that already pass structured steps."""

    structured = _validate_structured_output(steps) if isinstance(steps, dict) and "goal" in steps else steps
    return compile_execution(structured)


def generate_execution_plan(payload: Any, inputs: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]]]:
    structured = _validate_structured_output(payload) if isinstance(payload, dict) and "goal" in payload else structure_steps_with_llm(_extract_steps(payload))
    plan = compile_execution(structured)
    lines = ["# Execution Plan", ""]
    for index, step in enumerate(plan, start=1):
        if step["type"] == "navigate":
            lines.append(f"{index}. navigate {step['url']}")
        elif step["type"] == "fill":
            lines.append(f"{index}. fill {step['selector']} {step['value']}")
        elif step["type"] == "click":
            lines.append(f"{index}. click {step['selector']}")
        elif step["type"] == "scroll":
            scroll_parts: list[str] = []
            if step.get("selector"):
                scroll_parts.append(f"into_view {step['selector']}")
            if step.get("delta_y") is not None:
                scroll_parts.append(f"delta_y={step['delta_y']}")
            if step.get("delta_x"):
                scroll_parts.append(f"delta_x={step['delta_x']}")
            suffix = "; ".join(scroll_parts)
            lines.append(f"{index}. scroll" + (f" {suffix}" if suffix else ""))
        elif step["type"] == "assert_visible":
            lines.append(f"{index}. assert_visible {step['selector']}")
    return "\n".join(lines).rstrip() + "\n", plan


def _selector_target(step: dict[str, Any]) -> dict[str, str]:
    selector = str(step.get("selector") or "")
    text = _selector_text(selector)
    target_type = "field" if step.get("type") == "fill" else "button"
    section = ""
    lowered = text.lower()
    if any(token in lowered for token in _DESTRUCTIVE_TEXT):
        section = "danger zone"
    elif any(token in lowered for token in _LOGIN_TEXT):
        section = "login form"
    return {"text": text, "type": target_type, "section": section}


def _recovery_slug_from_step(step: dict[str, Any]) -> str:
    target = _selector_target(step)
    raw = " ".join(part for part in (str(step.get("type") or ""), target["text"] or target["type"]) if part)
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
        if clean and clean not in out:
            out.append(clean)
    return out[:4]


def _anchors_for_step(target: dict[str, str]) -> list[str]:
    anchors: list[str] = []
    section = target.get("section", "")
    if section:
        anchors.append(section)
    text = target.get("text", "").lower()
    if section == "danger zone" or any(token in text for token in _DESTRUCTIVE_TEXT):
        anchors.append("bottom")
    return anchors


def _visual_hint_for_step(step: dict[str, Any], target: dict[str, str]) -> str:
    text = target.get("text", "").lower()
    if step.get("type") == "fill":
        return "text input"
    if target.get("section") == "danger zone" or any(token in text for token in _DESTRUCTIVE_TEXT):
        return "red button"
    return "visible button"


def generate_recovery(structured_steps: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    compiled = compile_execution(structured_steps)
    entries: list[dict[str, Any]] = []
    for index, step in enumerate(compiled, start=1):
        if step.get("type") not in {"fill", "click"}:
            continue
        target = _selector_target(step)
        entries.append(
            {
                "step_id": index,
                "intent": _recovery_slug_from_step(step),
                "target": target,
                "anchors": _anchors_for_step(target),
                "fallback": {
                    "text_variants": _fallback_text_variants(target.get("text", "")),
                    "visual_hint": _visual_hint_for_step(step, target),
                },
            }
        )
    return {"steps": entries}


def generateRecoveryMap(steps: Any) -> dict[str, Any]:
    return generate_recovery(steps)


generate_recovery_map = generateRecoveryMap


def _iter_declared_input_names(payload: Any) -> Iterable[str]:
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    for container in (payload, *(_get_mapping(payload.get(key)) for key in _METADATA_KEYS)):
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


def build_manifest(inputs: list[dict[str, Any]], package_name: str, description: str = "") -> dict[str, Any]:
    return {
        "name": package_name,
        "description": _manifest_description(package_name, description),
        "version": "1.0.0",
        "entry": {
            "execution": "./execution.json",
            "recovery": "./recovery.json",
            "inputs": "./inputs.json",
        },
        "execution_mode": "deterministic",
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


def _normalize_manifest_json(manifest_json: str, inputs_json: str, package_name: str, description: str = "") -> str:
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
        raw_inputs = inputs_payload.get("inputs") if isinstance(inputs_payload, dict) else inputs_payload
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
        return "Open login page" if any(token in step["url"].lower() for token in _LOGIN_TEXT) else f"Open {step['url']}"
    if step["type"] == "scroll":
        sel_raw = str(step.get("selector") or "").strip()
        dy_val = step.get("delta_y")
        dx_val = float(step.get("delta_x") or 0)
        phrases: list[str] = []
        if sel_raw:
            label = _selector_text(sel_raw) or sel_raw
            phrases.append(f"Scroll to reveal {label}" if label else "Scroll element into view")
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
    if step["type"] == "fill":
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
    return ""


def generate_skill_markdown(package_name: str, structured_steps: dict[str, Any], inputs: list[dict[str, Any]]) -> str:
    lines = [f"# {package_name}", "", "## Inputs"]
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
    for step in plan:
        step_type = step.get("type")
        if step_type not in _ALLOWED_EXECUTION_TYPES:
            raise ValueError(f"Unsupported execution step type: {step_type}")
        if step_type == "fill":
            has_fill = True
            _validate_selector(str(step.get("selector") or ""), step_type="fill")
        elif step_type == "click":
            has_click = True
            _validate_selector(str(step.get("selector") or ""), step_type="click")
        elif step_type == "assert_visible":
            _validate_selector(str(step.get("selector") or ""), step_type="assert_visible")
        elif step_type == "scroll":
            sel_scroll = str(step.get("selector") or "").strip()
            raw_dy = step.get("delta_y")
            raw_dx = float(step.get("delta_x") or 0)
            dy_present = raw_dy is not None
            try:
                dy = float(raw_dy) if dy_present else 0.0
            except (TypeError, ValueError) as exc:
                raise ValueError("scroll steps require numeric delta_y when present.") from exc
            has_wheel = (dy_present and dy != 0.0) or raw_dx != 0.0
            if not sel_scroll and not has_wheel:
                raise ValueError("scroll steps require a selector and/or non-zero delta_y / delta_x.")
            if sel_scroll:
                _validate_selector(sel_scroll, step_type="click")
        elif step_type == "navigate" and not re.match(r"^https?://", str(step.get("url") or ""), re.IGNORECASE):
            raise ValueError("Navigate steps require absolute HTTP(S) URLs.")
        if step_type == "wait":
            raise ValueError("execution.json must not contain wait steps.")
    serialized = json.dumps(plan, ensure_ascii=False).lower()
    if '"type": "wait"' in serialized or '"type":"wait"' in serialized:
        raise ValueError("execution.json must not contain wait steps.")
    if "xpath" in serialized or re.search(r'"selector"\s*:\s*"(?:/|//|\./)', serialized):
        raise ValueError("execution.json must not contain XPath selectors.")
    if not has_click or not has_fill:
        raise ValueError("execution.json must contain at least one click and one fill step.")


def build_skill_package(json_text: str) -> dict[str, Any]:
    payload = _parse_json_text(json_text)
    raw_steps = _extract_steps(payload)
    if not raw_steps:
        raise ValueError("No workflow steps detected in JSON.")
    structured = structure_steps_with_llm(raw_steps)
    package_name = _slugify_name(_package_title(payload, structured))
    inputs = parse_inputs(structured)
    execution_plan = compile_execution(structured)
    _validate_execution_plan(execution_plan)
    recovery_map = generate_recovery(structured)
    manifest = build_manifest(inputs, package_name, str(structured.get("goal") or ""))
    skill_md = generate_skill_markdown(package_name, structured, inputs)

    inputs_json = json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    execution_json = json.dumps(execution_plan, ensure_ascii=False, indent=2)
    recovery_json = json.dumps(recovery_map, ensure_ascii=False, indent=2)
    structured_json = json.dumps(structured, ensure_ascii=False, indent=2)
    execution_md = generate_execution_plan(structured, inputs)[0]
    visual_assets = _collect_visual_assets(payload)

    package_dir = write_skill_package_files(
        package_name,
        {
            "skill.md": skill_md,
            "execution.json": execution_json,
            "recovery.json": recovery_json,
            "inputs.json": inputs_json,
            "manifest.json": manifest_json,
        },
        visual_assets=visual_assets,
    )
    index_path = package_dir.parents[1] / INDEX_FILENAME
    index_json = index_path.read_text(encoding="utf-8") if index_path.is_file() else json.dumps({"workflows": []}, indent=2)

    return {
        "name": package_name,
        "index_json": index_json,
        "skill_md": skill_md,
        "execution_json": execution_json,
        "recovery_json": recovery_json,
        "skill_json": structured_json,
        "inputs_json": inputs_json,
        "manifest_json": manifest_json,
        "execution_md": execution_md,
        "execution_plan_json": execution_json,
        "input_count": len(inputs),
        "step_count": len(execution_plan),
        "used_llm": True,
        "warnings": [],
    }


def build_skill_package_zip(
    package_name: str,
    skill_md: str,
    skill_json: str,
    inputs_json: str,
    manifest_json: str,
    execution_md: str = "",
    execution_plan_json: str = "",
    execution_json: str = "",
    recovery_json: str = "",
) -> tuple[str, bytes]:
    name = _slugify_name(package_name)
    if not skill_md.strip():
        raise ValueError("skill.md content is required for export.")
    if not inputs_json.strip() or not manifest_json.strip():
        raise ValueError("inputs.json and manifest.json are required for export.")
    manifest_json = _normalize_manifest_json(manifest_json, inputs_json, name)
    if not execution_json.strip():
        execution_json = execution_plan_json.strip()
    if not execution_json.strip():
        if not skill_json.strip():
            raise ValueError("execution.json is required for export.")
        parsed_skill = _parse_json_text(skill_json)
        _, plan = generate_execution_plan(parsed_skill)
        _validate_execution_plan(plan)
        execution_json = json.dumps(plan, ensure_ascii=False, indent=2)
    if not recovery_json.strip():
        if skill_json.strip():
            recovery_json = json.dumps(generate_recovery(_parse_json_text(skill_json)), ensure_ascii=False, indent=2)
        else:
            recovery_json = json.dumps({"steps": []}, ensure_ascii=False, indent=2)
    visual_assets = read_skill_package_visual_asset_bytes(name)

    try:
        parsed_plan = _parse_json_text(execution_json)
    except ValueError as exc:
        raise ValueError("execution.json must be valid JSON.") from exc
    if not isinstance(parsed_plan, list):
        raise ValueError("execution.json must be a JSON array.")
    if not all(isinstance(step, dict) for step in parsed_plan):
        raise ValueError("execution.json steps must be objects.")
    _validate_execution_plan(parsed_plan)

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        workflow_root = f"{SKILL_PACKAGE_DIRNAME}/workflows/{name}"
        archive.writestr(f"{SKILL_PACKAGE_DIRNAME}/README.md", skill_package_readme(name))
        archive.writestr(
            f"{SKILL_PACKAGE_DIRNAME}/{INDEX_FILENAME}",
            json.dumps(
                {
                    "workflows": [
                        {
                            "name": name,
                            "description": _manifest_description(name, json.loads(manifest_json).get("description", "")),
                            "manifest": f"/skills/{name}/manifest.json",
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        for filename, content in read_engine_files().items():
            archive.writestr(f"{SKILL_PACKAGE_DIRNAME}/engine/{filename}", content)
        archive.writestr(f"{workflow_root}/skill.md", skill_md)
        archive.writestr(f"{workflow_root}/execution.json", execution_json)
        archive.writestr(f"{workflow_root}/recovery.json", recovery_json)
        archive.writestr(f"{workflow_root}/inputs.json", inputs_json)
        archive.writestr(f"{workflow_root}/manifest.json", manifest_json)
        if visual_assets:
            for filename, content in sorted(visual_assets.items()):
                archive.writestr(f"{workflow_root}/visuals/{Path(filename).name}", content)
        else:
            archive.writestr(f"{workflow_root}/visuals/.gitkeep", "")
    return f"{SKILL_PACKAGE_DIRNAME}_{name}.zip", buffer.getvalue()
