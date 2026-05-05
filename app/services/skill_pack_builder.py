"""LLM-first Skill Package generator.

Pipeline:

``raw skills.json -> declaration cleanup -> LLM structuring (trimmed steps) -> compiler -> package files``.

The LLM is the only layer that interprets messy recordings. This module only
validates structured output, compiles allowed runtime actions, and writes the
package artifacts.
"""

from __future__ import annotations

import copy
import logging
import json
import re
import time
import base64
import tempfile
from dataclasses import dataclass, field
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib import error, request
from urllib.parse import parse_qs, urlparse, urlunparse
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import settings
from app.llm.pack_llm_keys import configured_pack_keys, next_pack_api_key
from app.services.skill_pack_build_log import skill_pack_build_log_scope, skill_pack_log_append
from app.storage.skill_packages import (
    SKILLS_SUBDIR,
    VISUAL_IMAGE_SUFFIXES,
    _bundle_folder_name,
    _sanitize_segment,
    _write_bundle_index,
    bundle_root_dir,
    format_credentials_example_json_text,
    format_plugin_index_json,
    format_plugin_readme_text,
    format_test_cases_stub_json_text,
    infer_auth_config,
    format_auth_json_text,
    read_skill_package_files,
    read_skill_package_visual_asset_bytes,
    resolve_workflow_dir,
    skill_package_root_posix,
    validate_bundle_slug,
    write_skill_package_files,
)

_logger = logging.getLogger(__name__)


class SkillPackBuildUserError(ValueError):
    """Validation or LLM failure with any ``build_log`` rows gathered so far."""

    def __init__(self, message: str, build_log: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.build_log = build_log


@dataclass(frozen=True)
class RawWorkflow:
    """One workflow recording extracted from a raw package payload."""

    title: str
    payload: Any
    steps: list[dict[str, Any]]


@dataclass
class CompiledWorkflow:
    """In-memory artifacts for one workflow before it is written to disk."""

    name: str
    execution_json: str
    recovery_json: str
    inputs_json: str
    manifest_json: str
    skill_md: str
    inputs: list[dict[str, Any]]
    step_count: int
    visual_assets: dict[str, bytes]
    used_llm: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def input_count(self) -> int:
        return len(self.inputs)


@dataclass
class PersistedWorkflow:
    """API-facing summary for a workflow already written to bundle storage."""

    name: str
    bundle_slug: str
    index_json: str
    execution_json: str
    recovery_json: str
    inputs_json: str
    manifest_json: str
    input_count: int
    step_count: int
    used_llm: bool
    warnings: list[str] = field(default_factory=list)

    def to_response_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bundle_slug": self.bundle_slug,
            "index_json": self.index_json,
            "execution_json": self.execution_json,
            "recovery_json": self.recovery_json,
            "inputs_json": self.inputs_json,
            "manifest_json": self.manifest_json,
            "input_count": self.input_count,
            "step_count": self.step_count,
            "used_llm": self.used_llm,
            "warnings": list(self.warnings),
        }


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
_HYPHEN_COLLAPSE_RE = re.compile(r"-+")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^a-zA-Z0-9]+")
_TEXT_SELECTOR_RE = re.compile(r"^\s*text\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|(.+?))\s*$", re.IGNORECASE)
_INPUT_NAME_RE = re.compile(r"input\s*\[\s*name\s*=\s*['\"]?([^'\"\]]+)['\"]?\s*\]", re.IGNORECASE)

_STEP_LIST_KEYS = ("steps", "actions", "events", "recorded_events", "interactions", "workflow_steps")
_STEP_CONTAINER_KEYS = ("skills", "workflows", "flows", "scenarios", "recordings")
_METADATA_KEYS = ("meta", "package_meta", "metadata", "package", "workflow", "recording", "session")
_TITLE_KEYS = ("title", "name", "id", "slug", "workflow_name", "workflowName")
_INPUT_CONTAINER_KEYS = ("inputs", "parameters", "params", "variables")
_INPUT_DECLARATION_KEYS = frozenset(_INPUT_CONTAINER_KEYS)
_INPUT_NAME_KEYS = ("name", "id", "key", "label", "input_name", "inputName", "field", "binding")
_STEP_VISUAL_KEYS = ("full_screenshot", "scroll_screenshot", "element_snapshot")
_STEP_SCREENSHOT_URL_KEYS = ("full_url", "scroll_url", "element_url")

