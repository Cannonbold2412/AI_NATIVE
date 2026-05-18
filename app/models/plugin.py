"""Pydantic models for the Plugin entity."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PluginWorkflow(BaseModel):
    id: str
    slug: str
    name: str
    session_id: str
    recorded_at: float
    status: Literal["recorded", "compiled", "error"] = "recorded"
    skill_id: str | None = None


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
    target_url: str
    protected_url: str
    protected_url_marker_text: str = ""
    status: Literal["needs_auth", "ready", "building", "error"] = "needs_auth"
    auth: PluginAuth | None = None
    workflows: list[PluginWorkflow] = Field(default_factory=list)
    build: PluginBuild | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    # GitHub publishing metadata (populated after first publish)
    repository_url: str | None = None
    repository_private: bool = True
    last_published_version: str | None = None
    last_published_at: float | None = None
    last_commit_sha: str | None = None
    installer: PluginInstaller | None = None
    # Shared-runtime publish metadata (v2 manifest).
    # `package_id` is the org-scoped identifier used by `conxa install` (e.g. "acme/hr-onboarding").
    # Falls back to `slug` at build time when unset.
    package_id: str | None = None
    visibility: Literal["public", "private", "local"] = "private"
    tags: list[str] = Field(default_factory=list)
