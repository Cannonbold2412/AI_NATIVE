"""Shared constants and primitive helpers for skill package builds."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_HYPHEN_COLLAPSE_RE = re.compile(r"-+")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^a-zA-Z0-9]+")
_TEXT_SELECTOR_RE = re.compile(
    r"^\s*text\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|(.+?))\s*$", re.IGNORECASE
)
_INPUT_NAME_RE = re.compile(
    r"input\s*\[\s*name\s*=\s*['\"]?([^'\"\]]+)['\"]?\s*\]", re.IGNORECASE
)

_STEP_LIST_KEYS = (
    "steps",
    "actions",
    "events",
    "recorded_events",
    "interactions",
    "workflow_steps",
)
_STEP_CONTAINER_KEYS = ("skills", "workflows", "flows", "scenarios", "recordings")
_METADATA_KEYS = (
    "meta",
    "package_meta",
    "metadata",
    "package",
    "workflow",
    "recording",
    "session",
)
_TITLE_KEYS = ("title", "name", "id", "slug", "workflow_name", "workflowName")
_INPUT_CONTAINER_KEYS = ("inputs", "parameters", "params", "variables")
_INPUT_DECLARATION_KEYS = frozenset(_INPUT_CONTAINER_KEYS)
_INPUT_NAME_KEYS = (
    "name",
    "id",
    "key",
    "label",
    "input_name",
    "inputName",
    "field",
    "binding",
)
_STEP_VISUAL_KEYS = ("full_screenshot", "scroll_screenshot", "element_snapshot")
_STEP_SCREENSHOT_URL_KEYS = ("full_url", "scroll_url", "element_url")

_ALLOWED_STRUCTURED_TYPES = {
    "navigate",
    "fill",
    "type",
    "click",
    "select",
    "focus",
    "scroll",
    "check",
}
_TEXT_INPUT_STEP_TYPES = {"fill", "type"}
_SELECTOR_ONLY_STEP_TYPES = {"select", "focus"}
_CHECK_KINDS = {"url", "url_exact", "snapshot", "selector", "text"}
_GENERIC_SELECTORS = {"input", "button", "textarea", "select"}
_GENERIC_LABELS = {"input", "button", "textarea", "select"}
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
_LOGIN_TEXT = ("sign in", "signin", "log in", "login")
_DESTRUCTIVE_TEXT = (
    "delete",
    "remove",
    "destroy",
    "drop",
    "archive",
    "reset",
    "disable",
    "revoke",
)
_RECOVERY_VISUAL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


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
