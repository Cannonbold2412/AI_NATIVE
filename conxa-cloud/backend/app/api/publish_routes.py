"""Publish + installer-hosting endpoints used by Build Studio and end users.

Build Studio compiles locally, then publishes the data-only skill pack here so
runtime.exe instances can pull deltas (served by skillpack_update_routes), and
uploads the built ``{Company}-Plugin-Setup.exe`` for end-user download.

Ownership: the first workspace to publish a slug owns it. Subsequent publishes
or installer uploads for that slug must come from the same workspace (403
otherwise). Installer *downloads* are public — end users have no Clerk account.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from conxa_core.config import settings
from conxa_core.db import db_get, db_set
from conxa_core.storage.plugin_store import create_plugin, list_plugins, save_plugin
from app.services.saas import ensure_principal, principal_from_request

router = APIRouter(prefix="/plugins", tags=["publish"])
installers_router = APIRouter(prefix="/installers", tags=["installers"])

_OWNERS_NS = "publish_owners"
_SAFE_SLUG = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class PublishFile(BaseModel):
    path: str = Field(..., min_length=1, max_length=256)
    content_base64: str = Field(..., min_length=1)


class PublishBody(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    target_url: str = Field(default="")
    protected_url: str = Field(default="")
    skill_pack_version: str = Field(..., min_length=1, max_length=32)
    skills: list[str] = Field(default_factory=list)
    files: list[PublishFile] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_slug(slug: str) -> str:
    s = slug.strip()
    if not s or any(c not in _SAFE_SLUG for c in s) or ".." in s:
        raise HTTPException(status_code=400, detail="invalid_slug")
    return s


def _validate_rel_path(rel: str) -> str:
    r = rel.strip().replace("\\", "/")
    if not r or r.startswith("/") or ".." in r.split("/"):
        raise HTTPException(status_code=400, detail=f"invalid_file_path: {rel}")
    return r


def _skill_packs_dir(slug: str) -> Path:
    return settings.data_dir / "skill-packs" / slug


def _installer_dir(slug: str) -> Path:
    return settings.data_dir / "installers" / slug


def _owner_of(slug: str) -> str | None:
    row = db_get(_OWNERS_NS, slug)
    if isinstance(row, dict):
        return str(row.get("workspace_id") or "") or None
    return None


def _assert_owner(slug: str, workspace_id: str) -> None:
    owner = _owner_of(slug)
    if owner and owner != workspace_id:
        raise HTTPException(status_code=403, detail="slug_owned_by_another_workspace")
    if not owner:
        db_set(_OWNERS_NS, slug, {"workspace_id": workspace_id, "claimed_at": time.time()})


def _tracking_token(slug: str, workspace_id: str, version: str) -> str:
    existing = db_get("tracking_tokens", slug)
    if isinstance(existing, dict) and existing.get("token"):
        token = str(existing["token"])
    else:
        token = secrets.token_urlsafe(32)
    db_set(
        "tracking_tokens",
        slug,
        {
            "token": token,
            "version": version,
            "workspace_id": workspace_id,
            "updated_at": time.time(),
        },
    )
    return token


def _api_base(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _upsert_published_plugin(body: PublishBody, workspace_id: str) -> None:
    name = body.display_name.strip() or body.slug
    target_url = body.target_url.strip() or "https://example.com"
    protected_url = body.protected_url.strip()
    existing = next(
        (
            plugin
            for plugin in list_plugins(workspace_id=workspace_id)
            if plugin.slug == body.slug or plugin.name.lower() == name.lower()
        ),
        None,
    )
    if existing is None:
        plugin = create_plugin(
            name=name,
            target_url=target_url,
            protected_url=protected_url,
            workspace_id=workspace_id,
        )
        plugin = plugin.model_copy(update={"slug": body.slug, "status": "ready"})
    else:
        plugin = existing.model_copy(
            update={
                "name": name,
                "target_url": target_url or existing.target_url,
                "protected_url": protected_url or existing.protected_url,
                "status": "ready",
            }
        )
    save_plugin(plugin)


# ---------------------------------------------------------------------------
# Publish skill pack data
# ---------------------------------------------------------------------------

@router.post("/publish")
def post_publish(body: PublishBody, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    ensure_principal(principal)
    slug = _validate_slug(body.slug)
    _assert_owner(slug, principal.workspace_id)

    packs_dir = _skill_packs_dir(slug)
    packs_dir.mkdir(parents=True, exist_ok=True)
    pack_path = packs_dir / "pack.json"

    written = 0
    for f in body.files:
        rel = _validate_rel_path(f.path)
        try:
            raw = base64.b64decode(f.content_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise HTTPException(status_code=400, detail=f"invalid_base64: {rel}") from exc
        target = packs_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(raw)
        tmp.replace(target)
        written += 1

    published_at = time.time()
    tracking = {
        "enabled": True,
        "tracking_url": f"{_api_base(request)}/api/tracking/{slug}/events",
        "tracking_token": _tracking_token(slug, principal.workspace_id, body.skill_pack_version),
        "company_id": slug,
        "schema_version": 1,
        "protocol_version": 1,
    }
    if pack_path.is_file():
        try:
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pack = {}
    else:
        pack = {}
    pack.update(
        {
            "company": pack.get("company") or slug,
            "company_display": body.display_name.strip() or pack.get("company_display") or slug,
            "skill_pack_version": body.skill_pack_version,
            "skills": list(body.skills),
            "workspace_id": principal.workspace_id,
            "published_at": published_at,
            "sync_endpoint": f"{_api_base(request)}/api/v1/skill-packs/{slug}/delta",
            "tracking": tracking,
        }
    )
    tmp = pack_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(pack_path)
    _upsert_published_plugin(body, principal.workspace_id)

    return {
        "slug": slug,
        "version": body.skill_pack_version,
        "files_written": written,
        "sync_url": f"/api/v1/skill-packs/{slug}/delta",
        "tracking": tracking,
        "workspace_id": principal.workspace_id,
        "published_at": published_at,
    }


# ---------------------------------------------------------------------------
# Installer upload (authed) + download (public)
# ---------------------------------------------------------------------------

@router.post("/{slug}/installer/upload")
async def post_installer_upload(slug: str, request: Request) -> dict[str, Any]:
    """Upload the built installer .exe as a raw octet-stream body.

    Query params: ``filename`` (display name), ``version``.
    """
    principal = principal_from_request(request)
    ensure_principal(principal)
    slug = _validate_slug(slug)
    _assert_owner(slug, principal.workspace_id)

    max_bytes = settings.build_artifact_upload_max_bytes
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        raise HTTPException(status_code=413, detail="installer_too_large")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty_installer_body")
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="installer_too_large")

    sha256 = hashlib.sha256(body).hexdigest()
    version = request.query_params.get("version", "0.0.0")
    filename = request.query_params.get("filename") or f"{slug}-Plugin-Setup.exe"
    filename = Path(filename).name  # strip any path components

    out_dir = _installer_dir(slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    exe_path = out_dir / "installer.exe"
    tmp = exe_path.with_suffix(".exe.tmp")
    tmp.write_bytes(body)
    tmp.replace(exe_path)

    meta = {
        "slug": slug,
        "filename": filename,
        "version": version,
        "sha256": sha256,
        "size": len(body),
        "uploaded_at": time.time(),
        "workspace_id": principal.workspace_id,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {
        "slug": slug,
        "sha256": sha256,
        "size": len(body),
        "download_url": f"/api/v1/installers/{slug}",
    }


@installers_router.get("/{slug}")
def get_installer(slug: str) -> StreamingResponse:
    """Public end-user installer download. SHA-256 returned in X-Conxa-SHA256."""
    slug = _validate_slug(slug)
    out_dir = _installer_dir(slug)
    exe_path = out_dir / "installer.exe"
    meta_path = out_dir / "meta.json"
    if not exe_path.is_file() or not meta_path.is_file():
        raise HTTPException(status_code=404, detail="installer_not_published")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    headers = {
        "Content-Disposition": f'attachment; filename="{meta.get("filename", "setup.exe")}"',
        "X-Conxa-SHA256": str(meta.get("sha256", "")),
    }
    return StreamingResponse(
        open(exe_path, "rb"),  # noqa: SIM115
        media_type="application/octet-stream",
        headers=headers,
    )
