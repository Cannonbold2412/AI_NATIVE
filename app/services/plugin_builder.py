"""Plugin-first build pipeline.

Compiles a Plugin entity (auth session + N workflow sessions) into a
GitHub-ready plugin folder:

  output/skill_package/{bundle_slug}-plugin/
    .claude-plugin/
      plugin.json                  <- Claude Code plugin manifest
      marketplace.json             <- Claude Code marketplace catalog
    .mcp.json                      <- auto-start MCP server for Claude Code
    plugin.config.json            <- versioned manifest (replaces plugin.json)
    README.md                     <- auto-generated, public-facing
    CLAUDE.md                     <- Claude reads this for skill discovery
    .gitignore                    <- excludes auth/auth.json and local state
    LICENSE                       <- MIT by default
    package.json                  <- top-level npm manifest for post-clone install
    auth/
      credentials.example.json   <- template only, safe to commit
      login/                      <- compiled auth skill
    skills/
      {workflow_slug}/            <- one per workflow, login steps stripped
    execution/
      executor.js, recovery.js, tracker.js, validator.js, session_manager.js

auth/auth.json is NEVER placed in the build output — it is a credential
captured locally at runtime (via `conxa auth <plugin>`) and is gitignored.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from zipfile import ZIP_DEFLATED, ZipFile

from app.compiler.action_policy import RECOVERY_ACTION_TYPES
from app.editor.assets import resolve_skill_asset
from app.llm.anchor_vision_llm import _apply_bbox_highlight
from app.storage.plugin_store import get_plugin, set_build
from app.storage.json_store import read_skill
from app.storage.session_events import read_session_events

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
_TEXT_SELECTOR_RE = re.compile(r"^text=(?P<quote>['\"]?)(?P<text>.+?)(?P=quote)$")


def _to_bundle_slug(text: str) -> str:
    slug = _SLUG_RE.sub("_", text.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"p_{slug}"
    return slug[:40]


def _to_claude_plugin_name(text: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not name or not name[0].isalpha():
        name = f"p-{name}"
    return name[:64]


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


def _copy_url_state(step: dict[str, Any], out: dict[str, Any]) -> None:
    url_state = step.get("url_state")
    if not isinstance(url_state, dict) or not url_state:
        return

    sanitized: dict[str, Any] = {}
    for phase in ("before", "after"):
        phase_state = url_state.get(phase)
        if not isinstance(phase_state, dict):
            continue
        pattern = str(phase_state.get("url_pattern") or "").strip()
        if pattern:
            sanitized[phase] = {"url_pattern": pattern}

    if sanitized:
        out["url_state"] = sanitized


def _saved_step_to_execution_step(step: dict[str, Any]) -> dict[str, Any] | None:
    action = _step_action_name(step)
    if action == "input":
        action = "type"

    if action == "navigate":
        url = _step_url(step)
        if not url:
            return None
        out: dict[str, Any] = {"type": "navigate", "url": url}
        _copy_url_state(step, out)
        return out

    if action in {"click", "focus"}:
        selector = _step_selector(step)
        if not selector:
            return None
        out = {"type": action, "selector": selector}
        _copy_url_state(step, out)
        return out

    if action in {"type", "fill"}:
        selector = _step_selector(step)
        if not selector:
            return None
        value = step.get("value")
        if value is None:
            value = ""
        out = {"type": action, "selector": selector, "value": str(value)}
        _copy_url_state(step, out)
        return out

    if action == "select":
        selector = _step_selector(step)
        if not selector:
            return None
        out = {"type": "select", "selector": selector}
        if step.get("value") is not None:
            out["value"] = str(step.get("value"))
        _copy_url_state(step, out)
        return out

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
        _copy_url_state(step, out)
        return out

    if action == "check":
        kind = str(step.get("check_kind") or "url").strip().lower().replace("-", "_")
        out = {"type": "check", "kind": "url_exact" if kind in {"url_must_be", "exact_url"} else kind}
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
        _copy_url_state(step, out)
        return out

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
    execution_steps: list[dict[str, Any]] = []
    source_steps: list[dict[str, Any]] = []
    step_ids: list[int] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        converted = _saved_step_to_execution_step(raw)
        if converted is None:
            continue
        execution_steps.append(converted)
        source_steps.append(raw)
        step_ids.append(len(execution_steps))
    execution_steps = _repair_parameterized_search_result_selectors(execution_steps)
    if not execution_steps:
        raise ValueError(f"Saved skill {meta.get('id') or workflow_slug!r} has no executable steps.")

    inputs = _normalize_saved_skill_inputs(list(saved_skill.get("inputs") or []))
    skill_dir = bundle_root / "skills" / workflow_slug
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    skill_dir.mkdir(parents=True, exist_ok=True)
    source_session_id = str(meta.get("source_session_id") or "").strip()
    visuals_dir = _write_saved_visual_assets(
        source_steps=source_steps,
        skill_dir=skill_dir,
        source_session_id=source_session_id,
    )
    recovery = _build_saved_skill_recovery(source_steps, step_ids, visuals_dir)
    (skill_dir / "execution.json").write_text(json.dumps(execution_steps, indent=2, ensure_ascii=False), encoding="utf-8")
    (skill_dir / "recovery.json").write_text(json.dumps(recovery, indent=2, ensure_ascii=False), encoding="utf-8")
    (skill_dir / "input.json").write_text(json.dumps({"inputs": inputs}, indent=2, ensure_ascii=False), encoding="utf-8")
    (skill_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": workflow_slug,
                "description": f"Run the {title} workflow.",
                "version": "1.0.0",
                "entry": {
                    "execution": "./execution.json",
                    "recovery": "./recovery.json",
                    "input": "./input.json",
                },
                "inputs": [{"name": item["name"], "type": item["type"]} for item in inputs],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(_render_saved_skill_markdown(title, inputs, execution_steps), encoding="utf-8")


# ─────────────────────────────────────────────────
# Plugin output directory helpers
# ─────────────────────────────────────────────────

def _plugin_bundle_slug(plugin_id: str, plugin_name: str) -> str:
    base = _to_bundle_slug(plugin_name)
    return f"{base}_{plugin_id[:8]}"


def _bundle_root(bundle_slug: str) -> Path:
    from app.storage.skill_packages import bundle_root_dir, ensure_bundle_scaffold
    root = bundle_root_dir(bundle_slug)
    if root is None:
        root = ensure_bundle_scaffold(bundle_slug)
    return root


# ─────────────────────────────────────────────────
# session_manager.js — generated per plugin with
# protected_url and marker_text injected as constants
# ─────────────────────────────────────────────────

_MCP_SERVER_TEMPLATE = '''\
#!/usr/bin/env node
"use strict";
/**
 * server.js — MCP server for {plugin_name}.
 *
 * Install via Claude Code: Settings → MCP Servers → Add from GitHub
 * Then ask Claude: "call bootstrap_auth to set up your session"
 */
const {{ Server }} = require("@modelcontextprotocol/sdk/server/index.js");
const {{ StdioServerTransport }} = require("@modelcontextprotocol/sdk/server/stdio.js");
const {{ CallToolRequestSchema, ListToolsRequestSchema }} = require("@modelcontextprotocol/sdk/types.js");
const {{ chromium }} = require("playwright");
const fs = require("fs");
const path = require("path");

const PLUGIN_DIR    = path.dirname(require.main.filename);
const CONFIG        = JSON.parse(fs.readFileSync(path.join(PLUGIN_DIR, "plugin.config.json"), "utf8"));
const AUTH_JSON     = path.join(PLUGIN_DIR, "auth", "auth.json");
const LOGIN_DIR     = path.join(PLUGIN_DIR, "auth", "login");
const PROTECTED_URL = {protected_url};
const MARKER_TEXT   = {marker_text};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function interpolate(value, inputs) {{
  if (typeof value !== "string") return value;
  return value.replace(/\\{{\\{{\\s*([^{{}}]+?)\\s*\\}}\\}}/g, (_, k) => String(inputs[k] ?? ""));
}}

async function tryLocator(page, sel, timeout) {{
  try {{ await page.locator(sel).waitFor({{ state: "visible", timeout: timeout || 4000 }}); return true; }}
  catch (_) {{ return false; }}
}}

const URL_STATE_WAIT_MS = 2000;
const URL_STATE_POLL_MS = 100;

async function waitForUrlState(page, urlState) {{
  if (!urlState || !urlState.url_pattern) return;
  const pattern = new RegExp(urlState.url_pattern);
  const deadline = Date.now() + URL_STATE_WAIT_MS;
  let currentUrl = page.url();

  while (Date.now() <= deadline) {{
    currentUrl = page.url();
    if (pattern.test(currentUrl)) return;
    await page.waitForTimeout(Math.min(URL_STATE_POLL_MS, Math.max(0, deadline - Date.now())));
  }}

  throw new Error(`URL ${{currentUrl}} does not match expected pattern ${{urlState.url_pattern}}`);
}}

// ─── Step executor ────────────────────────────────────────────────────────────

async function executeStep(page, step, inputs) {{
  const type  = step.type;
  const raw   = step.selector || step.css_selector || (step.target && step.target.css) || "";
  const sel   = interpolate(raw, inputs);

  if (type === "wait") {{ await page.waitForTimeout(Number(step.ms) || 1000); return; }}
  if (type === "navigate") {{
    await page.goto(interpolate(step.url || "", inputs), {{ timeout: 30000, waitUntil: "domcontentloaded" }});
    return;
  }}
  if (type === "scroll") {{
    if (sel) {{ await page.locator(sel).first().scrollIntoViewIfNeeded({{ timeout: 5000 }}).catch(() => {{}}); }}
    else      {{ await page.evaluate(`window.scrollBy(${{Number(step.delta_x)||0}}, ${{Number(step.delta_y)||0}})`); }}
    return;
  }}
  if (type === "fill" || type === "type") {{
    await page.locator(sel).first().fill(interpolate(step.value || "", inputs), {{ timeout: 15000 }});
    return;
  }}
  if (type === "click") {{
    try {{ await page.locator(sel).first().click({{ timeout: 15000 }}); return; }}
    catch (err) {{
      if (String(err).includes("intercepts pointer events")) {{
        try {{ await page.locator(sel).last().click({{ timeout: 10000 }}); return; }} catch (_) {{}}
      }}
      throw err;
    }}
  }}
  if (type === "select") {{
    await page.locator(sel).first().selectOption(interpolate(step.value || "", inputs), {{ timeout: 15000 }});
    return;
  }}
  if (type === "check") {{
    const pattern = interpolate(step.pattern || step.check_pattern || "", inputs);
    if (pattern && !new RegExp(pattern).test(page.url()))
      throw new Error(`URL check failed: ${{page.url()}} does not match ${{pattern}}`);
    return;
  }}
  // Unknown type — skip
}}

async function runSkill(page, skillDir, inputs) {{
  const execPath = path.join(skillDir, "execution.json");
  if (!fs.existsSync(execPath)) throw new Error(`execution.json not found in ${{skillDir}}`);
  const exec  = JSON.parse(fs.readFileSync(execPath, "utf8"));
  const steps = Array.isArray(exec) ? exec
              : Array.isArray(exec.steps) ? exec.steps
              : Array.isArray(exec.execution_plan) ? exec.execution_plan : [];

  const recoveryPath = path.join(skillDir, "recovery.json");
  const recovery = fs.existsSync(recoveryPath)
    ? JSON.parse(fs.readFileSync(recoveryPath, "utf8"))
    : {{ steps: [] }};

  for (let i = 0; i < steps.length; i++) {{
    const step = steps[i];
    try {{
      if (step.url_state && step.url_state.before && step.url_state.before.url_pattern) {{
        await waitForUrlState(page, step.url_state.before);
      }}
      await executeStep(page, step, inputs);
      if (step.url_state && step.url_state.after && step.url_state.after.url_pattern) {{
        await waitForUrlState(page, step.url_state.after);
      }}
    }} catch (err) {{
      if (String(err.message || err).includes("expected pattern")) {{
        throw new Error(`Step ${{step.id || i}} (${{step.type}}) failed: ${{err.message}}`);
      }}
      // Attempt fallback selectors from recovery.json
      const stepNumber = i + 1;
      const rec = (recovery.steps || []).find(r =>
        (step.id && r.id === step.id) || Number(r.step_id) === stepNumber
      );
      let recovered = false;
      if (rec) {{
        const selectorContext = rec.selector_context && typeof rec.selector_context === "object" ? rec.selector_context : {{}};
        const fallback = rec.fallback && typeof rec.fallback === "object" ? rec.fallback : {{}};
        const anchors = Array.isArray(rec.anchors) ? rec.anchors : [];
        const candidates = Array.from(new Set([
          ...(Array.isArray(rec.fallback_selectors) ? rec.fallback_selectors : []),
          ...(Array.isArray(rec.candidates) ? rec.candidates : []),
          ...(typeof selectorContext.primary === "string" ? [selectorContext.primary] : []),
          ...(Array.isArray(selectorContext.alternatives) ? selectorContext.alternatives : []),
          ...(Array.isArray(fallback.text_variants) ? fallback.text_variants.map(t => `text=${{JSON.stringify(String(t).trim())}}`) : []),
          ...anchors
            .filter(a => a && typeof a.text === "string" && a.text.trim())
            .map(a => `text=${{JSON.stringify(a.text.trim())}}`),
        ].filter(Boolean)));
        for (const cand of candidates) {{
          if (await tryLocator(page, cand, 3000)) {{
            try {{
              await executeStep(page, {{ ...step, selector: cand }}, inputs);
              if (step.url_state && step.url_state.after && step.url_state.after.url_pattern) {{
                await waitForUrlState(page, step.url_state.after);
              }}
              recovered = true;
              break;
            }}
            catch (_) {{}}
          }}
        }}
      }}
      if (!recovered) throw new Error(`Step ${{step.id || i}} (${{step.type}}) failed: ${{err.message}}`);
    }}
  }}
}}

async function runPlan(page, steps, inputs) {{
  for (let i = 0; i < steps.length; i++) {{
    const step = steps[i];
    try {{
      if (step.url_state && step.url_state.before && step.url_state.before.url_pattern) {{
        await waitForUrlState(page, step.url_state.before);
      }}
      await executeStep(page, step, inputs);
      if (step.url_state && step.url_state.after && step.url_state.after.url_pattern) {{
        await waitForUrlState(page, step.url_state.after);
      }}
    }} catch (err) {{
      // Layer 1: step-embedded alternative selectors
      const candidates = Array.from(new Set([
        ...(Array.isArray(step.fallback_selectors) ? step.fallback_selectors : []),
        ...(Array.isArray(step.candidates) ? step.candidates : []),
        ...(Array.isArray(step.anchors) ? step.anchors.filter(a => a && typeof a.text === "string").map(a => `text=${{JSON.stringify(a.text.trim())}}`) : []),
        ...(Array.isArray(step.fallback_text_variants) ? step.fallback_text_variants.map(t => `text=${{JSON.stringify(String(t).trim())}}`) : []),
      ].filter(Boolean)));

      let recovered = false;
      // Layer 2: try each candidate selector
      for (const cand of candidates) {{
        if (await tryLocator(page, cand, 3000)) {{
          try {{
            await executeStep(page, {{ ...step, selector: cand }}, inputs);
            if (step.url_state && step.url_state.after && step.url_state.after.url_pattern) {{
              await waitForUrlState(page, step.url_state.after);
            }}
            recovered = true;
            break;
          }} catch (_) {{}}
        }}
      }}
      // Layer 3: derive text selector from step value or label
      if (!recovered) {{
        const textHints = [step.value, step.label, step.aria_label].filter(v => v && typeof v === "string" && v.length < 60);
        for (const hint of textHints) {{
          const textSel = `text=${{JSON.stringify(hint.trim())}}`;
          if (await tryLocator(page, textSel, 3000)) {{
            try {{
              await executeStep(page, {{ ...step, selector: textSel }}, inputs);
              recovered = true;
              break;
            }} catch (_) {{}}
          }}
        }}
      }}
      if (!recovered) throw new Error(`Step ${{i}} (${{step.type}}) failed: ${{err.message}}`);
    }}
  }}
}}

// ─── Session management ───────────────────────────────────────────────────────

async function isAuthenticated(page) {{
  const url = page.url();
  try {{
    if (new URL(url).hostname !== new URL(PROTECTED_URL).hostname) return false;
  }} catch (_) {{ return false; }}
  if (MARKER_TEXT) {{
    const text = await page.textContent("body").catch(() => "");
    if (!text.includes(MARKER_TEXT)) return false;
  }}
  return true;
}}

async function getAuthContext(headless) {{
  const browser = await chromium.launch({{ headless: headless !== false }});
  const opts = {{}};
  if (fs.existsSync(AUTH_JSON)) {{
    try {{ opts.storageState = JSON.parse(fs.readFileSync(AUTH_JSON, "utf8")); }} catch (_) {{}}
  }}
  const context = await browser.newContext(opts);
  const page    = await context.newPage();

  await page.goto(PROTECTED_URL, {{ waitUntil: "domcontentloaded", timeout: 30000 }}).catch(() => {{}});
  await page.waitForTimeout(600);

  if (!(await isAuthenticated(page))) {{
    if (!fs.existsSync(LOGIN_DIR))
      throw new Error("Session expired. Ask Claude to call bootstrap_auth first.");
    await runSkill(page, LOGIN_DIR, {{}});
    const state = await context.storageState();
    fs.mkdirSync(path.dirname(AUTH_JSON), {{ recursive: true }});
    fs.writeFileSync(AUTH_JSON, JSON.stringify(state, null, 2));
    await page.goto(PROTECTED_URL, {{ waitUntil: "domcontentloaded", timeout: 30000 }}).catch(() => {{}});
    if (!(await isAuthenticated(page))) throw new Error("Auth failed. Call bootstrap_auth again.");
  }}

  await page.close();
  return {{ browser, context }};
}}

// ─── MCP server ───────────────────────────────────────────────────────────────

const server = new Server(
  {{ name: CONFIG.id, version: CONFIG.version }},
  {{ capabilities: {{ tools: {{}} }} }},
);

server.setRequestHandler(ListToolsRequestSchema, async () => {{
  const tools = [
    {{
      name: "bootstrap_auth",
      description: `Set up your ${{CONFIG.name}} session. Opens a browser — log in, then close the window. Run once before using any skill.`,
      inputSchema: {{ type: "object", properties: {{}}, required: [] }},
    }},
    {{
      name: "list_skills",
      description: "List all available skills with metadata",
      inputSchema: {{ type: "object", properties: {{}}, required: [] }},
    }},
    {{
      name: "read_skill_files",
      description: "Read execution.json and recovery.json for a skill. Returns steps and recovery info for planning.",
      inputSchema: {{ type: "object", properties: {{ slug: {{ type: "string", description: "Skill slug (use underscores or hyphens)" }} }}, required: ["slug"] }},
    }},
    {{
      name: "execute_plan",
      description: "Execute a merged multi-skill plan via Playwright. Accepts steps array (merged from multiple execution.json files). Runs visible browser.",
      inputSchema: {{ type: "object", properties: {{ steps: {{ type: "array", description: "Merged array of execution steps from one or more skills" }}, inputs: {{ type: "object", description: "Input values to substitute into step placeholders" }} }}, required: ["steps"] }},
    }},
  ];

  for (const skill of (CONFIG.skills || [])) {{
    let description = `Execute ${{skill.slug}} on ${{CONFIG.target_url}}`;
    let inputSchema = {{ type: "object", properties: {{}}, required: [] }};
    const mPath = path.join(PLUGIN_DIR, skill.path, "manifest.json");
    const iPath = path.join(PLUGIN_DIR, skill.path, "input.json");
    if (fs.existsSync(mPath)) {{
      try {{ const m = JSON.parse(fs.readFileSync(mPath, "utf8")); description = m.description || m.intent || description; }}
      catch (_) {{}}
    }}
    if (fs.existsSync(iPath)) {{
      try {{
        const loaded = JSON.parse(fs.readFileSync(iPath, "utf8"));
        inputSchema = {{ type: "object", ...loaded }};
      }} catch (_) {{}}
    }}
    tools.push({{ name: skill.slug.replace(/-/g, "_"), description, inputSchema }});
  }}
  console.error(`[ListTools] Registering ${{tools.length}} tools: ${{tools.map(t => t.name).join(", ")}}`);
  return {{ tools }};
}});

server.setRequestHandler(CallToolRequestSchema, async (request) => {{
  const {{ name, arguments: args }} = request.params;

  if (name === "bootstrap_auth") {{
    const browser = await chromium.launch({{ headless: false }});
    const context = await browser.newContext();
    const page    = await context.newPage();
    await page.goto(CONFIG.target_url, {{ waitUntil: "domcontentloaded", timeout: 30000 }});
    // Wait until user navigates to the protected area (up to 5 min)
    try {{
      const protectedHostPath = new URL(PROTECTED_URL).pathname.replace(/\\/$/, "");
      await page.waitForURL(u => u.pathname.startsWith(protectedHostPath) || u.href.includes(PROTECTED_URL), {{ timeout: 300000 }});
    }} catch (_) {{}}
    const state = await context.storageState();
    fs.mkdirSync(path.dirname(AUTH_JSON), {{ recursive: true }});
    fs.writeFileSync(AUTH_JSON, JSON.stringify(state, null, 2));
    await browser.close();
    return {{ content: [{{ type: "text", text: `Session saved. You can now use ${{CONFIG.name}} skills.` }}] }};
  }}

  // ── list_skills ───────────────────────────────────────────────────────────
  if (name === "list_skills") {{
    const skills = CONFIG.skills || [];
    console.error(`[list_skills] Returning ${{skills.length}} skills: ${{skills.map(s => s.slug).join(", ")}}`);
    return {{ content: [{{ type: "text", text: JSON.stringify(skills, null, 2) }}] }};
  }}

  // ── read_skill_files ─────────────────────────────────────────────────────
  if (name === "read_skill_files") {{
    const slugArg = (args && args.slug) ? String(args.slug) : "";
    console.error(`[read_skill_files] Looking for skill: ${{slugArg}}`);
    const skill = (CONFIG.skills || []).find(s => s.slug === slugArg || s.slug === slugArg.replace(/_/g, "-") || s.slug === slugArg.replace(/-/g, "_"));
    if (!skill) {{
      console.error(`[read_skill_files] Skill not found. Available: ${{(CONFIG.skills || []).map(s => s.slug).join(", ")}}`);
      return {{ content: [{{ type: "text", text: `Skill not found: ${{slugArg}}. Use list_skills to see available skills.` }}] }};
    }}
    const skillDir = path.join(PLUGIN_DIR, skill.path);
    const execPath = path.join(skillDir, "execution.json");
    const recPath  = path.join(skillDir, "recovery.json");
    const result = {{
      slug: skill.slug,
      path: skill.path,
      execution: fs.existsSync(execPath) ? JSON.parse(fs.readFileSync(execPath, "utf8")) : null,
      recovery:  fs.existsSync(recPath)  ? JSON.parse(fs.readFileSync(recPath,  "utf8")) : null,
    }};
    console.error(`[read_skill_files] Found ${{skill.slug}}: ${{result.execution ? result.execution.length + " steps" : "no execution.json"}}`);
    return {{ content: [{{ type: "text", text: JSON.stringify(result, null, 2) }}] }};
  }}

  // ── execute_plan ─────────────────────────────────────────────────────────
  if (name === "execute_plan") {{
    const steps  = (args && Array.isArray(args.steps))  ? args.steps  : [];
    const inputs = (args && typeof args.inputs === "object" && args.inputs) ? args.inputs : {{}};
    console.error(`[execute_plan] Starting with ${{steps.length}} steps, inputs: ${{JSON.stringify(inputs)}}`);
    if (steps.length === 0) return {{ content: [{{ type: "text", text: "execute_plan: no steps provided." }}] }};

    let _browser, _context;
    try {{
      ({{ browser: _browser, context: _context }} = await getAuthContext(false));
      console.error(`[execute_plan] Auth context ready`);
    }} catch (authErr) {{
      console.error(`[execute_plan] Auth failed: ${{authErr}}`);
      return {{ content: [{{ type: "text", text: String(authErr) }}] }};
    }}

    const page = await _context.newPage();
    try {{
      console.error(`[execute_plan] Running ${{steps.length}} steps...`);
      await runPlan(page, steps, inputs);
      const state = await _context.storageState();
      fs.mkdirSync(path.dirname(AUTH_JSON), {{ recursive: true }});
      fs.writeFileSync(AUTH_JSON, JSON.stringify(state, null, 2));
      const shot = await page.screenshot({{ type: "png" }}).catch(() => null);
      const url  = page.url();
      await _browser.close();
      console.error(`[execute_plan] Success! URL: ${{url}}`);
      const content = [{{ type: "text", text: `Plan executed successfully. URL: ${{url}}` }}];
      if (shot) content.push({{ type: "image", data: shot.toString("base64"), mimeType: "image/png" }});
      return {{ content }};
    }} catch (err) {{
      console.error(`[execute_plan] Failed: ${{err.message}}`);
      await _browser.close().catch(() => {{}});
      return {{ content: [{{ type: "text", text: `Plan execution failed at: ${{err.message}}` }}] }};
    }}
  }}

  const skillSlug = name.replace(/_/g, "-");
  const skill = (CONFIG.skills || []).find(s => s.slug === skillSlug);
  if (!skill) throw new Error(`Unknown tool: ${{name}}`);

  let _browser, _context;
  try {{
    ({{ browser: _browser, context: _context }} = await getAuthContext(false));
  }} catch (authErr) {{
    return {{ content: [{{ type: "text", text: String(authErr) }}] }};
  }}

  const page = await _context.newPage();
  try {{
    await runSkill(page, path.join(PLUGIN_DIR, skill.path), args || {{}});
    const state = await _context.storageState();
    fs.mkdirSync(path.dirname(AUTH_JSON), {{ recursive: true }});
    fs.writeFileSync(AUTH_JSON, JSON.stringify(state, null, 2));
    const shot = await page.screenshot({{ type: "png" }}).catch(() => null);
    const url  = page.url();
    await _browser.close();
    const content = [{{ type: "text", text: `${{skill.slug}} completed. URL: ${{url}}` }}];
    if (shot) content.push({{ type: "image", data: shot.toString("base64"), mimeType: "image/png" }});
    return {{ content }};
  }} catch (err) {{
    await _browser.close().catch(() => {{}});
    return {{ content: [{{ type: "text", text: `Skill failed: ${{err}}` }}] }};
  }}
}});

const _skillFlagIdx = process.argv.indexOf("--run-skill");
if (_skillFlagIdx !== -1) {{
  // ── CLI execution mode ────────────────────────────────────────────────────
  const _skillSlug  = process.argv[_skillFlagIdx + 1];
  const _inputsIdx  = process.argv.indexOf("--inputs");
  const _inputs     = _inputsIdx !== -1 ? JSON.parse(process.argv[_inputsIdx + 1]) : {{}};
  const _headless   = process.argv.includes("--headless");

  const _skill = (CONFIG.skills || []).find(s => s.slug === _skillSlug);
  if (!_skill) {{
    process.stdout.write(JSON.stringify({{ status: "failed", error: `Skill not found: ${{_skillSlug}}` }}));
    process.exit(1);
  }}

  getAuthContext(_headless).then(async ({{ browser, context }}) => {{
    const page = await context.newPage();
    try {{
      await runSkill(page, path.join(PLUGIN_DIR, _skill.path), _inputs);
      const url  = page.url();
      const shot = await page.screenshot({{ type: "png" }}).catch(() => null);
      const state = await context.storageState();
      fs.mkdirSync(path.dirname(AUTH_JSON), {{ recursive: true }});
      fs.writeFileSync(AUTH_JSON, JSON.stringify(state, null, 2));
      await browser.close();
      process.stdout.write(JSON.stringify({{
        status: "success",
        url,
        screenshot: shot ? shot.toString("base64") : null,
      }}));
      process.exit(0);
    }} catch (err) {{
      await browser.close().catch(() => {{}});
      process.stdout.write(JSON.stringify({{ status: "failed", error: String(err) }}));
      process.exit(1);
    }}
  }}).catch(err => {{
    process.stdout.write(JSON.stringify({{ status: "failed", error: String(err) }}));
    process.exit(1);
  }});
}} else {{
  // ── MCP server mode (default) ─────────────────────────────────────────────
  const transport = new StdioServerTransport();
  server.connect(transport);
}}
'''


def _render_mcp_server(plugin_name: str, protected_url: str, marker_text: str) -> str:
    """Inject plugin_name, protected_url and marker_text as JS string literals."""
    return _MCP_SERVER_TEMPLATE.format(
        plugin_name=plugin_name,
        protected_url=json.dumps(protected_url),
        marker_text=json.dumps(marker_text),
    )


# ─────────────────────────────────────────────────
# GitHub-ready file generators
# ─────────────────────────────────────────────────

def _render_gitignore() -> str:
    return (
        "# Conxa plugin — these are local-only and must never be committed\n"
        "auth/auth.json\n"
        "node_modules/\n"
        ".venv/\n"
        "execution_log.jsonl\n"
        "data/runs/\n"
        "*.local.json\n"
        ".env\n"
    )


def _render_package_json(name: str, version: str, description: str, node_deps: dict[str, str]) -> str:
    deps = {
        "@modelcontextprotocol/sdk": "^1.0.0",
        "playwright": "^1.45.0",
    }
    deps.update(node_deps)
    manifest = {
        "name": f"conxa-plugin-{_to_bundle_slug(name)}",
        "version": version,
        "description": description,
        "main": "server.js",
        "scripts": {"prestart": "npm install --prefer-offline --silent", "start": "node server.js"},
        "dependencies": deps,
        "engines": {"node": ">=20"},
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False)


def _render_claude_plugin_json(
    plugin_name: str,
    version: str,
    description: str,
    repository_url: str = "",
) -> str:
    manifest: dict[str, Any] = {
        "name": _to_claude_plugin_name(plugin_name),
        "description": description,
        "version": version,
        "author": {"name": "Conxa"},
        "license": "MIT",
    }
    if repository_url:
        manifest["repository"] = repository_url
    return json.dumps(manifest, indent=2, ensure_ascii=False)


def _render_claude_mcp_json(plugin_slug: str) -> str:
    manifest = {
        "mcpServers": {
            plugin_slug: {
                "command": "npm",
                "args": ["--prefix", "${CLAUDE_PLUGIN_ROOT}", "start"],
            }
        }
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False)


def _render_claude_marketplace_json(
    plugin_name: str,
    version: str,
    description: str,
    repository_url: str = "",
) -> str:
    plugin_entry: dict[str, Any] = {
        "name": _to_claude_plugin_name(plugin_name),
        "description": description,
        "version": version,
        "source": "./",
        "category": "productivity",
    }
    if repository_url:
        plugin_entry["repository"] = repository_url

    marketplace = {
        "$schema": "https://json.schemastore.org/claude-code-marketplace.json",
        "name": f"{_to_claude_plugin_name(plugin_name)}-marketplace",
        "version": version,
        "description": f"Claude Code marketplace for {plugin_name}",
        "owner": {"name": "Conxa"},
        "plugins": [plugin_entry],
    }
    return json.dumps(marketplace, indent=2, ensure_ascii=False)


def _render_readme(plugin_name: str, plugin_slug: str, target_url: str, skill_slugs: list[str]) -> str:
    skills_md = "\n".join(f"- `{s}` — see `skills/{s}/SKILL.md`" for s in skill_slugs)
    return f"""\
