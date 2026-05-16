"""GitHub OAuth + plugin publish API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.integrations.github_oauth import (
    _frontend_origin,
    get_status,
    handle_callback,
    revoke,
    start_oauth,
)
from app.services.github_publisher import (
    NoBuildError,
    PublishResult,
    VersionAlreadyPublished,
    next_versions,
    publish,
)
from app.storage.plugin_store import get_plugin

router = APIRouter(tags=["publish"])

_DEFAULT_WORKSPACE = "local"


def _workspace_id(request: Request) -> str:
    """Derive workspace ID from request context. Returns 'local' for unauthenticated dev."""
    workspace_id = getattr(request.state, "workspace_id", None)
    if workspace_id:
        return str(workspace_id)

    auth = getattr(request.state, "auth", None)
    if isinstance(auth, dict):
        return str(auth.get("org_id") or auth.get("subject") or _DEFAULT_WORKSPACE)

    return _DEFAULT_WORKSPACE


# ─────────────────────────────────────────────────────────────────────────────
# GitHub OAuth endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/integrations/github/status")
def github_status(request: Request) -> dict:
    return get_status(_workspace_id(request))


@router.get("/integrations/github/connect")
def github_connect(request: Request) -> RedirectResponse:
    url = start_oauth(_workspace_id(request))
    return RedirectResponse(url, status_code=302)


@router.get("/integrations/github/callback")
def github_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    """OAuth callback — returns HTML that posts a message to the opener and closes."""
    frontend = _frontend_origin()
    if error or not code:
        html = f"""<!doctype html><html><body><script>
window.opener && window.opener.postMessage({{type:'github-oauth-error',error:{repr(error or 'missing_code')}}}, {repr(frontend)});
window.close();
</script></body></html>"""
        return HTMLResponse(html)

    try:
        result = handle_callback(code, state)
        login = result["login"]
        html = f"""<!doctype html><html><body><script>
window.opener && window.opener.postMessage({{type:'github-oauth-success',login:{repr(login)}}}, '*');
window.close();
</script></body></html>"""
    except Exception as exc:  # noqa: BLE001
        html = f"""<!doctype html><html><body><script>
window.opener && window.opener.postMessage({{type:'github-oauth-error',error:{repr(str(exc))}}}, '*');
window.close();
</script></body></html>"""
    return HTMLResponse(html)


@router.post("/integrations/github/disconnect")
def github_disconnect(request: Request) -> dict:
    revoke(_workspace_id(request))
    return {"disconnected": True}


# ─────────────────────────────────────────────────────────────────────────────
# Plugin publish endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/plugins/{plugin_id}/publish/preview")
def publish_preview(plugin_id: str, request: Request) -> dict:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(404, "Plugin not found")

    current = plugin.last_published_version or (plugin.build.version if plugin.build else "0.0.0")
    repo_status = "linked" if plugin.repository_url else "unlinked"

    bundle_files: list[str] = []
    if plugin.build:
        from pathlib import Path
        bp = Path(plugin.build.output_path)
        if bp.is_dir():
            bundle_files = sorted(
                str(p.relative_to(bp)) for p in bp.rglob("*") if p.is_file()
            )

    return {
        "plugin_id": plugin_id,
        "current_version": current,
        "next_versions": next_versions(current),
        "repo_status": repo_status,
        "repo_url": plugin.repository_url,
        "last_published_version": plugin.last_published_version,
        "last_commit_sha": plugin.last_commit_sha,
        "bundle_files": bundle_files,
        "has_build": plugin.build is not None,
    }


class PublishBody(BaseModel):
    version_bump: Literal["patch", "minor", "major"] | None = "patch"
    manual_version: str | None = None
    changelog: str = ""
    create_repo: bool = False
    repo_name: str | None = None
    repo_url: str | None = None   # override stored repository_url
    private: bool = True


@router.post("/plugins/{plugin_id}/publish")
def publish_plugin(plugin_id: str, body: PublishBody, request: Request) -> dict:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(404, "Plugin not found")
    if plugin.build is None:
        raise HTTPException(400, "Plugin has not been built yet. Build it first.")

    workspace_id = _workspace_id(request)
    status = get_status(workspace_id)
    if not status["connected"]:
        raise HTTPException(401, "GitHub is not connected. Connect GitHub on the Publish page.")

    try:
        result: PublishResult = publish(
            plugin_id,
            workspace_id,
            version_bump=body.version_bump,
            manual_version=body.manual_version,
            changelog=body.changelog,
            create_repo=body.create_repo,
            repo_name=body.repo_name,
            repo_url=body.repo_url,
            private=body.private,
        )
    except VersionAlreadyPublished as exc:
        raise HTTPException(409, str(exc)) from exc
    except NoBuildError as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Publish failed: {exc}") from exc

    return {
        "repo_url": result.repo_url,
        "version": result.version,
        "commit_sha": result.commit_sha,
        "install_snippet": result.install_snippet,
    }
