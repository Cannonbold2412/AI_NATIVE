"""Endpoints consumed by runtime.exe at startup for skill pack sync and auth."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from conxa_core.config import settings

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
                "content_base64": fpath.read_bytes().decode("latin-1").encode("utf-8"),  # placeholder
                "_content_bytes": fpath.read_bytes(),
            })

    # Encode file content as base64 for inline delivery
    import base64
    for f in files:
        raw = f.pop("_content_bytes", b"")
        f["content_base64"] = base64.b64encode(raw).decode("ascii")

    return {"current_version": current_version, "base_version": since_version, "files": files}


@router.get("/{company}/delta")
def get_skill_pack_delta(company: str, since: str = "0", request: Request = None) -> dict[str, Any]:
    """Return files changed since `since` version as base64-encoded content.

    Rate limited: 1 request per 5 minutes per token.
    """
    token = _extract_token(request) if request else None
    # In production: verify token against Clerk/JWT. Local dev: skip.
    if token and settings.auth_required:
        _check_rate_limit(token)

    return _build_delta(company, since)


# ─── Auth endpoints ───────────────────────────────────────────────────────────

class RefreshBody(BaseModel):
    token: str
    company: str


class PollBody(BaseModel):
    nonce: str


class TelemetryBody(BaseModel):
    runtime_version: str = ""
    companies: list[str] = []
    platform: str = ""


# In-memory nonce store — replace with Redis in production
_auth_nonces: dict[str, dict[str, Any]] = {}


auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/refresh")
def post_auth_refresh(body: RefreshBody) -> dict[str, Any]:
    """Attempt to refresh a Conxa auth token.

    In production this validates against Clerk and issues a new JWT.
    Local dev returns a fixed response.
    """
    if not body.token:
        raise HTTPException(status_code=401, detail="Token required.")
    # Local dev: echo back with extended expiry
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400 * 30))
    return {"token": body.token, "expires_at": expires_at}


@auth_router.post("/cli/poll")
def post_auth_cli_poll(body: PollBody) -> dict[str, Any]:
    nonce = body.nonce
    if nonce in _auth_nonces:
        entry = _auth_nonces.pop(nonce)
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400 * 30))
        return {"token": entry["token"], "expires_at": expires_at}
    return {"status": "pending"}


@auth_router.post("/cli/complete")
def post_auth_cli_complete(nonce: str, token: str) -> dict[str, Any]:
    """Called by Conxa web UI after user logs in via deep-link auth flow."""
    _auth_nonces[nonce] = {"token": token, "ts": time.time()}
    return {"ok": True}


# ─── Telemetry ────────────────────────────────────────────────────────────────

telemetry_router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@telemetry_router.post("/runtime-start")
def post_telemetry_runtime_start(body: TelemetryBody) -> dict[str, Any]:
    """Non-critical. Records which runtime versions are active for ops visibility."""
    # In production: write to analytics DB / metrics system.
    return {"ok": True}
