"""Plugin-first build pipeline.

Compiles a Plugin entity (auth session + N workflow sessions) into a
data-only skill pack folder:

  output/skill_package/{bundle_slug}-plugin/
    plugin.json                   <- plugin manifest
    README.md                     <- auto-generated, public-facing
    CLAUDE.md                     <- Claude reads this for skill discovery
    .gitignore                    <- excludes auth/auth.json and local state
    LICENSE                       <- MIT by default
    auth/                         <- runtime-local auth directory only
    skills/
      {workflow_slug}/            <- one per workflow, login steps stripped

auth/auth.json and auth/credentials*.json are NEVER placed in the build output.
Credentials are local runtime state captured by the installed Conxa runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from zipfile import ZIP_DEFLATED, ZipFile

from app.compiler.action_policy import RECOVERY_ACTION_TYPES
from app.editor.action_registry import is_marker_action, is_supported_action, normalize_action_kind
from app.editor.assets import resolve_skill_asset
from app.llm.anchor_vision_llm import _apply_bbox_highlight
from app.storage.plugin_store import get_plugin, set_build
from app.storage.json_store import read_skill

# ─────────────────────────────────────────────────
# Login-step detection
# ─────────────────────────────────────────────────
_LOGIN_MARKERS = frozenset(
    {
        "login", "log in", "log-in", "signin", "sign in", "sign-in",
        "username", "password", "email", "forgot password", "remember me",
    }
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PLACEHOLDER_RE = re.compile(r"^\{\{[a-zA-Z][a-zA-Z0-9_]*\}\}$")
_PLACEHOLDER_NAME_RE = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}")
_TEXT_SELECTOR_RE = re.compile(r"^text=(?P<quote>['\"]?)(?P<text>.+?)(?P=quote)$")


def _to_bundle_slug(text: str) -> str:
    slug = _SLUG_RE.sub("_", text.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"p_{slug}"
    return slug[:40]


def _is_login_step(step: dict[str, Any]) -> bool:
    """Heuristic: step touches a login page or login-related element."""
    page_url = str((step.get("page") or {}).get("url") or "").lower()
    page_title = str((step.get("page") or {}).get("title") or "").lower()
    target_text = str((step.get("target") or {}).get("inner_text") or "").lower()
    semantic_text = str((step.get("semantic") or {}).get("normalized_text") or "").lower()
    aria = str((step.get("target") or {}).get("aria_label") or "").lower()

    haystack = " ".join([page_url, page_title, target_text, semantic_text, aria])
    return any(marker in haystack for marker in _LOGIN_MARKERS)


def strip_login_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove events that belong to a login sequence from workflow recordings."""
    if not events:
        return events

    has_login = any(_is_login_step(e) for e in events)
    if not has_login:
        return events

    login_urls: set[str] = set()
    for e in events:
        if _is_login_step(e):
            url = str((e.get("page") or {}).get("url") or "")
            if url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    login_urls.add(f"{parsed.scheme}://{parsed.netloc}")
                    login_urls.add(url.split("?")[0])
                except Exception:
                    login_urls.add(url)

    if not login_urls:
        return events

    filtered = [e for e in events if not _is_login_step(e)]
    return filtered if filtered else events


# ─────────────────────────────────────────────────
# Session → JSON payload conversion
# ─────────────────────────────────────────────────

def _events_to_json_text(events: list[dict[str, Any]], title: str) -> str:
    return json.dumps({"title": title, "steps": events}, ensure_ascii=False)


def _step_action_name(step: dict[str, Any]) -> str:
    action = step.get("action") or {}
    if isinstance(action, dict):
        return str(action.get("action") or "").strip().lower()
    return str(action or "").strip().lower()


def _step_selector(step: dict[str, Any]) -> str:
    target = step.get("target") if isinstance(step.get("target"), dict) else {}
    selector = str(target.get("primary_selector") or "").strip()
    if selector:
        return selector
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    if isinstance(action, dict):
        selector = str(action.get("selector") or action.get("css_selector") or "").strip()
        if selector:
            return selector
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    selectors = signals.get("selectors") if isinstance(signals.get("selectors"), dict) else {}
    return str(selectors.get("css") or selectors.get("text_based") or selectors.get("aria") or "").strip()


def _step_url(step: dict[str, Any]) -> str:
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    if isinstance(action, dict):
        url = str(action.get("url") or "").strip()
        if url:
            return url
    url = str(step.get("url") or "").strip()
    if url:
        return url
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    context = signals.get("context") if isinstance(signals.get("context"), dict) else {}
    return str(context.get("page_url") or "").strip()


def _saved_step_intents(step: dict[str, Any]) -> set[str]:
    intents = {str(step.get("intent") or "").strip().lower()}
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    semantic = signals.get("semantic") if isinstance(signals.get("semantic"), dict) else {}
    intents.add(str(semantic.get("final_intent") or "").strip().lower())
    intents.add(str(semantic.get("llm_intent") or "").strip().lower())
    recovery = step.get("recovery") if isinstance(step.get("recovery"), dict) else {}
    intents.add(str(recovery.get("final_intent") or "").strip().lower())
    return {intent for intent in intents if intent}


