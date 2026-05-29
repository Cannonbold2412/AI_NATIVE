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
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.db import db_get, db_set
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

    pack = {
        "skill_pack_version": body.skill_pack_version,
        "skills": list(body.skills),
        "workspace_id": principal.workspace_id,
        "published_at": time.time(),
    }
    pack_path = packs_dir / "pack.json"
    tmp = pack_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(pack_path)

    return {
        "slug": slug,
        "version": body.skill_pack_version,
        "files_written": written,
        "sync_url": f"/api/v1/skill-packs/{slug}/delta",
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

    max_bytes = 250 * 1024 * 1024
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
