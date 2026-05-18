"""Filesystem JSON persistence for Plugin entities.

Layout:
  data/plugins/{plugin_id}.json  — one file per plugin
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.plugin import Plugin, PluginWorkflow, PluginAuth, PluginBuild, PluginInstaller


def _plugins_dir() -> Path:
    p = settings.data_dir / "plugins"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _plugin_path(plugin_id: str) -> Path:
    return _plugins_dir() / f"{plugin_id}.json"


def _read_raw(plugin_id: str) -> dict[str, Any] | None:
    path = _plugin_path(plugin_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_raw(plugin: Plugin) -> None:
    path = _plugin_path(plugin.id)
    path.write_text(
        json.dumps(plugin.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def create_plugin(name: str, target_url: str, protected_url: str, protected_url_marker_text: str = "") -> Plugin:
    import re
    slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "plugin"
    plugin_id = str(uuid.uuid4())
    now = time.time()
    plugin = Plugin(
        id=plugin_id,
        slug=f"{slug_base}-{plugin_id[:8]}",
        name=name,
        target_url=target_url,
        protected_url=protected_url,
        protected_url_marker_text=protected_url_marker_text,
        status="needs_auth",
        created_at=now,
        updated_at=now,
    )
    _write_raw(plugin)
    return plugin


def get_plugin(plugin_id: str) -> Plugin | None:
    raw = _read_raw(plugin_id)
    if raw is None:
        return None
    try:
        return Plugin.model_validate(raw)
    except Exception:
        return None


def list_plugins() -> list[Plugin]:
    out: list[Plugin] = []
    base = _plugins_dir()
    paths = sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            out.append(Plugin.model_validate(raw))
        except Exception:
            continue
    return out


def save_plugin(plugin: Plugin) -> Plugin:
    plugin = plugin.model_copy(update={"updated_at": time.time()})
    _write_raw(plugin)
    return plugin


def delete_plugin(plugin_id: str) -> bool:
    path = _plugin_path(plugin_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def set_plugin_auth(plugin_id: str, session_id: str, storage_state_path: str) -> Plugin | None:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        return None
    now = time.time()
    plugin.auth = PluginAuth(
        session_id=session_id,
        captured_at=now,
        storage_state_path=storage_state_path,
    )
    plugin.status = "ready"
    return save_plugin(plugin)


def add_workflow(plugin_id: str, name: str, session_id: str) -> tuple[Plugin, PluginWorkflow] | None:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        return None
    wf_id = str(uuid.uuid4())
    import re
    base_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workflow"
    existing_slugs = {w.slug for w in plugin.workflows}
    slug = base_slug
    counter = 2
    while slug in existing_slugs:
        slug = f"{base_slug}-{counter}"
        counter += 1
    wf = PluginWorkflow(
        id=wf_id,
        slug=slug,
        name=name,
        session_id=session_id,
        recorded_at=time.time(),
    )
    plugin.workflows.append(wf)
    return save_plugin(plugin), wf


def remove_workflow(plugin_id: str, workflow_id: str) -> Plugin | None:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        return None
    plugin.workflows = [w for w in plugin.workflows if w.id != workflow_id]
    return save_plugin(plugin)


def set_build(plugin_id: str, output_path: str, version: str = "0.1.0") -> Plugin | None:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        return None
    plugin.build = PluginBuild(
        last_built_at=time.time(),
        output_path=output_path,
        version=version,
    )
    return save_plugin(plugin)


def set_installer(
    plugin_id: str,
    *,
    installer_path: str,
    filename: str,
    version: str,
    runtime_version: str,
) -> Plugin | None:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        return None
    plugin.installer = PluginInstaller(
        built_at=time.time(),
        installer_path=installer_path,
        filename=filename,
        version=version,
        runtime_version=runtime_version,
    )
    return save_plugin(plugin)