def _has_meaningful_export_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_export_payload(item) for item in value)
    if isinstance(value, dict):
        return any(_has_meaningful_export_payload(item) for item in value.values())
    return bool(value)


def _has_user_interaction_payload(step: dict[str, Any]) -> bool:
    if _step_selector(step):
        return True

    target = step.get("target")
    if isinstance(target, dict) and _has_meaningful_export_payload(target):
        return True

    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    selectors = signals.get("selectors") if isinstance(signals.get("selectors"), dict) else {}
    if _has_meaningful_export_payload(selectors):
        return True

    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    if isinstance(action, dict):
        for key, value in action.items():
            if key in {"action", "url"}:
                continue
            if _has_meaningful_export_payload(value):
                return True

    for key in ("value", "input_binding", "frame", "check_kind", "check_pattern", "check_selector", "check_text"):
        if _has_meaningful_export_payload(step.get(key)):
            return True
    return False


def _is_legacy_synthetic_start_navigation_step(step: dict[str, Any]) -> bool:
    if normalize_action_kind(_step_action_name(step)) != "navigate":
        return False
    if "navigate_to_start_url" not in _saved_step_intents(step):
        return False
    return not _has_user_interaction_payload(step)


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
        out_chain.append(
            {
                "selector": selector,
                "fallback_selectors": fallbacks,
                "url": str(item.get("url") or "").strip(),
                "url_pattern": str(item.get("url_pattern") or "").strip(),
            }
        )
    return {"chain": out_chain} if out_chain else {}


def _copy_frame(step: dict[str, Any], out: dict[str, Any]) -> None:
    frame = _sanitize_runtime_frame(step.get("frame"))
    if frame:
        out["frame"] = frame


def _step_action_value(step: dict[str, Any]) -> Any:
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    if isinstance(action, dict) and action.get("value") is not None:
        return action.get("value")
    return step.get("value")


def _action_value_text(step: dict[str, Any]) -> str:
    value = _step_action_value(step)
    if value is None:
        return ""
    return str(value)


