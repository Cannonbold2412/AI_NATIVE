"""Plugin-first API routes.

Manages Plugin entities (create, list, get, delete) and per-plugin workflows.
Auth recording and workflow recording endpoints delegate to the recorder.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from io import BytesIO
from pathlib import Path
from queue import SimpleQueue
from typing import Any, AsyncIterator, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.models.plugin import Plugin
from app.recorder.session import is_blank_url, registry
from app.services.saas import principal_from_request, ensure_principal
from app.storage.plugin_store import (
    add_workflow,
    create_plugin,
    delete_plugin,
    get_plugin,
    list_plugins,
    remove_workflow,
    save_plugin,
    set_plugin_auth,
)

router = APIRouter(prefix="/plugins", tags=["plugins"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------

class CreatePluginBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    target_url: str = Field(..., min_length=1)
    protected_url: str = Field(default="")
    protected_url_marker_text: str = Field(default="")


class StartAuthRecordBody(BaseModel):
    """Optional override for the auth recording start URL (defaults to plugin.target_url)."""
    start_url: str | None = Field(default=None)


class FinalizeAuthBody(BaseModel):
    session_id: str


class StartWorkflowRecordBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    url_variables: dict[str, str] = Field(default_factory=dict)
    capture_hover: bool = Field(False, description="Capture hover events for workflows that depend on hover-revealed elements.")


class FinalizeWorkflowBody(BaseModel):
    session_id: str
    workflow_id: str
    force_workflow_kind: str | None = None  # "login" | "workflow" | None (auto-detect)


class UpdateWorkflowBody(BaseModel):
    skill_id: str | None = None


class BuildPluginBody(BaseModel):
    version: str = Field(default="0.1.0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plugin_or_404(plugin_id: str) -> Plugin:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
    return plugin


def _storage_state_path(plugin_id: str) -> Path:
    """Canonical location for a plugin's captured browser session."""
    p = settings.data_dir / "plugins" / plugin_id / "auth"
    p.mkdir(parents=True, exist_ok=True)
    return p / "auth.json"


