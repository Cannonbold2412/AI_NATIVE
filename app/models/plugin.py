"""Pydantic models for the Plugin entity."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PluginWorkflow(BaseModel):
    id: str
    slug: str
    name: str
    session_id: str
    recorded_at: float
    status: Literal["recorded", "compiled", "error"] = "recorded"
    skill_id: str | None = None
    # Pipeline state fields
    edited_at: float | None = None
    last_test_at: float | None = None
    last_test_status: Literal["passed", "failed", "never"] = "never"
    last_test_error: str | None = None
    last_test_inputs: dict[str, Any] = Field(default_factory=dict)


class PluginAuth(BaseModel):
    session_id: str
    captured_at: float
    storage_state_path: str


class PluginBuild(BaseModel):
    last_built_at: float
    output_path: str
    version: str = "0.1.0"


class PluginInstaller(BaseModel):
    built_at: float
    installer_path: str
    filename: str
    version: str
    runtime_version: str


class Plugin(BaseModel):
    id: str
    slug: str
    name: str
    owner_user_id: str = "local"
    workspace_id: str = ""
    target_url: str
    protected_url: str = ""
    protected_url_marker_text: str = ""
    status: Literal["needs_auth", "ready", "building", "error"] = "needs_auth"
    auth: PluginAuth | None = None
    workflows: list[PluginWorkflow] = Field(default_factory=list)
    build: PluginBuild | None = None
    installer: PluginInstaller | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