_ALLOWED_STRUCTURED_TYPES = {"navigate", "fill", "click", "scroll"}
_ALLOWED_EXECUTION_TYPES = {"navigate", "fill", "click", "assert_visible", "scroll"}
_GENERIC_SELECTORS = {"input", "button", "textarea", "select"}
_GENERIC_LABELS = {"input", "button", "textarea", "select"}
_SENSITIVE_HINTS = ("password", "passcode", "passwd", "secret", "token", "api_key", "apikey", "private_key", "credential", "auth", "otp", "pin")
_LOGIN_TEXT = ("sign in", "signin", "log in", "login")
_DESTRUCTIVE_TEXT = ("delete", "remove", "destroy", "drop", "archive", "reset", "disable", "revoke")
_RECOVERY_VISUAL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _parse_json_text(json_text: str) -> Any:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, (dict, list)):
        raise ValueError("JSON root must be an object or array.")
    return payload


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
    _logger.info(f"Plugin JSON preprocessed. Size reduction: {original_size} → {cleaned_size} bytes")
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
    """Deep-copy raw recording steps and drop heavy fields only for the structuring LLM.

    The on-disk payload still carries screenshots for asset collection; the chat
    request omits ``screenshot`` / ``visual`` / ``signals.visual`` / ``extras.session_id``
    to shrink tokens.
    """

    return [_sanitize_recording_step_for_llm(step) for step in raw_steps if isinstance(step, dict)]


def _sanitize_recording_step_for_llm(step: dict[str, Any]) -> dict[str, Any]:
    c = copy.deepcopy(step)
    c.pop("screenshot", None)
    c.pop("visual", None)
    sig = c.get("signals")
    if isinstance(sig, dict):
        sig.pop("visual", None)
        if not sig:
            c.pop("signals", None)
    extras = c.get("extras")
    if isinstance(extras, dict):
        extras.pop("session_id", None)
        if not extras:
            c.pop("extras", None)
    return c


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


def slugify_skill_package_folder_name(value: str) -> str:
    """Stable slug for workflow folder names under ``workflows/``."""

    return _slugify_name(value)


def slugify_skill_bundle_name(value: str | None) -> str:
    """Stable slug for a named skill package bundle under ``output/skill_package/``."""

    return _slugify_name(value or "default")


def hyphen_skill_plugin_name(raw_slug: str) -> str:
    """Normalize a slug to hyphen-case for OpenCode / Claude / Codex skill folder ``name`` fields."""

    base = str(raw_slug or "").strip().lower().replace("_", "-")
    base = _HYPHEN_COLLAPSE_RE.sub("-", base).strip("-")
    if not base:
        base = "generated-skill"
    if len(base) > 64:
        base = base[:64].strip("-")
    return base or "generated-skill"


def skill_package_agent_plugin_name(bundle_slug: str, workflow_slug: str) -> str:
    """Per-workflow plugin folder name: ``<bundle>_<workflow>`` → hyphen form (e.g. ``render`` + ``deploy_app`` → ``render-deploy-app``)."""

    return hyphen_skill_plugin_name(f"{bundle_slug}_{workflow_slug}")


def _bundle_skill_file_path(bundle_slug: str) -> str:
    """Return path to orchestration/index.md (the entry-point for Claude in new layout)."""
    return "orchestration/index.md"