def _sse_line(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


_FINAL_URL_LOGIN_PATTERNS = (
    "login",
    "signin",
    "sign-in",
    "auth",
    "oauth",
    "sso",
    "session/new",
    "account/login",
    "accountchooser",
    "account-chooser",
)


def _reject_reason_for_protected_url(url: str) -> str:
    value = str(url or "").strip()
    if is_blank_url(value):
        return "No authenticated page URL was captured. Log in, navigate to the page where workflows should start, then close Chromium."
    try:
        from urllib.parse import urlparse

        parsed = urlparse(value)
    except Exception:
        return "The captured protected URL is not valid."
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "The captured protected URL must be an http or https page."
    lowered = value.lower()
    if any(marker in lowered for marker in _FINAL_URL_LOGIN_PATTERNS):
        return "The final page still looks like a login/auth page. Navigate to the authenticated app page, then close Chromium."
    return ""


async def _start_recorder_session(sess: Any) -> None:
    try:
        await sess.start()
    except RuntimeError as exc:
        registry.pop(sess.session_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Plugin CRUD
# ---------------------------------------------------------------------------

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
    plugin = get_plugin(plugin_id, workspace_id=principal.workspace_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
    return {"plugin": plugin.model_dump(mode="json")}


@router.delete("/{plugin_id}")
def delete_plugin_endpoint(plugin_id: str, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    plugin = get_plugin(plugin_id, workspace_id=principal.workspace_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
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


# ---------------------------------------------------------------------------
# Auth recording
# ---------------------------------------------------------------------------

@router.post("/{plugin_id}/auth/record")
async def post_start_auth_record(plugin_id: str, body: StartAuthRecordBody) -> dict[str, Any]:
    """Launch a clean browser session for the user to log in."""
    plugin = _plugin_or_404(plugin_id)
    start_url = body.start_url or plugin.target_url
    storage_state_path = _storage_state_path(plugin_id)
    sess = registry.create(
        start_url=start_url,
        storage_state_autosave_path=str(storage_state_path),
        auth_mode=True,
    )
    # Tag the session so finalize knows it is an auth session.
    sess._auth_plugin_id = plugin_id  # type: ignore[attr-defined]
    await _start_recorder_session(sess)
    return {
        "session_id": sess.session_id,
        "plugin_id": plugin_id,
        "start_url": start_url,
        "message": "Browser launched. Log in, navigate to the page workflows should start from, then close Chromium.",
    }


@router.post("/{plugin_id}/auth/finalize")
async def post_finalize_auth(plugin_id: str, body: FinalizeAuthBody) -> dict[str, Any]:
    """Stop auth recording, capture storage_state, persist auth.json."""
    _plugin_or_404(plugin_id)
    sess = registry.get(body.session_id)

    storage_state_path = _storage_state_path(plugin_id)
    final_url = ""

    # Capture one final storage_state when the browser is still alive. Auth sessions
    # also autosave while open, so a browser closed by the user can still finalize.
    if sess is not None:
        final_url = str(getattr(sess, "current_url", "") or "")
        try:
            if sess._context is not None and sess.browser_open:
                try:
                    page = sess._active_page_sync()
                    if page is not None:
                        sess._remember_page_url_sync(page)
                        final_url = str(getattr(sess, "current_url", "") or final_url)
                except Exception:
                    pass
                sess._context.storage_state(path=str(storage_state_path))
        except Exception as exc:
            if not storage_state_path.is_file():
                raise HTTPException(status_code=500, detail=f"Failed to capture storage state: {exc}") from exc

        await sess.stop()
        final_url = str(getattr(sess, "current_url", "") or final_url)

    if not storage_state_path.is_file():
        raise HTTPException(status_code=404, detail="Session not found or auth state was not captured.")

    reject_reason = _reject_reason_for_protected_url(final_url)
    if reject_reason:
        raise HTTPException(status_code=400, detail=reject_reason)

    updated = set_plugin_auth(
        plugin_id=plugin_id,
        session_id=body.session_id,
        storage_state_path=str(storage_state_path),
        protected_url=final_url,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Plugin not found after finalize.")

    return {
        "plugin_id": plugin_id,
        "session_id": body.session_id,
        "storage_state_saved": storage_state_path.is_file(),
        "plugin_status": updated.status,
        "protected_url": updated.protected_url,
    }


@router.post("/{plugin_id}/auth/re-record")
def post_re_record_auth(plugin_id: str) -> dict[str, Any]:
    """Reset plugin to needs_auth so the user can re-record login."""
    plugin = _plugin_or_404(plugin_id)
    # Archive existing auth.json.
    auth_path = _storage_state_path(plugin_id)
    if auth_path.is_file():
        ts = int(time.time())
        auth_path.rename(auth_path.parent / f"auth.{ts}.json")
    plugin.auth = None
    plugin.status = "needs_auth"
    plugin = save_plugin(plugin)
    return {"plugin_id": plugin_id, "status": plugin.status}


# ---------------------------------------------------------------------------
# Workflow recording
# ---------------------------------------------------------------------------

@router.post("/{plugin_id}/workflows/record")
async def post_start_workflow_record(plugin_id: str, body: StartWorkflowRecordBody) -> dict[str, Any]:
    """Launch a browser pre-loaded with the plugin's saved session for workflow recording."""
    plugin = _plugin_or_404(plugin_id)
    if plugin.status != "ready" or plugin.auth is None:
        raise HTTPException(
            status_code=400,
            detail="Plugin auth not recorded yet. Record login first.",
        )

    storage_state_path = Path(plugin.auth.storage_state_path)
    if not storage_state_path.is_file():
        raise HTTPException(
            status_code=400,
            detail="Auth storage state file missing. Re-record login.",
        )

    # Resolve {{variable}} placeholders in protected_url using provided url_variables.
    start_url = plugin.protected_url.strip()
    if not start_url:
        raise HTTPException(
            status_code=400,
            detail="Plugin auth is missing a protected URL. Re-record login and close Chromium on the page where workflows should start.",
        )
    if body.url_variables:
        var_pattern = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}")
        start_url = var_pattern.sub(
            lambda m: body.url_variables.get(m.group(1), m.group(0)),
            start_url,
        )
    # If unresolved template variables remain, fall back to target_url so the
    # browser opens at the login page — auth cookies will redirect automatically.
    if "{{" in start_url:
        start_url = plugin.target_url

    # Create session with storage_state_path — RecordingSession restores it when launching the context.
    sess = registry.create(
        start_url=start_url,
        storage_state_path=str(storage_state_path),
        capture_hover=body.capture_hover,
    )
    try:
        await _start_recorder_session(sess)
    except HTTPException:
        raise

    result = add_workflow(plugin_id, body.name, session_id=sess.session_id)
    if result is None:
        await sess.stop()
        registry.pop(sess.session_id)
        raise HTTPException(status_code=404, detail="Plugin not found.")
    _, wf = result

    return {
        "session_id": sess.session_id,
        "workflow_id": wf.id,
        "plugin_id": plugin_id,
        "message": "Browser launched with restored session. Record your workflow, then close it to finalize.",
    }


@router.post("/{plugin_id}/workflows/{workflow_id}/finalize")
async def post_finalize_workflow(plugin_id: str, workflow_id: str, body: FinalizeWorkflowBody) -> dict[str, Any]:
    """Finalize a user-closed workflow recording and mark workflow as recorded."""
    _plugin_or_404(plugin_id)
    sess = registry.get(body.session_id)
    if sess:
        if sess.browser_open:
            raise HTTPException(
                status_code=409,
                detail="Close Chromium before saving this workflow. The backend will not close recording browsers.",
            )
        await sess.stop()
        raw_events = sess.snapshot_events()
        registry.pop(body.session_id)
    else:
        from app.storage.session_events import read_session_events
        raw_events = read_session_events(body.session_id)

    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")

    workflow_exists = any(wf.id == workflow_id for wf in plugin.workflows)
    if not workflow_exists:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    if not raw_events:
        remove_workflow(plugin_id, workflow_id)
        raise HTTPException(
            status_code=400,
            detail="No workflow actions were recorded. Browser closed before any supported action was captured.",
        )

    for wf in plugin.workflows:
        if wf.id == workflow_id:
            wf.session_id = body.session_id
            wf.status = "recorded"
            break

    save_plugin(plugin)

    # Auto-classify unless the caller overrides.
    workflow_kind: str = body.force_workflow_kind or "workflow"
    if not body.force_workflow_kind:
        try:
            from app.recorder.session import classify_login_flow
            from app.models.events import RecordedEvent
            events = [RecordedEvent.model_validate(e) for e in raw_events]
            workflow_kind = classify_login_flow(events)
        except Exception:
            workflow_kind = "workflow"

    return {
        "plugin_id": plugin_id,
        "workflow_id": workflow_id,
        "status": "recorded",
        "session_id": body.session_id,
        "workflow_kind": workflow_kind,
    }


@router.delete("/{plugin_id}/workflows/{workflow_id}")
def delete_workflow_endpoint(plugin_id: str, workflow_id: str) -> dict[str, Any]:
    _plugin_or_404(plugin_id)
    updated = remove_workflow(plugin_id, workflow_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
    return {"deleted": True, "plugin_id": plugin_id, "workflow_id": workflow_id}


@router.patch("/{plugin_id}/workflows/{workflow_id}")
def patch_workflow_endpoint(plugin_id: str, workflow_id: str, body: UpdateWorkflowBody) -> dict[str, Any]:
    plugin = _plugin_or_404(plugin_id)
    updated_workflow = None
    for wf in plugin.workflows:
        if wf.id == workflow_id:
            if body.skill_id is not None:
                wf.skill_id = body.skill_id
                wf.status = "compiled"
            updated_workflow = wf
            break
    if updated_workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    save_plugin(plugin)
    return {
        "plugin_id": plugin_id,
        "workflow_id": workflow_id,
        "skill_id": updated_workflow.skill_id,
        "status": updated_workflow.status,
    }


# ---------------------------------------------------------------------------
# Plugin build (SSE)
# ---------------------------------------------------------------------------

async def _build_sse(plugin_id: str, version: str) -> AsyncIterator[bytes]:
    q: SimpleQueue[tuple[str, Any]] = SimpleQueue()

    def runner() -> None:
        try:
            from app.services.plugin_builder import build_plugin
            out = build_plugin(plugin_id, version=version, realtime_sink=lambda e: q.put(("log", e)))
            q.put(("ok", out))
        except Exception as exc:
            q.put(("fail", {"message": str(exc)}))

    asyncio.get_running_loop().run_in_executor(None, runner)

    while True:
        kind, data = await asyncio.to_thread(q.get)
        if kind == "log":
            yield _sse_line({"event": "log", "entry": data})
        elif kind == "ok":
            yield _sse_line({"event": "done", "result": data})
            return
        else:
            yield _sse_line({"event": "error", "message": data.get("message", "Build failed")})
            return


@router.post("/{plugin_id}/build/stream")
async def post_build_plugin_stream(plugin_id: str, body: BuildPluginBody) -> StreamingResponse:
    _plugin_or_404(plugin_id)
    return StreamingResponse(
        _build_sse(plugin_id, body.version),
        media_type="text/event-stream",
        headers=dict(_SSE_HEADERS),
    )


@router.post("/{plugin_id}/build")
def post_build_plugin(plugin_id: str, body: BuildPluginBody) -> dict[str, Any]:
    _plugin_or_404(plugin_id)
    from app.services.plugin_builder import build_plugin
    try:
        return build_plugin(plugin_id, version=body.version)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Compiled skill inspect
# ---------------------------------------------------------------------------

_COMPILED_SKILL_FILES = ("execution.json", "recovery.json", "input.json")


def _skill_dir(plugin: Plugin) -> Callable[[str], Path]:
    """Return a callable that resolves the on-disk directory for a skill slug."""
    if plugin.build is None:
        raise HTTPException(status_code=400, detail="Plugin has not been built yet.")

    bundle_root = Path(plugin.build.output_path)

    def _resolve(slug: str) -> Path:
        skill_dir = bundle_root / "skills" / slug
        if not skill_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Compiled skill '{slug}' not found.")
        return skill_dir

    return _resolve


@router.get("/{plugin_id}/skills/{skill_slug}/compiled")
def get_compiled_skill(plugin_id: str, skill_slug: str) -> dict[str, Any]:
    """Return compiled JSON files for a skill."""
    plugin = _plugin_or_404(plugin_id)
    resolve = _skill_dir(plugin)
    skill_dir = resolve(skill_slug)

    result: dict[str, Any] = {}
    for fname in _COMPILED_SKILL_FILES:
        fpath = skill_dir / fname
        if fpath.is_file():
            try:
                result[fname] = json.loads(fpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                result[fname] = None
        else:
            result[fname] = None

    return {"plugin_id": plugin_id, "skill_slug": skill_slug, "files": result}


class ExecuteSkillBody(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    headless: bool = Field(default=True)


@router.post("/{plugin_id}/skills/{skill_slug}/execute")
async def post_execute_skill(plugin_id: str, skill_slug: str, body: ExecuteSkillBody) -> dict[str, Any]:
    """Low-level dev tool: run a built skill without persisting results. Use /test/stream for the gated test flow."""
    plugin = _plugin_or_404(plugin_id)
    if plugin.build is None:
        raise HTTPException(status_code=400, detail="Plugin not built yet.")
    from app.services.plugin_executor import execute_skill
    try:
        result = await execute_skill(plugin, skill_slug, body.inputs, body.headless)
        return {"plugin_id": plugin_id, "skill_slug": skill_slug, **result}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class WorkflowTestBody(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    headless: bool = Field(default=False)  # author wants to watch by default


@router.post("/{plugin_id}/workflows/{workflow_id}/test/stream")
async def post_test_workflow_stream(plugin_id: str, workflow_id: str, body: WorkflowTestBody) -> StreamingResponse:
    """Run a built workflow end-to-end and persist the pass/fail result. Gate for Build Installer."""
    plugin = _plugin_or_404(plugin_id)
    if plugin.build is None:
        raise HTTPException(status_code=400, detail="Build the plugin first before testing.")

    wf = next((w for w in plugin.workflows if w.id == workflow_id), None)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    if not wf.skill_id:
        raise HTTPException(status_code=400, detail="Compile this workflow first.")
    if wf.edited_at and plugin.build.last_built_at and wf.edited_at > plugin.build.last_built_at:
        raise HTTPException(
            status_code=400,
            detail="Workflow was edited since the last build. Rebuild the plugin before retesting.",
        )

    from app.services.plugin_executor import execute_skill
    from app.storage.plugin_store import set_workflow_test_result, set_workflow_test_error

    async def events() -> AsyncIterator[bytes]:
        log_queue: asyncio.Queue[str] = asyncio.Queue()

        def log_sink(line: str) -> None:
            log_queue.put_nowait(line)

        yield _sse_line({"event": "log", "entry": {"message": f"Starting test for workflow '{wf.name}'..."}})

        task = asyncio.create_task(
            execute_skill(plugin, wf.slug, body.inputs, body.headless, log_sink=log_sink)
        )

        # Stream log lines while execution is in progress
        while not task.done():
            try:
                line = await asyncio.wait_for(log_queue.get(), timeout=0.1)
                yield _sse_line({"event": "log", "entry": {"message": line}})
            except asyncio.TimeoutError:
                continue

        # Drain any remaining log lines queued before the task completed
        while not log_queue.empty():
            yield _sse_line({"event": "log", "entry": {"message": log_queue.get_nowait()}})

        try:
            result = await task
            set_workflow_test_result(plugin_id, workflow_id, status="passed", inputs=dict(body.inputs))
            yield _sse_line({"event": "done", "result": result})
        except Exception as exc:
            err = str(exc)[:2000]
            set_workflow_test_error(plugin_id, workflow_id, err)
            yield _sse_line({"event": "error", "message": err})

    return StreamingResponse(events(), media_type="text/event-stream", headers=dict(_SSE_HEADERS))


@router.post("/{plugin_id}/build-installer/stream")
async def post_build_installer_stream(plugin_id: str) -> StreamingResponse:
    """Build a Windows installer EXE and stream progress via SSE."""
    plugin = _plugin_or_404(plugin_id)
    if plugin.build is None:
        raise HTTPException(
            status_code=400,
            detail="Plugin must be built first. Call /build/stream before building the installer.",
        )
    untested = [wf.name for wf in plugin.workflows if wf.last_test_status != "passed"]
    if untested:
        raise HTTPException(
            status_code=400,
            detail=f"All workflows must pass Test Plugin first. Untested or failing: {', '.join(untested)}",
        )
    from app.services.plugin_builder import _plugin_bundle_slug
    company_slug = _plugin_bundle_slug(plugin_id, plugin.name)

    q: SimpleQueue[tuple[str, Any]] = SimpleQueue()

    def runner() -> None:
        try:
            from app.services.installer_builder import build_installer
            result = build_installer(plugin_id, company_slug=company_slug, realtime_sink=lambda e: q.put(("log", e)))
            q.put(("ok", result))
        except Exception as exc:
            q.put(("fail", {"message": str(exc)}))

    asyncio.get_running_loop().run_in_executor(None, runner)

    async def events() -> AsyncIterator[bytes]:
        while True:
            kind, data = await asyncio.to_thread(q.get)
            if kind == "log":
                yield _sse_line({"event": "log", "entry": data})
            elif kind == "ok":
                yield _sse_line({"event": "done", "result": data})
                return
            else:
                yield _sse_line({"event": "error", "message": data.get("message", "Installer build failed")})
                return

    return StreamingResponse(events(), media_type="text/event-stream", headers=dict(_SSE_HEADERS))


@router.get("/{plugin_id}/installer/download")
def get_download_installer(plugin_id: str) -> StreamingResponse:
    """Download the compiled installer EXE."""
    plugin = _plugin_or_404(plugin_id)
    if plugin.installer is None:
        raise HTTPException(status_code=404, detail="Installer not built yet. Call build-installer/stream first.")
    p = Path(plugin.installer.installer_path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Installer file missing. Rebuild required.")
    headers = {"Content-Disposition": f'attachment; filename="{p.name}"'}
    return StreamingResponse(open(p, "rb"), media_type="application/octet-stream", headers=headers)  # noqa: SIM115


@router.get("/{plugin_id}/download")
def get_download_plugin(plugin_id: str) -> StreamingResponse:
    plugin = _plugin_or_404(plugin_id)
    if plugin.build is None:
        raise HTTPException(status_code=400, detail="Plugin not built yet.")
    from app.services.plugin_builder import zip_plugin
    try:
        filename, payload = zip_plugin(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(BytesIO(payload), media_type="application/zip", headers=headers)
