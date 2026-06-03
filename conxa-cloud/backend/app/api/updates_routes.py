"""
Phase 4.5 — dependency manifest endpoint for Build Studio bootstrap.

GET /updates/deps-manifest    (public — fetched before Clerk login)
GET /updates/runtime-manifest (public — fetched by runtime self-updater)

The manifests are driven by environment variables so IT teams or CI can
update them without redeploying. The Build Studio bootstrap.py reads
deps-manifest on first launch; runtime/sync.js reads runtime-manifest
on each cold start (cached 24h locally).
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(tags=["updates"])

# ── Defaults baked in (CI overrides via env) ──────────────────────────────────

_NSIS_VERSION = os.environ.get("CONXA_NSIS_VERSION", "3.10")
_NSIS_URL = os.environ.get(
    "CONXA_NSIS_URL",
    f"https://downloads.sourceforge.net/project/nsis/NSIS%203/{_NSIS_VERSION}/nsis-{_NSIS_VERSION}.zip",
)
_NSIS_SHA256 = os.environ.get("CONXA_NSIS_SHA256", "")

# The actual repo hosting release artifacts. Override via env on Render once a
# dedicated org/repo is established. Default points at the monorepo where CI
# publishes runtime and studio releases.
_GITHUB_REPO = os.environ.get("CONXA_GITHUB_REPO", "Cannonbold2412/AI_NATIVE")

_RUNTIME_VERSION = os.environ.get("CONXA_RUNTIME_VERSION", "runtime-v1.0.0")
_RUNTIME_WIN_URL = os.environ.get(
    "CONXA_RUNTIME_WIN_URL",
    f"https://github.com/{_GITHUB_REPO}/releases/download/{_RUNTIME_VERSION}/runtime-win.exe",
)
_RUNTIME_WIN_SHA256 = os.environ.get("CONXA_RUNTIME_WIN_SHA256", "")
_RUNTIME_KEYTAR_URL = os.environ.get(
    "CONXA_KEYTAR_WIN_URL",
    f"https://github.com/{_GITHUB_REPO}/releases/download/{_RUNTIME_VERSION}/keytar.node",
)
_RUNTIME_KEYTAR_SHA256 = os.environ.get("CONXA_KEYTAR_WIN_SHA256", "")

_MIN_SKILL_PACK_VERSION = os.environ.get("CONXA_MIN_SKILL_PACK_VERSION", "0.3.0")
_PLAYWRIGHT_VERSION = os.environ.get("CONXA_PLAYWRIGHT_VERSION", "1.49.0")
_CHROMIUM_REVISION = os.environ.get("CONXA_CHROMIUM_REVISION", "1148460")

_STUDIO_VERSION = os.environ.get("CONXA_STUDIO_VERSION", "studio-v1.0.0")
_STUDIO_WIN_URL = os.environ.get(
    "CONXA_STUDIO_WIN_URL",
    f"https://github.com/{_GITHUB_REPO}/releases/download/{_STUDIO_VERSION}/Conxa%20Build%20Studio%20Setup%201.0.0.exe",
)
_STUDIO_WIN_SHA256 = os.environ.get("CONXA_STUDIO_WIN_SHA256", "")


@router.get("/updates/deps-manifest", include_in_schema=False)
def deps_manifest() -> dict:
    """
    Build Studio bootstrap.py fetches this on every startup to check for
    dependency updates. Public — called before the user logs in.

    Returns both legacy top-level keys (for pre-v2 Build Studio installs) and
    a generic ``deps`` dict that the v2 update loop iterates over. Adding a new
    dep only requires updating cloud env vars and the ``deps`` dict below —
    no Build Studio release needed as long as the dep's action is a known type
    ("copy" or "extract_zip").
    """
    return {
        # ── v2 envelope ──────────────────────────────────────────────────────
        "manifest_version": 2,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # ── legacy keys (v1 clients) ─────────────────────────────────────────
        "nsis": {
            "version": _NSIS_VERSION,
            "url": _NSIS_URL,
            "sha256": _NSIS_SHA256,
        },
        "runtime": {
            "version": _RUNTIME_VERSION,
            "win_url": _RUNTIME_WIN_URL,
            "win_sha256": _RUNTIME_WIN_SHA256,
            "keytar_url": _RUNTIME_KEYTAR_URL,
            "keytar_sha256": _RUNTIME_KEYTAR_SHA256,
        },
        # ── v2 generic deps dict ─────────────────────────────────────────────
        "deps": {
            "nsis": {
                "version": _NSIS_VERSION,
                "files": [
                    {
                        "filename": "nsis.zip",
                        "url": _NSIS_URL,
                        "sha256": _NSIS_SHA256,
                        "action": "extract_zip",
                    }
                ],
            },
            "runtime": {
                "version": _RUNTIME_VERSION,
                "files": [
                    {
                        "filename": "runtime-win.exe",
                        "url": _RUNTIME_WIN_URL,
                        "sha256": _RUNTIME_WIN_SHA256,
                        "action": "copy",
                    },
                    {
                        "filename": "keytar.node",
                        "url": _RUNTIME_KEYTAR_URL,
                        "sha256": _RUNTIME_KEYTAR_SHA256,
                        "action": "copy",
                    },
                ],
            },
        },
    }


@router.get("/updates/studio-manifest", include_in_schema=False)
def studio_manifest() -> dict:
    """
    Fetched by the web frontend to surface the Build Studio download link.
    Public — called without authentication.
    Set CONXA_STUDIO_WIN_URL on Render once the installer is published.
    """
    return {
        "version": _STUDIO_VERSION,
        "win_url": _STUDIO_WIN_URL,
        "win_sha256": _STUDIO_WIN_SHA256,
    }


@router.get("/updates/runtime-manifest", include_in_schema=False)
def runtime_manifest() -> dict:
    """
    runtime/sync.js fetches this on each cold start (cached 24h) to check
    whether runtime-win.exe needs updating.
    """
    return {
        "version": _RUNTIME_VERSION,
        "url": _RUNTIME_WIN_URL,
        "sha256": _RUNTIME_WIN_SHA256,
        "keytar_url": _RUNTIME_KEYTAR_URL,
        "keytar_sha256": _RUNTIME_KEYTAR_SHA256,
        "min_skill_pack_version": _MIN_SKILL_PACK_VERSION,
        "playwright_version": _PLAYWRIGHT_VERSION,
        "chromium_revision": _CHROMIUM_REVISION,
    }
