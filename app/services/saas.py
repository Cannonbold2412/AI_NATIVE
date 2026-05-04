"""Workspace, billing, release, and audit metadata for the SaaS product layer.

The compiler still persists artifacts on disk. This module provides the
workspace-scoped product metadata around those artifacts and keeps a file-backed
local implementation for development until SKILL_DATABASE_URL is wired to a
database-backed repository.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request

from app.config import settings
from app.metrics.store import metrics
from app.services.jobs import job_store
from app.storage.json_store import list_skill_summaries
from app.storage.skill_packages import list_skill_bundle_summaries

LOCAL_USER_ID = "user_local"
LOCAL_WORKSPACE_ID = "wrk_local"
LOCAL_WORKSPACE_SLUG = "local"

_lock = threading.RLock()


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    workspace_slug: str
    workspace_name: str
    email: str | None = None
    name: str | None = None
    auth_provider: str = "local"

    def public_user(self) -> dict[str, Any]:
        return {
            "id": self.user_id,
            "email": self.email,
            "name": self.name,
            "auth_provider": self.auth_provider,
        }

    def public_workspace(self) -> dict[str, Any]:
        return {
            "id": self.workspace_id,
            "slug": self.workspace_slug,
            "name": self.workspace_name,
            "role": "owner",
        }


def _metadata_path() -> Path:
    path = settings.data_dir / "saas" / "metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _default_state() -> dict[str, Any]:
    now = time.time()
    return {
        "users": {
            LOCAL_USER_ID: {
                "id": LOCAL_USER_ID,
                "email": "local@ai-native.dev",
                "name": "Local Developer",
                "created_at": now,
            }
        },
        "workspaces": {
            LOCAL_WORKSPACE_ID: {
                "id": LOCAL_WORKSPACE_ID,
                "slug": LOCAL_WORKSPACE_SLUG,
                "name": "Local workspace",
                "created_at": now,
                "legacy_imported_at": now,
            }
        },
        "memberships": [
            {"user_id": LOCAL_USER_ID, "workspace_id": LOCAL_WORKSPACE_ID, "role": "owner", "created_at": now}
        ],
        "billing": {
            LOCAL_WORKSPACE_ID: {
                "plan": "development",
                "status": "inactive",
                "customer_id": None,
                "subscription_id": None,
                "current_period_end": None,
                "updated_at": now,
            }
        },
        "package_releases": {},
        "audit_events": [],
    }


def _read_state() -> dict[str, Any]:
    path = _metadata_path()
    if not path.is_file():
        state = _default_state()
        _write_state(state)
        return state
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    state = _default_state()
    if isinstance(data, dict):
        for key in state:
            if key in data:
                state[key] = data[key]
    return state


def _write_state(state: dict[str, Any]) -> None:
    path = _metadata_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _slug_from_org_id(org_id: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in org_id).strip("-")
    return text or "workspace"


def principal_from_request(request: Request) -> Principal:
    auth = getattr(request.state, "auth", None)
    if not isinstance(auth, dict) or not auth.get("subject"):
        return Principal(
            user_id=LOCAL_USER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            workspace_slug=LOCAL_WORKSPACE_SLUG,
            workspace_name="Local workspace",
            email="local@ai-native.dev",
            name="Local Developer",
        )

    claims = auth.get("claims") if isinstance(auth.get("claims"), dict) else {}
    subject = str(auth["subject"])
    org_id = str(auth.get("org_id") or f"personal_{subject}")
    workspace_slug = _slug_from_org_id(org_id)
    return Principal(
        user_id=subject,
        workspace_id=org_id,
        workspace_slug=workspace_slug,
        workspace_name=str(claims.get("org_name") or claims.get("azp") or "Workspace"),
        email=str(claims.get("email") or claims.get("primary_email_address") or "") or None,
        name=str(claims.get("name") or claims.get("full_name") or "") or None,
        auth_provider="clerk",
    )


def ensure_principal(principal: Principal) -> None:
    with _lock:
        state = _read_state()
        now = time.time()
        state.setdefault("users", {})[principal.user_id] = {
            "id": principal.user_id,
            "email": principal.email,
            "name": principal.name,
            "auth_provider": principal.auth_provider,
            "updated_at": now,
        }
        state.setdefault("workspaces", {})[principal.workspace_id] = {
            "id": principal.workspace_id,
            "slug": principal.workspace_slug,
            "name": principal.workspace_name,
            "updated_at": now,
            "legacy_imported_at": state.get("workspaces", {})
            .get(principal.workspace_id, {})
            .get("legacy_imported_at", now),
        }
        memberships = state.setdefault("memberships", [])
        if not any(
            row.get("user_id") == principal.user_id and row.get("workspace_id") == principal.workspace_id
            for row in memberships
            if isinstance(row, dict)
        ):
            memberships.append(
                {
                    "user_id": principal.user_id,
                    "workspace_id": principal.workspace_id,
                    "role": "owner",
                    "created_at": now,
                }
            )
        state.setdefault("billing", {}).setdefault(
            principal.workspace_id,
            {
                "plan": "development" if principal.auth_provider == "local" else "free",
                "status": "inactive",
                "customer_id": None,
                "subscription_id": None,
                "current_period_end": None,
                "updated_at": now,
            },
        )
        _write_state(state)


def add_audit_event(
    principal: Principal,
    action: str,
    *,
    resource_type: str,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        event = {
            "id": f"evt_{int(time.time() * 1000)}",
            "workspace_id": principal.workspace_id,
            "user_id": principal.user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "metadata": metadata or {},
            "created_at": time.time(),
        }
        events = state.setdefault("audit_events", [])
        events.append(event)
        state["audit_events"] = events[-500:]
        _write_state(state)
        return event


def audit_events_for(principal: Principal, limit: int = 100) -> list[dict[str, Any]]:
    ensure_principal(principal)
    with _lock:
        state = _read_state()
        rows = [
            row
            for row in state.get("audit_events", [])
            if isinstance(row, dict) and row.get("workspace_id") == principal.workspace_id
        ]
    rows.sort(key=lambda row: float(row.get("created_at") or 0), reverse=True)
    return rows[: max(1, min(limit, 500))]


def billing_for(principal: Principal) -> dict[str, Any]:
    ensure_principal(principal)
    with _lock:
        state = _read_state()
        billing = dict(state.get("billing", {}).get(principal.workspace_id) or {})
    billing.setdefault("plan", "development" if principal.auth_provider == "local" else "free")
    billing.setdefault("status", "inactive")
    billing["stripe_configured"] = bool(settings.stripe_secret_key and settings.stripe_price_id)
    return billing


def upsert_billing(workspace_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        state = _read_state()
        current = dict(state.setdefault("billing", {}).get(workspace_id) or {})
        current.update(patch)
        current["updated_at"] = time.time()
        state["billing"][workspace_id] = current
        _write_state(state)
        return current


def _release_key(principal: Principal, bundle_slug: str) -> str:
    return f"{principal.workspace_id}:{bundle_slug}"


def release_for(principal: Principal, bundle_slug: str) -> dict[str, Any]:
    ensure_principal(principal)
    with _lock:
        state = _read_state()
        release = dict(state.get("package_releases", {}).get(_release_key(principal, bundle_slug)) or {})
    release.setdefault("bundle_slug", bundle_slug)
    release.setdefault("workspace_id", principal.workspace_id)
    release.setdefault("state", "draft")
    release.setdefault("version", "0.1.0")
    release.setdefault("release_notes", "")
    release.setdefault("published_by", None)
    release.setdefault("published_at", None)
    release.setdefault("archived_at", None)
    return release


def update_release(principal: Principal, bundle_slug: str, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_principal(principal)
    with _lock:
        state = _read_state()
        key = _release_key(principal, bundle_slug)
        current = release_for(principal, bundle_slug)
        current.update(patch)
        current["bundle_slug"] = bundle_slug
        current["workspace_id"] = principal.workspace_id
        current["updated_at"] = time.time()
        state.setdefault("package_releases", {})[key] = current
        _write_state(state)
    add_audit_event(
        principal,
        "package_release_updated",
        resource_type="package_bundle",
        resource_id=bundle_slug,
        metadata={"state": current.get("state"), "version": current.get("version")},
    )
    return current


def usage_for(principal: Principal) -> dict[str, Any]:
    ensure_principal(principal)
    skills = list_skill_summaries()
    packages = list_skill_bundle_summaries()
    jobs = job_store.list()
    workflow_count = sum(len(pkg.get("workflows") or []) for pkg in packages)
    return {
        "workspace_id": principal.workspace_id,
        "skills": len(skills),
        "packages": len(packages),
        "workflows": workflow_count,
        "jobs": len(jobs),
        "active_jobs": sum(1 for job in jobs if job.status in {"queued", "running"}),
        "metrics": metrics.snapshot(),
        "limits": {
            "skills": None,
            "packages": None,
            "monthly_recordings": None,
        },
    }


def dashboard_for(principal: Principal) -> dict[str, Any]:
    ensure_principal(principal)
    skills = list_skill_summaries()
    packages = list_skill_bundle_summaries()
    jobs = [job.public() for job in job_store.list()]
    releases = [release_for(principal, str(pkg.get("package_name"))) for pkg in packages]
    published = sum(1 for release in releases if release.get("state") == "published")
    return {
        "workspace": principal.public_workspace(),
        "stats": {
            "skills": len(skills),
            "packages": len(packages),
            "workflows": sum(len(pkg.get("workflows") or []) for pkg in packages),
            "active_jobs": sum(1 for job in jobs if job.get("status") in {"queued", "running"}),
            "published_packages": published,
        },
        "recent_workflows": skills[:6],
        "recent_packages": packages[:6],
        "active_jobs": [job for job in jobs if job.get("status") in {"queued", "running"}][:6],
        "package_health": [
            {
                "package_name": pkg.get("package_name"),
                "workflow_count": len(pkg.get("workflows") or []),
                "file_count": len(pkg.get("files") or []),
                "release_state": release_for(principal, str(pkg.get("package_name"))).get("state"),
            }
            for pkg in packages[:6]
        ],
        "usage": usage_for(principal),
    }
