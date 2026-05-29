"""Plugin metadata routes (dashboard).

The cloud exposes read/list/delete plus workspace-scoped create for the
dashboard. Recording, compiling, building plugins/installers, and executing
skills all happen locally in the Build Studio — those endpoints are no longer
served here.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from conxa_core.config import settings
from conxa_core.models.plugin import Plugin
from app.services.saas import principal_from_request, ensure_principal
from conxa_core.storage.plugin_store import (
    create_plugin,
    delete_plugin,
    get_plugin,
    list_plugins,
)

router = APIRouter(prefix="/plugins", tags=["plugins"])


class CreatePluginBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    target_url: str = Field(..., min_length=1)
    protected_url: str = Field(default="")
    protected_url_marker_text: str = Field(default="")


def _plugin_or_404(plugin_id: str, workspace_id: str) -> Plugin:
    plugin = get_plugin(plugin_id, workspace_id=workspace_id)
    if plugin is None:
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
    )
    return {"plugin": plugin.model_dump(mode="json")}


@router.get("")
def get_list_plugins(request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    plugins = list_plugins(workspace_id=principal.workspace_id)
    return {"plugins": [p.model_dump(mode="json") for p in plugins]}


@router.get("/{plugin_id}")
def get_plugin_detail(plugin_id: str, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    plugin = _plugin_or_404(plugin_id, principal.workspace_id)
    return {"plugin": plugin.model_dump(mode="json")}


@router.delete("/{plugin_id}")
def delete_plugin_endpoint(plugin_id: str, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    plugin = _plugin_or_404(plugin_id, principal.workspace_id)
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
    return {"deleted": True, "plugin_id": plugin_id}
