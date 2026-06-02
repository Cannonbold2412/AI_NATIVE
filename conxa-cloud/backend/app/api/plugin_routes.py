"""Plugin metadata routes (dashboard).

The cloud exposes read/list/delete plus workspace-scoped create for the
dashboard. Recording, compiling, building plugins/installers, and executing
skills all happen locally in the Build Studio — those endpoints are no longer
served here.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from conxa_core.config import settings
from conxa_core.db import db_get
from conxa_core.models.plugin import Plugin, PluginBuild, PluginInstaller, PluginWorkflow
from app.services.saas import add_audit_event, principal_from_request, ensure_principal, visible_workspace_ids_for
from conxa_core.storage.plugin_store import (
    create_plugin,
    delete_plugin,
    get_plugin,
    list_plugins,
    save_plugin,
)

router = APIRouter(prefix="/plugins", tags=["plugins"])


class CreatePluginBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    target_url: str = Field(..., min_length=1)
    protected_url: str = Field(default="")
    protected_url_marker_text: str = Field(default="")


def _backfill_plugin(plugin: Plugin) -> Plugin:
    """Populate build/installer/workflows for plugins published before these fields
    were persisted to the store. Uses disk files first; falls back to the
    sync_tokens Postgres record so this works even on ephemeral Render disks.
    Saves the enriched record on first run so subsequent requests pay no cost.
    """
    changed = False
    slug = plugin.slug

    # ── installer ──────────────────────────────────────────────────────────────
    if plugin.installer is None:
        exe_path = settings.data_dir / "installers" / slug / "installer.exe"
        meta_path = settings.data_dir / "installers" / slug / "meta.json"
        try:
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                plugin.installer = PluginInstaller(
                    built_at=float(meta.get("uploaded_at", 0)),
                    installer_path=str(exe_path),
                    filename=str(meta.get("filename", f"{slug}-Plugin-Setup.exe")),
                    version=str(meta.get("version", "0.1.0")),
                    runtime_version="",
                )
                changed = True
            elif exe_path.is_file():
                # meta.json gone (disk wiped); reconstruct version from Postgres.
                sync_rec = db_get("sync_tokens", slug) or {}
                version = str(sync_rec.get("version", "0.1.0"))
                plugin.installer = PluginInstaller(
                    built_at=exe_path.stat().st_mtime,
                    installer_path=str(exe_path),
                    filename=f"{slug}-Plugin-Setup.exe",
                    version=version,
                    runtime_version="",
                )
                changed = True
        except Exception:
            pass

    # ── build + workflows ──────────────────────────────────────────────────────
    if plugin.build is None or not plugin.workflows:
        pack_path = settings.data_dir / "skill-packs" / slug / "pack.json"
        try:
            if pack_path.is_file():
                pack = json.loads(pack_path.read_text(encoding="utf-8"))
                version = str(pack.get("skill_pack_version", "0.1.0"))
                skills: list[str] = pack.get("skills", [])
                if plugin.build is None:
                    plugin.build = PluginBuild(
                        last_built_at=float(pack.get("published_at", time.time())),
                        output_path="",
                        version=version,
                    )
                    changed = True
                if not plugin.workflows and skills:
                    now = float(pack.get("published_at", time.time()))
                    plugin.workflows = [
                        PluginWorkflow(
                            id=str(uuid.uuid4()),
                            slug=s,
                            name=s.replace("-", " ").title(),
                            session_id="",
                            recorded_at=now,
                            status="compiled",
                            skill_id=s,
                        )
                        for s in skills
                    ]
                    changed = True
            elif plugin.build is None:
                # pack.json gone; derive version from Postgres sync_tokens.
                sync_rec = db_get("sync_tokens", slug) or {}
                if sync_rec.get("version"):
                    plugin.build = PluginBuild(
                        last_built_at=float(sync_rec.get("updated_at", time.time())),
                        output_path="",
                        version=str(sync_rec["version"]),
                    )
                    changed = True
        except Exception:
            pass

    if changed:
        plugin = save_plugin(plugin)
    return plugin


def _visible_plugins(principal) -> list[Plugin]:
    visible_ids = set(visible_workspace_ids_for(principal))
    plugins: list[Plugin] = []
    for plugin in list_plugins():
        if plugin.workspace_id == principal.workspace_id:
            plugins.append(_backfill_plugin(plugin))
            continue
        if plugin.workspace_id in visible_ids and plugin.owner_user_id == principal.user_id:
            plugins.append(_backfill_plugin(plugin))
    return sorted(plugins, key=lambda p: p.updated_at, reverse=True)


def _plugin_or_404(plugin_id: str, principal) -> Plugin:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
    visible_ids = set(visible_workspace_ids_for(principal))
    if plugin.workspace_id != principal.workspace_id and not (
        plugin.workspace_id in visible_ids and plugin.owner_user_id == principal.user_id
    ):
        raise HTTPException(status_code=404, detail="Plugin not found.")
    return plugin


@router.post("")
def post_create_plugin(body: CreatePluginBody, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    ensure_principal(principal)
    plugin = create_plugin(
        name=body.name,
        target_url=body.target_url,
        protected_url=body.protected_url,
        protected_url_marker_text=body.protected_url_marker_text,
        workspace_id=principal.workspace_id,
        owner_user_id=principal.user_id,
    )
    add_audit_event(
        principal,
        "plugin_create",
        resource_type="plugin",
        resource_id=plugin.id,
        metadata={"name": body.name},
    )
    return {"plugin": plugin.model_dump(mode="json")}


@router.get("")
def get_list_plugins(request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    plugins = _visible_plugins(principal)
    return {"plugins": [p.model_dump(mode="json") for p in plugins]}


@router.get("/{plugin_id}")
def get_plugin_detail(plugin_id: str, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    plugin = _plugin_or_404(plugin_id, principal)
    return {"plugin": plugin.model_dump(mode="json")}


@router.delete("/{plugin_id}")
def delete_plugin_endpoint(plugin_id: str, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    plugin = _plugin_or_404(plugin_id, principal)
    # Remove built output if present.
    if plugin.build and plugin.build.output_path:
        out_path = Path(plugin.build.output_path)
        if out_path.is_dir():
            shutil.rmtree(out_path, ignore_errors=True)
    # Remove stored auth state.
    auth_dir = settings.data_dir / "plugins" / plugin_id
    if auth_dir.is_dir():
        shutil.rmtree(auth_dir, ignore_errors=True)
    if not delete_plugin(plugin_id):
        raise HTTPException(status_code=404, detail="Plugin not found.")
    add_audit_event(
        principal,
        "plugin_delete",
        resource_type="plugin",
        resource_id=plugin_id,
        metadata={"name": plugin.name},
    )
    return {"deleted": True, "plugin_id": plugin_id}