# {plugin_name}

Automate [{target_url}]({target_url}) with Claude using this Conxa plugin.

## Install

Add to **Claude Code** (Settings → MCP Servers → Add from GitHub):

```
github.com/<your-org>/{plugin_slug}
```

Or add manually to `.claude/settings.json`:

```json
{{
  "mcpServers": {{
    "{plugin_slug}": {{
      "command": "node",
      "args": ["/path/to/{plugin_slug}/server.js"]
    }}
  }}
}}
```

After installing, ask Claude to set up your session:

> "Call bootstrap_auth to set up {plugin_name}"

Claude will open a browser — log in manually, and your session is saved locally.

## Available Skills

{skills_md}

## How It Works

This plugin runs as a local MCP server. When Claude calls a skill tool, Chrome
launches on your machine, executes the recorded workflow, and returns a result
and screenshot. Your auth session (`auth/auth.json`) stays on your machine
and is never uploaded anywhere.

---
*Generated by [Conxa](https://conxa.ai)*
"""


def _render_claude_md(
    plugin_name: str, target_url: str, skill_slugs: list[str]
) -> str:
    skills_list = "\n".join(f"- `{s}`" for s in skill_slugs)
    return f"""\
# {plugin_name} Plugin — Claude Instructions

## ⚠️ CRITICAL EXECUTION RULES

**NEVER use any of these tools:**
- `mcp__Claude_in_Chrome__*` (Chrome MCP browser tools)
- `computer_use` or `computer-use`
- Any built-in browser navigation or screenshot tools

**ALWAYS use this plugin's MCP tools to execute browser automation.**

---

## Available MCP Tools

| Tool | Purpose |
|------|---------|
| `bootstrap_auth` | Open browser for user to log in and save session |
| `list_skills` | List all available skills with metadata |
| `read_skill_files(slug)` | Get execution.json + recovery.json for a skill |
| `execute_plan(steps, inputs)` | Run a merged multi-skill plan via Playwright |
| Individual skill tools | Shortcut to run a single skill directly |

---

## Available Skills

{skills_list}

---

## Execution Flow

When the user asks you to do something on {target_url}:

### Step 1: Identify Skills
Determine which skills are needed from the list above.
Example: "Delete my database" → needs: `bootstrap_auth` (if not authed) + `delete_database`

### Step 2: Load Skill Data
For each required skill, call:
```
read_skill_files(slug: "<skill-slug>")
```
This returns `execution` (steps array) and `recovery` (per-step fallbacks).

### Step 3: Merge into a Plan
Combine the steps from all skills into ONE sequence:
- Login steps come first
- Remove duplicate navigation (if multiple skills navigate to the same page, keep only one)
- Annotate each step with its recovery info from the recovery data
- Inject `{{{{input_key}}}}` placeholders with actual user-provided values

### Step 4: Execute the Plan
Call:
```
execute_plan(steps: [...merged steps...], inputs: {{"key": "value"}})
```
The plugin will run a visible Playwright browser and execute all steps.

### Step 5: Handle Failures
If `execute_plan` returns an error:
- Check the error message for which step failed
- Reload the skill files with `read_skill_files`
- Adjust the plan (different selector, different sequence)
- Call `execute_plan` again with the fixed plan

---

## Authentication

If you get: *"Session expired. Ask Claude to call bootstrap_auth first."*
→ Call `bootstrap_auth` (opens a visible browser for the user to log in)
→ Once the user logs in and the browser closes, call `execute_plan` again

---

## Input Parameters

When calling `read_skill_files`, the response includes each step's `inputs` field.
Look for `{{{{key}}}}` placeholders in `value` fields — those are the required inputs to inject.
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


def _render_credentials_example() -> str:
    return json.dumps(
        {
            "_comment": "Copy this to credentials.json and fill in your values. This file is safe to commit.",
            "username": "your-email@example.com",
            "password": "your-password",
        },
        indent=2,
        ensure_ascii=False,
    )


# ─────────────────────────────────────────────────
# Main build entry point
# ─────────────────────────────────────────────────

def build_plugin(
    plugin_id: str,
    *,
    version: str = "0.1.0",
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Compile a plugin from its recorded sessions into a GitHub-ready skill package."""
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"Plugin {plugin_id!r} not found.")
    if plugin.auth is None:
        raise ValueError("Plugin has no recorded auth session. Record login first.")
    if not plugin.workflows:
        raise ValueError("Plugin has no workflows. Record at least one workflow.")

    def _log(msg: str, **extra: Any) -> None:
        entry = {"kind": "plugin_build", "message": msg, "plugin_id": plugin_id, **extra}
        if realtime_sink:
            realtime_sink(entry)

    bundle_slug = _plugin_bundle_slug(plugin_id, plugin.name)
    _log("Starting plugin build", bundle_slug=bundle_slug, version=version)

    from app.services.skill_pack_builder import build_skill_package

    # ── 1. Build auth/login skill ──────────────────────────────────────────
    _log("Building auth/login skill", session_id=plugin.auth.session_id)
    auth_events = read_session_events(plugin.auth.session_id)
    if not auth_events:
        raise ValueError(f"No events found for auth session {plugin.auth.session_id!r}.")

    auth_json_text = _events_to_json_text(auth_events, f"{plugin.name} login")
    build_skill_package(
        auth_json_text,
        package_name="_auth_login",
        bundle_slug=bundle_slug,
        realtime_sink=realtime_sink,
    )
    _log("Auth/login skill compiled")
    bundle_root = _bundle_root(bundle_slug)

    # ── 2. Build workflow skills ───────────────────────────────────────────
    skill_slugs: list[str] = []
    for wf in plugin.workflows:
        saved_skill = read_skill(wf.skill_id) if wf.skill_id else None
        if saved_skill is not None:
            _log(
                "Building workflow from saved skill JSON",
                workflow=wf.name,
                workflow_id=wf.id,
                skill_id=wf.skill_id,
            )
            _build_workflow_from_saved_skill(
                bundle_root=bundle_root,
                workflow_slug=wf.slug,
                saved_skill=saved_skill,
            )
            skill_slugs.append(wf.slug)
            _log(f"Workflow {wf.name!r} compiled from saved skill JSON")
            continue

        if wf.skill_id:
            _log(
                "Saved skill JSON not found; building workflow from original recording",
                workflow=wf.name,
                workflow_id=wf.id,
                skill_id=wf.skill_id,
                warning=True,
            )
        else:
            _log(
                "Building workflow from original recording",
                workflow=wf.name,
                workflow_id=wf.id,
                session_id=wf.session_id,
            )
        raw_events = read_session_events(wf.session_id)
        if not raw_events:
            _log(f"Skipping workflow {wf.name!r} — no events found", warning=True)
            continue

        clean_events = strip_login_steps(raw_events)
        stripped_count = len(raw_events) - len(clean_events)
        if stripped_count:
            _log(f"Stripped {stripped_count} login steps from workflow {wf.name!r}")

        wf_json_text = _events_to_json_text(clean_events, wf.name)
        build_skill_package(
            wf_json_text,
            package_name=wf.slug,
            bundle_slug=bundle_slug,
            realtime_sink=realtime_sink,
        )
        skill_slugs.append(wf.slug)
        _log(f"Workflow {wf.name!r} compiled")

    # ── 3. Post-process: restructure auth ─────────────────────────────────
    # Move skills/_auth_login/ → auth/login/
    auth_skill_src = bundle_root / "skills" / "_auth_login"
    auth_login_dir = bundle_root / "auth" / "login"
    if auth_skill_src.is_dir():
        if auth_login_dir.exists():
            shutil.rmtree(auth_login_dir)
        shutil.move(str(auth_skill_src), str(auth_login_dir))
        _log("Moved _auth_login skill to auth/login/")

    # auth/auth.json is captured locally via `conxa auth <plugin>` — never placed here.

    # ── 4. Write server.js — MCP server entry point ───────────────────────
    (bundle_root / "server.js").write_text(
        _render_mcp_server(plugin.name, plugin.protected_url, plugin.protected_url_marker_text),
        encoding="utf-8",
    )
    _log("Written server.js (MCP server)")

    # ── 5. Write auth/credentials.example.json ────────────────────────────
    creds_example_path = bundle_root / "auth" / "credentials.example.json"
    creds_example_path.parent.mkdir(parents=True, exist_ok=True)
    creds_example_path.write_text(_render_credentials_example(), encoding="utf-8")
    _log("Written auth/credentials.example.json")

    # ── 6. Write plugin.config.json ───────────────────────────────────────
    skills_list = [
        {"slug": "auth_login", "path": "skills/auth_login", "version": "1.0.0"},
        *[
            {"slug": slug, "path": f"skills/{slug}", "version": "1.0.0"}
            for slug in skill_slugs
        ]
    ]
    plugin_config = {
        "schema_version": "1.0",
        "id": plugin.id,
        "slug": bundle_slug,
        "name": plugin.name,
        "version": version,
        "description": f"Conxa plugin for {plugin.name}",
        "target_url": plugin.target_url,
        "protected_url": plugin.protected_url,
        "protected_url_marker_text": plugin.protected_url_marker_text,
        "built_at": time.time(),
        "auth": {
            "kind": "session",
            "storage_state": "auth/auth.json",
            "credentials_example": "auth/credentials.example.json",
            "login_skill": "auth/login",
        },
        "skills": skills_list,
        "execution": {
            "server": "server.js",
        },
        "dependencies": {
            "node": {
                "@modelcontextprotocol/sdk": "^1.0.0",
                "playwright": "^1.45.0",
            },
            "python": {},
        },
        "compatibility": {
            "conxa_runtime": ">=1.0.0",
            "node": ">=20",
        },
        "metadata": {
            "author": "",
            "repository": "",
            "license": "MIT",
            "tags": [],
        },
    }
    (bundle_root / "plugin.config.json").write_text(
        json.dumps(plugin_config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Remove legacy root plugin.json if it exists from a previous build.
    legacy = bundle_root / "plugin.json"
    if legacy.exists():
        legacy.unlink()
    _log("Written plugin.config.json", skills=skill_slugs)

    # ── 7. Write GitHub-ready root files ──────────────────────────────────
    claude_dir = bundle_root / ".claude-plugin"
    claude_dir.mkdir(parents=True, exist_ok=True)
    description = f"Conxa plugin for {plugin.name}"
    (claude_dir / "plugin.json").write_text(
        _render_claude_plugin_json(plugin.name, version, description),
        encoding="utf-8",
    )
    (claude_dir / "marketplace.json").write_text(
        _render_claude_marketplace_json(plugin.name, version, description),
        encoding="utf-8",
    )
    (bundle_root / ".mcp.json").write_text(
        _render_claude_mcp_json(bundle_slug),
        encoding="utf-8",
    )
    _log("Written Claude Code plugin marketplace files")

    (bundle_root / ".gitignore").write_text(_render_gitignore(), encoding="utf-8")
    _log("Written .gitignore")

    (bundle_root / "package.json").write_text(
        _render_package_json(plugin.name, version, description, {}),
        encoding="utf-8",
    )
    _log("Written package.json")

    (bundle_root / "README.md").write_text(
        _render_readme(plugin.name, bundle_slug, plugin.target_url, skill_slugs),
        encoding="utf-8",
    )
    _log("Written README.md")

    (bundle_root / "CLAUDE.md").write_text(
        _render_claude_md(plugin.name, plugin.target_url, skill_slugs),
        encoding="utf-8",
    )
    _log("Written CLAUDE.md")

    license_path = bundle_root / "LICENSE"
    if not license_path.exists():
        license_path.write_text(_render_license(), encoding="utf-8")
        _log("Written LICENSE")

    # ── 8. Persist build record ────────────────────────────────────────────
    set_build(plugin_id, output_path=str(bundle_root), version=version)

    return {
        "plugin_id": plugin_id,
        "bundle_slug": bundle_slug,
        "output_path": str(bundle_root),
        "version": version,
        "skills": skill_slugs,
        "auth_login_skill": str(auth_login_dir) if auth_login_dir.is_dir() else None,
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
            # auth/auth.json is a local credential — never include in the zip
            if rel.parts[0] == "auth" and rel.name == "auth.json":
                continue
            arcname = file_path.relative_to(bundle_root.parent).as_posix()
            zf.write(file_path, arcname)

    filename = f"{bundle_root.name}.zip"
    return filename, buf.getvalue()