def _resolve_bundle_slug(explicit: str | None) -> str:
    slug = slugify_skill_bundle_name(explicit)
    if not validate_bundle_slug(slug):
        raise ValueError(f'Invalid skill package name "{explicit}". Reserved or malformed slugs are not allowed.')
    return slug


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
    parsed_call = urlparse(url)
    api_path = (parsed_call.path or "/").strip() or "/"
    strict_json_response = body.get("response_format") is not None
    _timeout_s = max(0.2, settings.pack_llm_timeout_ms / 1000.0)
    # Transient 5xx retries: up to this many HTTP POSTs total (initial + retries).
    max_tries = 3
    raw_step_count = len(raw_steps)

    raw = ""
    for attempt in range(max_tries):
        headers = {"Content-Type": "application/json"}
        pack_key, _, _ = next_pack_api_key()
        if pack_key:
            headers["Authorization"] = f"Bearer {pack_key}"

        req = request.Request(url, data=raw_body, headers=headers, method="POST")
        skill_pack_log_append(
            {
                "kind": "llm_request_sent",
                "attempt": attempt + 1,
                "model": model,
                "host": (parsed_ep.netloc or "").lower() or None,
                "path": api_path,
                "timeout_ms": int(settings.pack_llm_timeout_ms),
                "payload_bytes": len(raw_body),
                "raw_step_count": raw_step_count,
                "max_attempts": max_tries,
                "strict_json_response": strict_json_response,
            }
        )
        t0 = time.perf_counter()
        try:
            with request.urlopen(req, timeout=_timeout_s) as res:
                raw = res.read().decode("utf-8")
                skill_pack_log_append(
                    {
                        "kind": "llm_response_received",
                        "attempt": attempt + 1,
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                        "response_chars": len(raw),
                    }
                )
                break
        except error.HTTPError as exc:
            err_preview = ""
            try:
                err_chunk = exc.read()
                err_preview = err_chunk.decode("utf-8", errors="replace").strip().replace("\n", " ")[:1400]
            except Exception:
                err_preview = ""
            elapsed_http = round((time.perf_counter() - t0) * 1000, 2)
            skill_pack_log_append(
                {
                    "kind": "llm_http_error",
                    "attempt": attempt + 1,
                    "status": exc.code,
                    "reason": str(exc.reason),
                    "elapsed_ms": elapsed_http,
                    "response_body_chars": len(err_preview),
                    **({"response_body_preview": err_preview} if err_preview else {}),
                }
            )
            if exc.code in _PACK_LLM_TRANSIENT_HTTP and attempt < max_tries - 1:
                skill_pack_log_append(
                    {"kind": "llm_retry", "attempt": attempt + 1, "reason": f"HTTP {exc.code}"}
                )
                continue
            _logger.warning(
                "LLM structuring HTTP failure final host=%s path=%s model=%s steps=%s attempt=%s/%s status=%s elapsed_ms=%s preview=%s",
                (parsed_ep.netloc or "").lower(),
                api_path,
                model,
                raw_step_count,
                attempt + 1,
                max_tries,
                exc.code,
                elapsed_http,
                (err_preview[:240] + "…") if len(err_preview) > 240 else err_preview,
            )
            msg = (
                f"LLM structuring request failed (HTTP {exc.code}: {exc.reason!s}); "
                f"attempt {attempt + 1}/{max_tries}, {raw_step_count} raw steps, POST {api_path}."
            )
            if err_preview:
                frag = err_preview[:420]
                if len(err_preview) > 420:
                    frag += "…"
                msg += f" Response body fragment: {frag}"
            raise ValueError(msg) from exc
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            is_timeout = isinstance(exc, TimeoutError) or (
                isinstance(exc, error.URLError)
                and exc.reason is not None
                and "timed out" in str(exc.reason).lower()
            )
            if is_timeout:
                skill_pack_log_append(
                    {
                        "kind": "llm_timeout",
                        "attempt": attempt + 1,
                        "timeout_ms": int(settings.pack_llm_timeout_ms),
                        "elapsed_ms": elapsed_ms,
                        "path": api_path,
                        "raw_step_count": raw_step_count,
                    }
                )
            else:
                skill_pack_log_append(
                    {
                        "kind": "llm_network_error",
                        "attempt": attempt + 1,
                        "elapsed_ms": elapsed_ms,
                        "detail": str(exc)[:500],
                        "exc_type": type(exc).__name__,
                    }
                )
            detail = (
                f"LLM structuring request failed ({type(exc).__name__}); attempt {attempt + 1}/{max_tries}; "
                f"{raw_step_count} raw steps; POST {api_path}: {exc!s}"
            )
            _logger.warning("LLM structuring transport error %s", detail[:700])
            raise ValueError(detail) from exc

    t_parse0 = time.perf_counter()
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM structuring provider returned invalid JSON.") from exc
    skill_pack_log_append(
        {
            "kind": "llm_response_parsed",
            "elapsed_ms": round((time.perf_counter() - t_parse0) * 1000, 2),
            "response_chars": len(raw),
            **(
                {"top_level_keys": sorted(response.keys())}
                if isinstance(response, dict) and len(response) <= 24
                else {"dict_key_estimate": len(response) if isinstance(response, dict) else 0}
            ),
        }
    )
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
    structured = _call_structuring_llm(sanitize_raw_steps_for_llm(raw_steps))
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
            _append_step(plan, {"type": "assert_visible", "selector": "text=New"})
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
    role = "textbox" if step.get("type") == "fill" else ""
    return {"text": text, "role": role}