def _action_value_json(step: dict[str, Any]) -> dict[str, Any]:
    value = _step_action_value(step)
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _copy_saved_common(step: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    _copy_frame(step, out)
    return out


def _saved_check_like_step(step: dict[str, Any], action: str) -> dict[str, Any] | None:
    kind = str(step.get("check_kind") or "url").strip().lower().replace("-", "_")
    out: dict[str, Any] = {"type": action, "kind": "url_exact" if kind in {"url_must_be", "exact_url"} else kind}
    if out["kind"] == "url":
        out["pattern"] = str(step.get("check_pattern") or _step_url(step) or "")
    elif out["kind"] == "url_exact":
        out["url"] = str(step.get("check_pattern") or _step_url(step) or "")
    elif out["kind"] == "selector":
        out["selector"] = str(step.get("check_selector") or _step_selector(step) or "")
    elif out["kind"] == "text":
        out["text"] = str(step.get("check_text") or "")
    elif out["kind"] == "snapshot":
        out["threshold"] = float(step.get("check_threshold") or 0.9)
    if not any(k in out and out[k] for k in ("pattern", "url", "selector", "text", "threshold")):
        return None
    return _copy_saved_common(step, out)


def _saved_step_to_execution_step(step: dict[str, Any]) -> dict[str, Any] | None:
    action = normalize_action_kind(_step_action_name(step))
    if not is_supported_action(action):
        return None

    if is_marker_action(action):
        out: dict[str, Any] = {"type": action, "recording_marker": True}
        value = _action_value_text(step)
        if value:
            out["value"] = value
        return _copy_saved_common(step, out)

    if action == "navigate":
        url = _step_url(step)
        if not url:
            return None
        return _copy_saved_common(step, {"type": "navigate", "url": url})

    if action in {"click", "focus", "hover", "dblclick", "right_click"}:
        selector = _step_selector(step)
        if not selector:
            return None
        return _copy_saved_common(step, {"type": action, "selector": selector})

    if action in {"type", "fill", "date_pick"}:
        selector = _step_selector(step)
        if not selector:
            return None
        return _copy_saved_common(step, {"type": action, "selector": selector, "value": _action_value_text(step)})

    if action in {"select", "select_option", "set_checkbox", "set_radio"}:
        selector = _step_selector(step)
        if not selector:
            return None
        out = {"type": action, "selector": selector}
        value = _action_value_text(step)
        if value:
            out["value"] = value
        return _copy_saved_common(step, out)

    if action == "scroll":
        action_block = step.get("action") if isinstance(step.get("action"), dict) else {}
        selector = _step_selector(step)
        out = {"type": "scroll"}
        if selector:
            out["selector"] = selector
        else:
            delta = action_block.get("delta") if isinstance(action_block, dict) else None
            if delta is None:
                delta = step.get("scroll_amount")
            out["delta_y"] = float(delta if delta is not None else 600)
        return _copy_saved_common(step, out)

    if action in {"check", "assert"}:
        return _saved_check_like_step(step, action)

    if action == "wait":
        action_block = step.get("action") if isinstance(step.get("action"), dict) else {}
        raw_ms = action_block.get("ms") if isinstance(action_block, dict) else None
        raw_ms = raw_ms if raw_ms is not None else _action_value_text(step)
        try:
            ms = int(raw_ms)
        except (TypeError, ValueError):
            ms = 1000
        return _copy_saved_common(step, {"type": "wait", "ms": max(ms, 0)})

    if action == "screenshot":
        return _copy_saved_common(step, {"type": "screenshot"})

    if action == "keyboard_shortcut":
        value = _action_value_text(step)
        if not value:
            return None
        return _copy_saved_common(step, {"type": "keyboard_shortcut", "value": value})

    if action == "drag_drop":
        payload = _action_value_json(step)
        selector = _step_selector(step)
        src = str(payload.get("src_selector") or payload.get("src_css") or "").strip()
        dst = str(payload.get("dst_selector") or payload.get("dst_css") or selector or "").strip()
        if not src or not dst:
            return None
        return _copy_saved_common(step, {"type": "drag_drop", "src_selector": src, "dst_selector": dst})

    if action in {"upload", "upload_intent"}:
        selector = _step_selector(step)
        value = _action_value_text(step) or "{{file_path}}"
        out = {"type": "upload", "value": value}
        if selector:
            out["selector"] = selector
        return _copy_saved_common(step, out)

    return None


def _normalize_saved_skill_inputs(inputs: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in inputs:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("id") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        row: dict[str, Any] = {
            "name": name,
            "type": "string",
            "description": str(raw.get("description") or raw.get("label") or f"Enter {name.replace('_', ' ')}"),
        }
        if raw.get("sensitive"):
            row["sensitive"] = True
        options = raw.get("options")
        if isinstance(options, list) and options:
            row["enum"] = [str(item) for item in options if str(item)]
        out.append(row)
    return out


def _placeholder_names_from_payload(payload: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            for match in _PLACEHOLDER_NAME_RE.finditer(value):
                name = match.group(1)
                if name not in seen:
                    seen.add(name)
                    names.append(name)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(payload)
    return names


def _merge_saved_inputs_with_execution_placeholders(
    declared_inputs: list[Any],
    execution_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    inputs = _normalize_saved_skill_inputs(declared_inputs)
    seen = {str(item.get("name") or "") for item in inputs}
    for name in _placeholder_names_from_payload(execution_steps):
        if name in seen:
            continue
        seen.add(name)
        inputs.append(
            {
                "name": name,
                "type": "string",
                "description": f"Enter {name.replace('_', ' ')}",
            }
        )
    return inputs


def _render_saved_skill_markdown(title: str, inputs: list[dict[str, Any]], execution_steps: list[dict[str, Any]]) -> str:
    lines = [f"# {title}", "", "## Inputs"]
    if inputs:
        for item in inputs:
            lines.append(f"- `{{{{{item['name']}}}}}`: {item.get('description') or 'Runtime input'}.")
    else:
        lines.append("- No runtime inputs are required.")
    lines.extend(["", "## Steps"])
    for index, step in enumerate(execution_steps, start=1):
        step_type = step.get("type")
        if step_type == "navigate":
            label = f"Open {step.get('url')}"
        elif step_type in {"fill", "type"}:
            label = f"Enter {step.get('value', '')}"
        elif step_type == "click":
            label = f"Click {step.get('selector')}"
        elif step_type == "check":
            label = f"Check {step.get('kind', 'url')}"
        else:
            label = str(step_type or "Run step")
        lines.append(f"{index}. {label}")
    return "\n".join(lines).strip() + "\n"


def _text_selector_value(selector: Any) -> str:
    text = str(selector or "").strip()
    match = _TEXT_SELECTOR_RE.match(text)
    if not match:
        return ""
    return match.group("text").strip()


def _quote_text_selector(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'text="{escaped}"'


def _repair_parameterized_search_result_selectors(execution_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use pure typed placeholders for the immediately selected search result."""
    out: list[dict[str, Any]] = []
    pending_placeholder = ""
    for step in execution_steps:
        step_copy = dict(step)
        step_type = str(step_copy.get("type") or "")
        value = str(step_copy.get("value") or "").strip()

        if step_type in {"type", "fill"} and _PLACEHOLDER_RE.match(value):
            pending_placeholder = value
        elif step_type == "click" and pending_placeholder:
            selector_value = _text_selector_value(step_copy.get("selector"))
            if selector_value and "{{" not in selector_value:
                step_copy["selector"] = _quote_text_selector(pending_placeholder)
            pending_placeholder = ""
        elif step_type not in {"focus", "scroll"}:
            pending_placeholder = ""

        out.append(step_copy)
    return out


def _normalize_recovery_name(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or "action"


def _target_text_from_selector(selector: str) -> str:
    text_value = _text_selector_value(selector)
    if text_value:
        return " ".join(text_value.split())
    match = re.search(r"input\s*\[\s*name\s*=\s*['\"]([^'\"]+)['\"]\s*\]", selector or "", re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _saved_recovery_anchors(step: dict[str, Any], target_text: str) -> list[dict[str, Any]]:
    recovery = step.get("recovery") if isinstance(step.get("recovery"), dict) else {}
    raw_anchors = recovery.get("anchors") if isinstance(recovery.get("anchors"), list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_anchors:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or raw.get("element") or "").strip()
        if "{{" in target_text and "{{" not in text:
            continue
        if not text or text in seen:
            continue
        relation = str(raw.get("relation") or "").strip().lower()
        priority = 2 if relation == "target" or text == target_text else 1
        out.append({"text": text, "priority": priority})
        seen.add(text)
    if target_text and target_text not in seen:
        out.append({"text": target_text, "priority": 2})
    return out[:4]


def _fallback_text_variants_for_saved_step(target_text: str) -> list[str]:
    variants: list[str] = []
    if target_text:
        variants.append(target_text)
    lowered = target_text.lower()
    if "delete" in lowered:
        variants.extend(["Delete", "Remove"])
    elif "remove" in lowered:
        variants.extend(["Remove", "Delete"])
    elif "continue" in lowered:
        variants.extend(["Continue", "Next"])
    elif "next" in lowered:
        variants.extend(["Next", "Continue"])
    elif "save" in lowered:
        variants.extend(["Save", "Update"])
    out: list[str] = []
    for item in variants:
        clean = " ".join(str(item or "").split())
        if clean and clean not in out:
            out.append(clean)
    return out[:4]


def _saved_step_fallback_selectors(step: dict[str, Any], primary_selector: str, target_text: str) -> list[str]:
    target = step.get("target") if isinstance(step.get("target"), dict) else {}
    raw = target.get("fallback_selectors") if isinstance(target.get("fallback_selectors"), list) else []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        selector = str(item or "").strip()
        if not selector or selector == primary_selector or selector in seen:
            continue
        if "{{" in target_text and "{{" not in selector:
            continue
        if selector.startswith("/") or selector.startswith("./") or selector.startswith("//") or "xpath" in selector.lower():
            continue
        out.append(selector)
        seen.add(selector)
    return out[:5]


def _saved_step_visual_ref(step_id: int, visuals_dir: Path | None) -> str | None:
    if visuals_dir is None:
        return None
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = visuals_dir / f"Image_{step_id}{suffix}"
        if candidate.is_file():
            return f"visuals/{candidate.name}"
    return None


def _repair_saved_step_click_selectors(source_steps: list[dict[str, Any]]) -> list[str]:
    repaired: list[str] = []
    pending_placeholder = ""
    for step in source_steps:
        action = _step_action_name(step)
        if action == "input":
            action = "type"
        selector = _step_selector(step)
        value = str(step.get("value") or "").strip()
        if action in {"type", "fill"} and _PLACEHOLDER_RE.match(value):
            pending_placeholder = value
        elif action == "click" and pending_placeholder:
            selector_value = _text_selector_value(selector)
            if selector_value and "{{" not in selector_value:
                selector = _quote_text_selector(pending_placeholder)
            pending_placeholder = ""
        elif action not in {"focus", "scroll"}:
            pending_placeholder = ""
        repaired.append(selector)
    return repaired


def _saved_visual_asset_path(step: dict[str, Any], source_session_id: str) -> str:
    signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
    visual = signals.get("visual") if isinstance(signals.get("visual"), dict) else {}
    rel = str(visual.get("full_screenshot") or "").strip().replace("\\", "/")
    if not rel or ".." in rel:
        return ""
    if rel.startswith("sessions/"):
        return rel
    if source_session_id and rel.startswith("images/"):
        return f"sessions/{source_session_id}/{rel}"
    return rel


def _write_saved_visual_assets(
    *,
    source_steps: list[dict[str, Any]],
    skill_dir: Path,
    source_session_id: str,
) -> Path | None:
    visuals_dir = skill_dir / "visuals"
    wrote = False
    for index, step in enumerate(source_steps, start=1):
        if not isinstance(step, dict):
            continue
        rel = _saved_visual_asset_path(step, source_session_id)
        if not rel:
            continue
        try:
            source_path = resolve_skill_asset(rel)
        except ValueError:
            continue
        if not source_path.is_file():
            continue
        suffix = source_path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue

        signals = step.get("signals") if isinstance(step.get("signals"), dict) else {}
        visual = signals.get("visual") if isinstance(signals.get("visual"), dict) else {}
        bbox = visual.get("bbox") if isinstance(visual.get("bbox"), dict) else {}
        viewport = str(visual.get("viewport") or "")
        image_bytes = source_path.read_bytes()
        if bbox:
            image_bytes = _apply_bbox_highlight(image_bytes, bbox, viewport, highlight_alpha=0.35)
            suffix = ".jpg"

        visuals_dir.mkdir(parents=True, exist_ok=True)
        (visuals_dir / f"Image_{index}{suffix}").write_bytes(image_bytes)
        wrote = True
    return visuals_dir if wrote else None


def _build_saved_skill_recovery(
    source_steps: list[dict[str, Any]],
    step_ids: list[int],
    visuals_dir: Path | None = None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    repaired_selectors = _repair_saved_step_click_selectors(source_steps)
    for step, step_id, selector in zip(source_steps, step_ids, repaired_selectors):
        action = _step_action_name(step)
        if action == "input":
            action = "type"
        if action not in RECOVERY_ACTION_TYPES:
            continue
        selector = str(selector or "").strip()
        if not selector:
            continue
        target_text = _target_text_from_selector(selector)
        original_selector_text = _target_text_from_selector(_step_selector(step))
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        target_role = "textbox" if action in {"type", "fill"} else str(target.get("role") or "")
        raw_intent = str(step.get("intent") or "").strip()
        old_intent_token = _normalize_recovery_name(original_selector_text)
        if "{{" in target_text and "{{" not in raw_intent and old_intent_token in _normalize_recovery_name(raw_intent):
            intent = f"{action}_{_normalize_recovery_name(target_text)}"
        else:
            intent = raw_intent or f"{action}_{_normalize_recovery_name(target_text or target_role)}"
        entry: dict[str, Any] = {
            "step_id": step_id,
            "intent": intent,
            "target": {
                "text": target_text,
                "role": target_role,
            },
            "anchors": _saved_recovery_anchors(step, target_text),
            "fallback": {
                "text_variants": _fallback_text_variants_for_saved_step(target_text),
                "role": target_role,
            },
            "selector_context": {
                "primary": selector,
                "alternatives": _saved_step_fallback_selectors(step, selector, target_text),
            },
        }
        visual_ref = _saved_step_visual_ref(step_id, visuals_dir)
        if visual_ref:
            entry["visual_ref"] = visual_ref
        entries.append(entry)
    return {"steps": entries}


def _build_workflow_from_saved_skill(
    *,
    bundle_root: Path,
    workflow_slug: str,
    saved_skill: dict[str, Any],
) -> None:
    meta = saved_skill.get("meta") if isinstance(saved_skill.get("meta"), dict) else {}
    title = str(meta.get("title") or workflow_slug).strip() or workflow_slug
    skills = saved_skill.get("skills") if isinstance(saved_skill.get("skills"), list) else []
    block = skills[0] if skills and isinstance(skills[0], dict) else {}
    raw_steps = block.get("steps") if isinstance(block.get("steps"), list) else []
    source_session_id = str(meta.get("source_session_id") or "").strip()
    execution_steps: list[dict[str, Any]] = []
    source_steps: list[dict[str, Any]] = []
    step_ids: list[int] = []
    export_steps = [
        raw
        for raw_index, raw in enumerate(raw_steps)
        if not (
            raw_index == 0
            and isinstance(raw, dict)
            and _is_legacy_synthetic_start_navigation_step(raw)
        )
    ]
    for raw_index, raw in enumerate(export_steps, start=1):
        if not isinstance(raw, dict):
            continue
        converted = _saved_step_to_execution_step(raw)
        if converted is None:
            action = _step_action_name(raw) or "unknown"
            raise ValueError(f"Saved skill step {raw_index} action {action!r} is not exportable.")
        execution_steps.append(converted)
        source_steps.append(raw)
        step_ids.append(len(execution_steps))
    execution_steps = _repair_parameterized_search_result_selectors(execution_steps)
    if not execution_steps:
        raise ValueError(f"Saved skill {meta.get('id') or workflow_slug!r} has no executable steps.")

    inputs = _merge_saved_inputs_with_execution_placeholders(
        list(saved_skill.get("inputs") or []),
        execution_steps,
    )
    skill_dir = bundle_root / "skills" / workflow_slug
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    skill_dir.mkdir(parents=True, exist_ok=True)
    visuals_dir = _write_saved_visual_assets(
        source_steps=source_steps,
        skill_dir=skill_dir,
        source_session_id=source_session_id,
    )
    recovery = _build_saved_skill_recovery(source_steps, step_ids, visuals_dir)
    (skill_dir / "execution.json").write_text(json.dumps(execution_steps, indent=2, ensure_ascii=False), encoding="utf-8")
    (skill_dir / "recovery.json").write_text(json.dumps(recovery, indent=2, ensure_ascii=False), encoding="utf-8")
    (skill_dir / "input.json").write_text(json.dumps({"inputs": inputs}, indent=2, ensure_ascii=False), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(_render_saved_skill_markdown(title, inputs, execution_steps), encoding="utf-8")


# ─────────────────────────────────────────────────
# skill-packs/{company}/ output format
# ─────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _write_skill_packs_format(
    *,
    bundle_root: Path,
    bundle_slug: str,
    plugin_name: str,
    target_url: str,
    protected_url: str,
    skill_slugs: list[str],
    version: str,
    conxa_api_url: str = "",
) -> None:
    """Write the skill-packs/{company}/ layout alongside the legacy build output.

    This format is consumed by runtime.exe (the new installer-distributed MCP server).
    The legacy skills/ layout is kept untouched for backward compatibility.
    """
    from app.config import settings

    company      = bundle_slug
    api_base     = (conxa_api_url or os.environ.get("CONXA_API_URL", "https://api.conxa.io")).rstrip("/")
    tracking_base = os.environ.get("CONXA_TRACKING_API_URL", api_base).rstrip("/")
    tracking_events_url = os.environ.get("CONXA_TRACKING_EVENTS_URL", "").strip()
    if not tracking_events_url:
        tracking_events_url = f"{tracking_base}/tracking/{company}/events"
    skill_packs  = settings.data_dir / "skill-packs" / company

    skill_packs.mkdir(parents=True, exist_ok=True)

    written_slugs: list[str] = []
    for slug in skill_slugs:
        src_dir  = bundle_root / "skills" / slug
        dest_dir = skill_packs / slug
        if not src_dir.is_dir():
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy execution.json, recovery.json and visuals unchanged
        for fname in ("execution.json", "recovery.json"):
            src = src_dir / fname
            if src.is_file():
                shutil.copy2(src, dest_dir / fname)

        if (src_dir / "visuals").is_dir():
            dest_visuals = dest_dir / "visuals"
            if dest_visuals.exists():
                shutil.rmtree(dest_visuals)
            shutil.copytree(src_dir / "visuals", dest_visuals)

        # inputs.json (rename from input.json)
        input_src = src_dir / "input.json"
        if input_src.is_file():
            shutil.copy2(input_src, dest_dir / "inputs.json")

        # Compute checksums over the files we wrote
        checksums: dict[str, str] = {}
        for fname in ("execution.json", "recovery.json", "inputs.json"):
            p = dest_dir / fname
            if p.is_file():
                checksums[fname] = _sha256_file(p)

        # Read name/description from input.json or SKILL.md fallback
        skill_name = slug.replace("_", " ").title()
        description = ""
        inputs_p = dest_dir / "inputs.json"
        if inputs_p.is_file():
            try:
                idata = json.loads(inputs_p.read_text(encoding="utf-8"))
                description = idata.get("description", "")
            except Exception:
                pass
        if not description:
            md_p = src_dir / "SKILL.md"
            if md_p.is_file():
                first = next((l.lstrip("# ").strip() for l in md_p.read_text(encoding="utf-8").splitlines() if l.strip()), "")
                description = first

        inputs_required: list[str] = []
        if inputs_p.is_file():
            try:
                idata = json.loads(inputs_p.read_text(encoding="utf-8"))
                if "required" in idata:
                    inputs_required = list(idata["required"])
                elif "inputs" in idata and isinstance(idata["inputs"], list):
                    inputs_required = [i["name"] for i in idata["inputs"] if isinstance(i, dict) and "name" in i]
            except Exception:
                pass

        manifest = {
            "slug":             slug,
            "name":             skill_name,
            "description":      description,
            "version":          version,
            "required_runtime": ">=1.0.0",
            "company":          company,
            "target_url":       target_url,
            "inputs_required":  inputs_required,
            "checksum":         checksums,
        }
        (dest_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written_slugs.append(slug)

    # pack.json at company root
    pack = {
        "company":            company,
        "company_display":    plugin_name,
        "skill_pack_version": version,
        "required_runtime":   ">=1.0.0",
        "target_url":         target_url,
        "protected_url":      protected_url,
        "skills":             written_slugs,
        "sync_endpoint":      f"{api_base}/skill-packs/{company}/delta",
        "built_at":           datetime.now(timezone.utc).isoformat(),
    }

    # Tracking config: embed in pack.json so the runtime knows where to send events
    import hmac as _hmac_mod
    import hashlib as _hash_mod

    _tracking_secret = os.environ.get("SKILL_TRACKING_HMAC_SECRET", "")
    _tracking_token  = ""
    if _tracking_secret:
        _raw = f"{company}:{version}".encode()
        _tracking_token = _hmac_mod.new(_tracking_secret.encode(), _raw, _hash_mod.sha256).hexdigest()
        from app.db import db_set
        db_set("tracking_tokens", company, {"token": _tracking_token, "version": version})

    # In local dev (no secret, no explicit URL overrides), point to the local API server
    # so the dashboard at localhost receives run data immediately.
    _explicit_url  = os.environ.get("CONXA_TRACKING_EVENTS_URL", "").strip()
    _explicit_base = os.environ.get("CONXA_API_URL", "").strip()
    if not _tracking_secret and not _explicit_url and not _explicit_base:
        tracking_events_url = f"http://127.0.0.1:{settings.port}/api/tracking/{company}/events"

    pack["tracking"] = {
        "enabled":          True,
        "tracking_url":     tracking_events_url,
        "tracking_token":   _tracking_token,
        "company_id":       company,
        "schema_version":   1,
        "protocol_version": 1,
    }

    (skill_packs / "pack.json").write_text(
        json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ─────────────────────────────────────────────────
# Plugin output directory helpers
# ─────────────────────────────────────────────────

def _plugin_bundle_slug(plugin_id: str, plugin_name: str) -> str:
    return _to_bundle_slug(plugin_name)


def _bundle_root(bundle_slug: str) -> Path:
    from app.storage.skill_packages import bundle_root_dir, ensure_bundle_scaffold
    root = bundle_root_dir(bundle_slug)
    if root is None:
        root = ensure_bundle_scaffold(bundle_slug)
    return root


# ─────────────────────────────────────────────────
# Template helpers
# ─────────────────────────────────────────────────

def _templates_dir() -> Path:
    return Path(__file__).parent.parent / "storage" / "plugin_templates"


def _render_plugin_template(name: str, **subs: str) -> str:
    tmpl = (_templates_dir() / "plugin" / name).read_text(encoding="utf-8")
    for k, v in subs.items():
        tmpl = tmpl.replace("{{" + k + "}}", v)
    return tmpl


def _copy_plugin_templates(
    bundle_root: Path,
    *,
    plugin_name: str,
    plugin_slug: str,
    target_url: str,
    version: str,
    skill_slugs: list[str],
    package_id: str | None = None,
) -> None:
    """Copy plugin-side templates into bundle_root with substitutions."""
    templates = _templates_dir()

    # .gitignore
    tmpl_gi = templates / "plugin" / ".gitignore"
    if tmpl_gi.exists():
        (bundle_root / ".gitignore").write_text(tmpl_gi.read_text(encoding="utf-8"), encoding="utf-8")

    install_id = package_id or plugin_slug

    # Claude.md (from template)
    skills_list = "\n".join(f"- `{s}`" for s in skill_slugs)
    (bundle_root / "Claude.md").write_text(
        _render_plugin_template(
            "Claude.md.tmpl",
            plugin_name=plugin_name,
            slug=plugin_slug,
            plugin_id=install_id,
            target_url=target_url,
            skills_list=skills_list,
        ),
        encoding="utf-8",
    )

    # index.md (from template)
    skills_catalog = "\n".join(f"- `{s}` — see `skills/{s}/SKILL.md`" for s in skill_slugs)
    (bundle_root / "index.md").write_text(
        _render_plugin_template(
            "index.md.tmpl",
            plugin_name=plugin_name,
            slug=plugin_slug,
            target_url=target_url,
            skills_catalog=skills_catalog,
        ),
        encoding="utf-8",
    )

    # Build output stays data-only. Runtime installation is handled by the
    # Windows installer flow, not by an npm CLI package.




def _clean_stale_artifacts(bundle_root: Path) -> None:
    """Remove files from old build architectures before rebuilding."""
    stale_files = [
        "server.js", "run.js", "browser.js", "config.js", "runtime.js",
        "package.json", "package-lock.json", ".mcp.json",
        "plugin.config.json",  # renamed to plugin.json
        "schema.json",         # removed from build output
        "auth/credentials.example.json",
        "auth/credentials.json",
    ]
    stale_dirs = [
        "execution", "node_modules", "auth/login",
        "runtime", "runtime/node_modules",
        ".claude-plugin",  # old marketplace shim, removed in shared-runtime migration
    ]
    for name in stale_files:
        p = bundle_root / name
        if p.exists():
            p.unlink()
    for name in stale_dirs:
        p = bundle_root / name
        if p.is_dir():
            shutil.rmtree(p)
    # Remove hash-suffixed per-plugin registry json files (e.g. render_c759c810.json)
    for p in bundle_root.glob("*_*.json"):
        p.unlink()


# ─────────────────────────────────────────────────
# Data-only package file generators (kept for README/LICENSE)
# ─────────────────────────────────────────────────


def _render_readme(
    plugin_name: str,
    plugin_slug: str,
    target_url: str,
    skill_slugs: list[str],
    package_id: str | None = None,
) -> str:
    skills_md = "\n".join(f"- `{s}` — see `skills/{s}/SKILL.md`" for s in skill_slugs)
    install_id = package_id or plugin_slug
    return f"""\
# {plugin_name}

Automate [{target_url}]({target_url}) with Claude using this Conxa skill pack.

Package ID: `{install_id}`

## Install

This is a data-only skill pack. Use Conxa's Build Installer page to create the
Windows setup file that installs the runtime, registers Claude, and copies these
skills onto the user's machine.

## Available Skills

{skills_md}

## How It Works

This skill pack works with the installed `conxa` MCP runtime. When Claude calls
a skill, a real Chromium browser opens on your machine, executes the recorded
workflow, and returns a result and screenshot. Your auth session stays on your
machine and is never uploaded anywhere.

---
*Generated by [Conxa](https://conxa.in)*
"""


def _render_license() -> str:
    year = datetime.now(timezone.utc).year
    return f"""\
MIT License

Copyright (c) {year} Conxa

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


# ─────────────────────────────────────────────────
# Main build entry point
# ─────────────────────────────────────────────────

def build_plugin(
    plugin_id: str,
    *,
    version: str = "0.1.0",
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Compile a plugin from its recorded sessions into an installer-ready package."""
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"Plugin {plugin_id!r} not found.")
    if not plugin.workflows:
        raise ValueError("Plugin has no workflows. Record at least one workflow.")
    uncompiled = [wf.name for wf in plugin.workflows if not wf.skill_id]
    if uncompiled:
        raise ValueError(f"Compile these workflows before building: {', '.join(uncompiled)}")
    unedited = [wf.name for wf in plugin.workflows if not wf.edited_at]
    if unedited:
        raise ValueError(
            f"Open the editor and sign off on these workflows before building: {', '.join(unedited)}"
        )

    def _log(msg: str, **extra: Any) -> None:
        entry = {"kind": "plugin_build", "message": msg, "plugin_id": plugin_id, **extra}
        if realtime_sink:
            realtime_sink(entry)

    bundle_slug = _plugin_bundle_slug(plugin_id, plugin.name)
    _log("Starting plugin build", bundle_slug=bundle_slug, version=version)

    bundle_root = _bundle_root(bundle_slug)

    # ── 0. Clean stale artifacts from old build architectures ─────────────
    _clean_stale_artifacts(bundle_root)
    _log("Cleaned stale artifacts")

    # ── 1. Build workflow skills ───────────────────────────────────────────
    skill_slugs: list[str] = []
    for wf in plugin.workflows:
        saved_skill = read_skill(wf.skill_id) if wf.skill_id else None
        if saved_skill is not None:
            _log("Building workflow from saved skill JSON", workflow=wf.name, workflow_id=wf.id)
            _build_workflow_from_saved_skill(
                bundle_root=bundle_root,
                workflow_slug=wf.slug,
                saved_skill=saved_skill,
            )
            skill_slugs.append(wf.slug)
            _log(f"Workflow {wf.name!r} compiled from saved skill JSON")
            continue

        _log(f"Skipping workflow {wf.name!r} — no compiled skill found", warning=True)

    # ── 2. Write plugin.json (v2 manifest for the installed Conxa runtime) ──
    var_pattern = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}")
    protected_url_vars = var_pattern.findall(plugin.protected_url)

    package_id = getattr(plugin, "package_id", None) or bundle_slug
    visibility = getattr(plugin, "visibility", "private")
    tags = list(getattr(plugin, "tags", []) or [])
    repository_url = getattr(plugin, "repository_url", None)

    plugin_config = {
        "package_format": 2,
        "id": package_id,
        "slug": bundle_slug,
        "name": plugin.name,
        "version": version,
        "visibility": visibility,
        "tags": tags,
        "target_url": plugin.target_url,
        "protected_url": plugin.protected_url,
        "protected_url_vars": protected_url_vars,
        "auth_requirements": {"kind": "cookie", "manual_login": True},
        "skills": [{"slug": s, "path": f"skills/{s}"} for s in skill_slugs],
        "runtime_min_version": "1.0.0",
        "compatibility": {"conxa_runtime": ">=1.0.0"},
    }
    if repository_url:
        plugin_config["source"] = {"kind": "git+https", "repository_url": repository_url}
    (bundle_root / "plugin.json").write_text(
        json.dumps(plugin_config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _log("Written plugin.json", skills=skill_slugs, package_id=package_id, visibility=visibility)

    # ── 3. Copy plugin templates (Claude.md, index.md, .gitignore) ─────────
    _copy_plugin_templates(
        bundle_root,
        plugin_name=plugin.name,
        plugin_slug=bundle_slug,
        target_url=plugin.target_url,
        version=version,
        skill_slugs=skill_slugs,
        package_id=package_id,
    )
    _log("Copied plugin templates")

    # ── 4. Write README.md and LICENSE ────────────────────────────────────
    (bundle_root / "README.md").write_text(
        _render_readme(plugin.name, bundle_slug, plugin.target_url, skill_slugs, package_id=package_id),
        encoding="utf-8",
    )
    _log("Written README.md")

    license_path = bundle_root / "LICENSE"
    if not license_path.exists():
        license_path.write_text(_render_license(), encoding="utf-8")
        _log("Written LICENSE")

    # ── 5. Write skill-packs/{company}/ format (for installer runtime) ────────
    try:
        _write_skill_packs_format(
            bundle_root=bundle_root,
            bundle_slug=bundle_slug,
            plugin_name=plugin.name,
            target_url=plugin.target_url,
            protected_url=plugin.protected_url,
            skill_slugs=skill_slugs,
            version=version,
        )
        _log("Written skill-packs format", company=bundle_slug, skills=skill_slugs)
    except Exception as exc:
        _log(f"Warning: skill-packs format write failed — {exc}", warning=True)

    # ── 6. Persist build record ────────────────────────────────────────────
    set_build(plugin_id, output_path=str(bundle_root), version=version)

    return {
        "plugin_id": plugin_id,
        "bundle_slug": bundle_slug,
        "output_path": str(bundle_root),
        "version": version,
        "skills": skill_slugs,
    }


def zip_plugin(plugin_id: str) -> tuple[str, bytes]:
    """Return (filename, zip_bytes) for the compiled plugin folder."""
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"Plugin {plugin_id!r} not found.")
    if plugin.build is None:
        raise ValueError("Plugin has not been built yet.")

    bundle_root = Path(plugin.build.output_path)
    if not bundle_root.is_dir():
        raise ValueError(f"Built plugin folder not found: {bundle_root}")

    buf = BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
        for file_path in sorted(bundle_root.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(bundle_root)
            # auth/* credentials are local runtime state — never include in the zip
            if rel.parts and rel.parts[0] == "auth" and (
                rel.name == "auth.json" or rel.name.startswith("credentials")
            ):
                continue
            arcname = file_path.relative_to(bundle_root.parent).as_posix()
            zf.write(file_path, arcname)

    filename = f"{bundle_root.name}.zip"
    return filename, buf.getvalue()
