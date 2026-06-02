"""Endpoints consumed by runtime.exe at startup for skill pack sync."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from conxa_core.config import settings
from conxa_core.db import db_get

router = APIRouter(prefix="/skill-packs", tags=["skill-packs"])

# Rate limiter: {token_prefix: last_request_ts}
_rate_cache: dict[str, float] = {}
_RATE_LIMIT_SECONDS = 300  # 5 minutes between sync requests per token


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return None


def _rate_limit_key(token: str) -> str:
    # Use first 16 chars of token hash as key — avoids storing full tokens
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _check_rate_limit(token: str) -> None:
    key = _rate_limit_key(token)
    last = _rate_cache.get(key, 0.0)
    if time.time() - last < _RATE_LIMIT_SECONDS:
        raise HTTPException(
            status_code=429,
            detail="Too many sync requests. Wait 5 minutes between syncs.",
            headers={"Retry-After": str(int(_RATE_LIMIT_SECONDS - (time.time() - last)))},
        )
    _rate_cache[key] = time.time()


def _verify_sync_token(company: str, token: str | None) -> None:
    """Validate the Bearer token against the per-company sync_token.

    In production (SKILL_AUTH_REQUIRED=true) a valid sync token is required.
    The sync token is minted at publish time and embedded in the installer's
    pack.json — end users never need a Conxa login.

    In local dev (auth_required=false) validation is skipped so the Build
    Studio can sync without a published token.
    """
    if not settings.auth_required:
        return
    stored = db_get("sync_tokens", company)
    if not isinstance(stored, dict) or not stored.get("token"):
        raise HTTPException(status_code=401, detail="sync_token_not_configured")
    if not token or not secrets.compare_digest(str(stored["token"]), token):
        raise HTTPException(status_code=401, detail="invalid_sync_token")


def _skill_packs_dir(company: str) -> Path:
    return settings.data_dir / "skill-packs" / company


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _pack_version(company: str) -> str:
    pack_path = _skill_packs_dir(company) / "pack.json"
    if not pack_path.is_file():
        return "0"
    try:
        return json.loads(pack_path.read_text(encoding="utf-8")).get("skill_pack_version", "0")
    except Exception:
        return "0"


def _build_delta(company: str, since_version: str) -> dict[str, Any]:
    """Compute which skill files changed since `since_version`.

    Simplified implementation: returns all files whenever the pack version
    differs from `since_version`. For production, this should diff by
    comparing individual file checksums against a version manifest.
    """
    packs_dir = _skill_packs_dir(company)
    pack_path = packs_dir / "pack.json"
    if not pack_path.is_file():
        raise HTTPException(status_code=404, detail=f"Skill pack not found: {company}")

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    current_version = pack.get("skill_pack_version", "0")

    if current_version == since_version:
        return {"current_version": current_version, "base_version": since_version, "files": []}

    files: list[dict[str, Any]] = []
    for slug in pack.get("skills", []):
        skill_dir = packs_dir / slug
        if not skill_dir.is_dir():
            continue
        for fname in ("execution.json", "recovery.json", "inputs.json", "manifest.json", "validation.json"):
            fpath = skill_dir / fname
            if not fpath.is_file():
                continue
            files.append({
                "skill":          slug,
                "path":           f"{slug}/{fname}",
                "action":         "update",
                "sha256":         _sha256_file(fpath),
                "_content_bytes": fpath.read_bytes(),
            })

    for f in files:
        raw = f.pop("_content_bytes", b"")
        f["content_base64"] = base64.b64encode(raw).decode("ascii")

    return {"current_version": current_version, "base_version": since_version, "files": files}


@router.get("/{company}/delta")
def get_skill_pack_delta(company: str, since: str = "0", request: Request = None) -> dict[str, Any]:
    """Return files changed since `since` version as base64-encoded content.

    Authentication: Bearer token must match the per-company sync_token minted
    at publish time and embedded in the installer's pack.json.
    Rate limited: 1 request per 5 minutes per token.
    """
    token = _extract_token(request) if request else None
    _verify_sync_token(company, token)
    if token:
        _check_rate_limit(token)
    return _build_delta(company, since)


# ─── Telemetry ────────────────────────────────────────────────────────────────

class TelemetryBody(BaseModel):
    runtime_version: str = ""
    companies: list[str] = []
    platform: str = ""


telemetry_router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@telemetry_router.post("/runtime-start")
def post_telemetry_runtime_start(body: TelemetryBody) -> dict[str, Any]:
    """Non-critical. Records which runtime versions are active for ops visibility."""
    # In production: write to analytics DB / metrics system.
    return {"ok": True}