def _recovery_slug_from_step(step: dict[str, Any]) -> str:
    target = _selector_target(step)
    raw = " ".join(part for part in (str(step.get("type") or ""), target["text"] or target["role"] or "action") if part)
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
    if step.get("type") == "fill":
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


def _anchors_for_step(step: dict[str, Any], target: dict[str, str]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    target_text = _sanitize_recovery_label(target.get("text"))
    lowered = target_text.lower()
    if any(token in lowered for token in _LOGIN_TEXT):
        anchors.append({"text": "Login", "priority": 1})
    if any(token in lowered for token in _DESTRUCTIVE_TEXT):
        anchors.append({"text": "Danger Zone", "priority": 1})
    if step.get("type") == "fill" and target_text:
        anchors.append({"text": target_text, "priority": 2})
    elif step.get("type") == "click" and target_text:
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


def _build_recovery_entry(step: dict[str, Any], step_id: int, visuals_dir: Path | None) -> dict[str, Any]:
    selector = _sanitize_recovery_selector(step.get("selector"))
    if not selector:
        raise ValueError(f"Recovery step {step_id} is missing a valid selector.")
    target = _selector_target(step)
    target_text = _sanitize_recovery_label(target.get("text"))
    fallback_role = target.get("role") or ""
    entry: dict[str, Any] = {
        "step_id": step_id,
        "intent": _recovery_slug_from_step(step),
        "target": {
            "text": target_text,
            "role": target.get("role") or "",
        },
        "anchors": _anchors_for_step(step, target),
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


def _validate_recovery_entries(compiled: list[dict[str, Any]], entries: list[dict[str, Any]], visuals_dir: Path | None) -> None:
    actionable_steps = [index for index, step in enumerate(compiled, start=1) if step.get("type") in {"fill", "click"}]
    if len(entries) != len(actionable_steps):
        raise ValueError("Every compiled fill/click step must have exactly one recovery entry.")
    by_step_id: dict[int, list[dict[str, Any]]] = {}
    for entry in entries:
        by_step_id.setdefault(int(entry.get("step_id") or 0), []).append(entry)
        if not str(entry.get("intent") or "").strip():
            raise ValueError("Recovery entries must include intent.")
        anchors = entry.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise ValueError("Recovery entries must include anchors.")
        if not all(_sanitize_recovery_label(_get_mapping(anchor).get("text")) for anchor in anchors):
            raise ValueError("Recovery anchors must use non-generic text labels.")
        fallback = _get_mapping(entry.get("fallback"))
        text_variants = fallback.get("text_variants")
        if not isinstance(text_variants, list) or not text_variants:
            raise ValueError("Recovery fallback.text_variants is required.")
        if not all(_sanitize_recovery_label(item) for item in text_variants):
            raise ValueError("Recovery fallback.text_variants must be non-generic labels.")
        selector_context = _get_mapping(entry.get("selector_context"))
        primary = _sanitize_recovery_selector(selector_context.get("primary"))
        alternatives = selector_context.get("alternatives")
        if not primary or not isinstance(alternatives, list):
            raise ValueError("Recovery selector_context must include primary and alternatives.")
        if any(not _sanitize_recovery_selector(item) for item in alternatives):
            raise ValueError("Recovery selector_context alternatives must be valid selectors.")
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
                raise ValueError("visual_ref must point to the matching Image_<step_id> asset.")
            if expected_ref is None and actual_ref:
                raise ValueError("visual_ref must be omitted when the step image is missing.")
            if expected_ref is not None and actual_ref != expected_ref:
                raise ValueError("visual_ref must be present only for matching step images.")
    for step_id in actionable_steps:
        if len(by_step_id.get(step_id, [])) != 1:
            raise ValueError("Every compiled fill/click step must have exactly one recovery entry.")


def generate_recovery(
    structured_steps: dict[str, Any] | list[dict[str, Any]],
    visuals_dir: Path | None = None,
) -> dict[str, Any]:
    compiled = compile_execution(structured_steps)
    entries: list[dict[str, Any]] = []
    for index, step in enumerate(compiled, start=1):
        if step.get("type") not in {"fill", "click"}:
            continue
        entries.append(_build_recovery_entry(step, index, visuals_dir))
    _validate_recovery_entries(compiled, entries, visuals_dir)
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
    raw_workflows = _enumerate_raw_workflows(payload)
    if not raw_workflows:
        raise ValueError("No workflow steps detected in JSON.")
    total = len(raw_workflows)
    skill_pack_log_append({"kind": "bundle_compile_outline", "workflow_count": total})
    compiled: list[CompiledWorkflow] = []
    for index, raw_workflow in enumerate(raw_workflows, start=1):
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
        explicit_name = package_name if len(raw_workflows) == 1 else None
        compiled.append(
            _compile_workflow_payload(
                raw_workflow.payload,
                raw_workflow.steps,
                package_name=explicit_name,
                source_title=label,
            )
        )
        skill_pack_log_append(
            {"kind": "workflow_compile_complete", "index": index, "total": total, "package_name": compiled[-1].name}
        )
    return compiled


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
    write_skill_package_files(
        bundle_slug,
        compiled.name,
        _workflow_file_payload(compiled),
        visual_assets=compiled.visual_assets,
    )
    # Build plugin index JSON from disk (handles multi-skill append correctly)
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
        if title_hint and title_hint != "generated_skill" and not _first_text_from_keys(payload, _TITLE_KEYS):
            payload["title"] = title_hint
        if source_session_id and not _source_session_id(payload):
            payload["package_meta"] = {**_get_mapping(payload.get("package_meta")), "source_session_id": source_session_id}
    return preprocess_skill_pack_declarations(payload)


def _prepare_append_payload(json_text: str) -> Any:
    """Alias for append callers so the append path shares the same cleanup pipeline."""

    return _prepare_skill_package_payload(json_text)


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
    return [_persist_skill_package_artifacts(compiled, bundle_slug) for compiled in compiled_workflows]


def _ensure_new_workflow_names(bundle_slug: str, compiled_workflows: list[CompiledWorkflow]) -> None:
    for compiled in compiled_workflows:
        if resolve_workflow_dir(bundle_slug, compiled.name):
            raise ValueError(f'Workflow "{compiled.name}" already exists in bundle "{bundle_slug}".')


def _read_bundle_entry_markdown(bundle_slug: str) -> str:
    return _read_bundle_skill_markdown(bundle_slug)


def _read_bundle_skill_markdown(bundle_slug: str) -> str:
    bundle_root = bundle_root_dir(bundle_slug)
    if bundle_root is None:
        return ""

    skill_path = bundle_root / _bundle_skill_file_path(bundle_slug)
    if not skill_path.is_file():
        return ""
    return skill_path.read_text(encoding="utf-8")


def _format_build_skill_package_result(
    persisted_workflows: list[PersistedWorkflow],
    *,
    bundle_slug: str,
    index_json: str,
    build_log: list[dict[str, Any]],
) -> dict[str, Any]:
    if not persisted_workflows:
        raise ValueError("No compiled workflows were persisted.")

    workflow_names = [item.name for item in persisted_workflows]
    result = persisted_workflows[0].to_response_dict()
    result["index_json"] = index_json
    result["skill_md"] = _read_bundle_skill_markdown(bundle_slug)
    result["workflow_names"] = workflow_names
    result["build_log"] = build_log
    return result


def _format_append_workflow_result(
    persisted_workflows: list[PersistedWorkflow],
    *,
    bundle_slug: str,
    index_json: str,
    build_log: list[dict[str, Any]],
) -> dict[str, Any]:
    if not persisted_workflows:
        raise ValueError("No appended workflows were persisted.")

    result = persisted_workflows[0].to_response_dict()
    result["index_json"] = index_json
    result["skill_md"] = _read_bundle_entry_markdown(bundle_slug)
    result["workflow_names"] = [item.name for item in persisted_workflows]
    result["build_log"] = build_log
    return result


def _build_skill_package_transaction(
    json_text: str,
    package_name: str | None,
    bundle_slug: str | None,
    build_log: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = _prepare_skill_package_payload(json_text)
    resolved_bundle_slug = _resolve_bundle_slug(bundle_slug)

    _log_persist_phase_start(resolved_bundle_slug, package_name)

    compiled_workflows = _compile_skill_package_payloads(payload, package_name=package_name)
    persisted_workflows = _persist_compiled_workflows(compiled_workflows, resolved_bundle_slug)
    refreshed_index_json = _refresh_bundle_runtime_files(resolved_bundle_slug)

    result = _format_build_skill_package_result(
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
        except ValueError as exc:
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
            payload = _prepare_append_payload(json_text)
            compiled_workflows = _compile_skill_package_payloads(payload, package_name=appended_package_name)
            _ensure_new_workflow_names(slug, compiled_workflows)
            for compiled in compiled_workflows:
                compiled.warnings = [f'Added workflow "{compiled.name}" to bundle "{slug}".']
            persisted = _persist_compiled_workflows(compiled_workflows, slug)
            index_json = _refresh_bundle_runtime_files(slug)
            return _format_append_workflow_result(
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

    # Infer auth and build per-skill inputs list from inputs_json
    inputs_list = _parse_existing_inputs(inputs_json)
    auth_config = infer_auth_config(inputs_list)
    sensitive = [i for i in inputs_list if i.get("sensitive")]
    description = _manifest_description(name, json.loads(manifest_json).get("description", ""))

    # Plugin index (single-skill export)
    plugin_index = format_plugin_index_json(
        bundle_segment,
        [{"name": name, "description": description}],
    )
    readme = format_plugin_readme_text(bundle_segment, [{"name": name, "description": description}])
    test_cases = format_test_cases_stub_json_text(inputs_list)

    # Per-skill SKILL.md (simple version from manifest data since structured steps not available here)
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
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        # Bundle-level files
        archive.writestr(f"{bundle_folder}/{bundle_segment}.json", plugin_index)
        archive.writestr(f"{bundle_folder}/README.md", readme)
        archive.writestr(f"{bundle_folder}/auth/auth.json", format_auth_json_text(auth_config))
        archive.writestr(f"{bundle_folder}/auth/credentials.example.json", format_credentials_example_json_text(sensitive))
        # Orchestration
        archive.writestr(f"{bundle_folder}/orchestration/index.md", orch_index)
        archive.writestr(f"{bundle_folder}/orchestration/planner.md", orch_planner)
        archive.writestr(f"{bundle_folder}/orchestration/schema.json", _ORCHESTRATION_SCHEMA_JSON + "\n")
        # Execution scaffolds
        archive.writestr(f"{bundle_folder}/package.json", _PACKAGE_JSON)
        archive.writestr(f"{bundle_folder}/execution/executor.js", _EXECUTOR_JS)
        archive.writestr(f"{bundle_folder}/execution/recovery.js", _RECOVERY_JS)
        archive.writestr(f"{bundle_folder}/execution/tracker.js", _TRACKER_JS)
        archive.writestr(f"{bundle_folder}/execution/validator.js", _VALIDATOR_JS)
        # Per-skill files
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
                # Drop duplicate top-level segments when on-disk tree is `<slug>/<slug>/…`.
                while rel.startswith(f"{slug}/"):
                    rel = rel[len(slug) + 1 :]
                arcname = f"{zip_prefix}/{rel}"
                archive.write(path, arcname)
    return f"{slug}.zip", buffer.getvalue()
