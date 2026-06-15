"""Build Studio Python backend — stdio JSON-RPC dispatcher.

Electron spawns this process and talks to it over stdin/stdout. The protocol is
newline-delimited JSON:

  request  (stdin) : {"id": "<uuid>", "type": "<command>", "payload": {...}}
  result   (stdout): {"id": "<uuid>", "type": "result", "result": {...}}
  error    (stdout): {"id": "<uuid>", "type": "error", "code": "...", "message": "..."}
  event    (stdout): {"type": "event", "id": "<uuid>"|null, ...}   (streaming progress)

The shared ``app/*`` package is used unchanged as a library; compile-time LLM
calls are redirected to the cloud proxy by swapping the router singleton.
Recording runs on a persistent asyncio loop in a background thread because the
Playwright recorder is async and long-lived.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import traceback
import urllib.error
import re
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from typing import Any, Callable

# Make this `python` dir importable (for the local `services` package and the
# bundled `conxa_compile` pipeline), regardless of launch CWD. The shared
# `conxa_core` package is installed as a dependency, not imported by path.
_PY_DIR = os.path.abspath(os.path.dirname(__file__))
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

from services import bootstrap as _bootstrap_pkg  # noqa: E402

# Point Playwright at the managed Chromium build before the recorder is imported
# or used. In frozen builds the browser lives in ~/.conxa-build-studio/deps/chromium;
# without this, launches on a non-bootstrap startup fail with "Executable doesn't exist".
_bootstrap_pkg.configure_playwright_browsers_path()

# Pre-import the recorder and plugin store at startup (main thread, before serve()
# starts blocking on stdin). Importing these lazily in a dispatch thread causes a
# deadlock: two simultaneous record clicks hit Python's per-module import lock while
# conxa_core.config.Settings() tries to read the repo .env from a piped-stdin context.
from conxa_compile.recorder.session import registry as _recorder_registry  # noqa: E402
from conxa_core.storage.plugin_store import get_plugin as _get_plugin  # noqa: E402

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _validate_release_version(value: Any) -> str:
    version = str(value or "").strip()
    if not _SEMVER_RE.fullmatch(version):
        raise _CommandError("invalid_release_version", "Installer version must look like 1.2.3 or 1.2.3-beta.1.")
    return version


def _validate_release_notes(value: Any) -> str:
    notes = str(value or "").strip()
    if not notes:
        raise _CommandError("invalid_release_notes", "Release message is required.")
    if len(notes) > 2000:
        raise _CommandError("invalid_release_notes", "Release message must be 2000 characters or fewer.")
    return notes


def _is_rejected_protected_url(url: str) -> bool:
    value = str(url or "").strip()
    if not value:
        return True
    parsed = urlparse(value)
    if parsed.scheme in {"", "about", "data", "blob", "file"}:
        return True
    haystack = " ".join([parsed.path, parsed.query, parsed.fragment]).lower()
    return any(token in haystack for token in ("login", "signin", "sign-in", "auth", "callback", "oauth"))


def _runtime_result_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _plugin_company_slug(plugin: Any) -> str:
    build = getattr(plugin, "build", None)
    output_path = str(getattr(build, "output_path", "") or "")
    if output_path:
        plugin_json = Path(output_path) / "plugin.json"
        if plugin_json.is_file():
            try:
                payload = json.loads(plugin_json.read_text(encoding="utf-8"))
                slug = str(payload.get("slug") or "").strip()
                if slug:
                    return slug
            except Exception:
                pass
        folder = Path(output_path).name
        if folder.endswith("-plugin"):
            return folder[:-7]
        if folder:
            return folder
    return str(getattr(plugin, "slug", "") or getattr(plugin, "id", "")).strip()


def _stage_runtime_auth(plugin: Any, company: str, data_dir: Path) -> None:
    auth = getattr(plugin, "auth", None)
    storage_state_path = Path(str(getattr(auth, "storage_state_path", "") or ""))
    if not storage_state_path.is_file():
        return

    import shutil
    from datetime import datetime, timezone

    sessions_dir = data_dir / "cache" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(storage_state_path, sessions_dir / f"{company}_raw_state.json")

    protected_url = str(getattr(plugin, "protected_url", "") or getattr(plugin, "target_url", "") or "").strip()
    if protected_url:
        meta_path = sessions_dir / f"{company}_auth_meta.json"
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        meta.update(
            {
                "protected_url": protected_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# --- stdout protocol ---------------------------------------------------------

_stdout_lock = threading.Lock()


def _write(obj: dict[str, Any]) -> None:
    with _stdout_lock:
        sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
        sys.stdout.flush()


def _emit_event(req_id: str | None, **fields: Any) -> None:
    _write({"type": "event", "id": req_id, **fields})


def _event_sink(req_id: str | None) -> Callable[[dict[str, Any]], None]:
    def sink(entry: dict[str, Any]) -> None:
        _emit_event(req_id, **entry)
    return sink


# --- background asyncio loop for the recorder --------------------------------

class _Loop:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()


# --- the backend -------------------------------------------------------------

class Backend:
    _MAX_UNDO = 50

    def __init__(self) -> None:
        self._loop = _Loop()
        self._active_recording: str | None = None
        self._rec_lock = threading.Lock()
        self._auth = None  # AuthService, lazily built once configured
        self._cloud_api = os.environ.get("CONXA_CLOUD_API", "http://127.0.0.1:8000")
        self._undo_stacks: dict[str, list] = {}
        self._redo_stacks: dict[str, list] = {}

    # -- undo / redo helpers -------------------------------------------------

    def _push_undo(self, skill_id: str, snapshot: dict[str, Any]) -> None:
        """Push a pre-mutation snapshot and clear redo. Caller must pass a safe copy."""
        stack = self._undo_stacks.setdefault(skill_id, [])
        stack.append(snapshot)
        if len(stack) > self._MAX_UNDO:
            stack.pop(0)
        self._redo_stacks[skill_id] = []

    def _history_flags(self, skill_id: str) -> dict[str, bool]:
        return {
            "can_undo": len(self._undo_stacks.get(skill_id, [])) > 0,
            "can_redo": len(self._redo_stacks.get(skill_id, [])) > 0,
        }

    # -- lazy auth wiring ----------------------------------------------------

    def _auth_service(self):
        if self._auth is None:
            from services.auth_service import AuthService

            self._auth = AuthService(
                clerk_domain=os.environ.get("CONXA_CLERK_DOMAIN", ""),
                client_id=os.environ.get("CONXA_CLERK_CLIENT_ID", ""),
                client_secret=os.environ.get("CONXA_CLERK_CLIENT_SECRET", ""),
                cloud_api=self._cloud_api,
            )
        return self._auth

    def _install_proxy_router(
        self,
        sink: Callable[[dict[str, Any]], None] | None = None,
        *,
        usage_class: str = "compile",
    ) -> None:
        """Redirect every compiler LLM call to the metered cloud proxy."""
        from services.llm_proxy_client import LLMProxyClient
        from conxa_core import llm as core_llm

        def _on_api_call(info: dict[str, Any]) -> None:
            if sink is not None:
                sink({"phase": "api_call", **info})

        client = LLMProxyClient(
            self._cloud_api,
            token_provider=lambda: self._auth_service().get_token(),
            client_header=os.environ.get("CONXA_PROXY_CLIENT", "build-studio"),
            usage_class=usage_class,
            on_api_call=_on_api_call,
        )
        core_llm.set_router(client)

    def _cloud_api_base(self) -> str:
        return (self._cloud_api or "https://apis.conxa.in").rstrip("/")

    def _auto_publish_enabled(self) -> bool:
        if os.environ.get("CONXA_DISABLE_AUTO_PUBLISH") == "1":
            return False
        parsed = urlparse(self._cloud_api_base())
        return parsed.hostname not in {"127.0.0.1", "localhost", ""}

    def _cloud_token(self) -> str:
        try:
            token = self._auth_service().get_token()
        except Exception as exc:
            raise _CommandError(
                "cloud_auth_required",
                "Sign in to Conxa Build Studio before building a cloud-connected installer.",
            ) from exc
        if not token:
            raise _CommandError(
                "cloud_auth_required",
                "Sign in to Conxa Build Studio before building a cloud-connected installer.",
            )
        return token

    def _cloud_json(self, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
        import urllib.request

        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self._cloud_api_base()}{path}", data=data, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self._cloud_token()}")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                detail = str(error_payload.get("detail") or "")
            except Exception:
                detail = ""
            if detail:
                raise _CommandError(detail, self._entitlement_error_message(detail)) from exc
            raise _CommandError("entitlements_unavailable", f"Cloud entitlement check failed: HTTP {exc.code}") from exc
        except Exception as exc:
            raise _CommandError("entitlements_unavailable", f"Cloud entitlement service unavailable: {exc}") from exc
        return payload if isinstance(payload, dict) else {}

    def _entitlement_error_message(self, code: str) -> str:
        messages = {
            "compile_credit_limit_exceeded": "Monthly compile credits are exhausted for this workspace.",
            "human_edit_pool_exceeded": "Monthly Human Edit pool is exhausted for this workspace.",
            "installer_limit_exceeded": "Installer slot limit reached for this workspace.",
            "seat_limit_exceeded": "Seat limit reached for this workspace.",
            "entitlements_unavailable": "Cloud entitlements are unavailable, so quota-gated actions are blocked.",
            "invalid_usage_class": "Invalid LLM usage class.",
        }
        return messages.get(code, code)

    def _compile_reservation_id(self, rid: str, plugin_id: str, workflow_id: str, session_id: str) -> str:
        raw = f"cmp_{rid}_{plugin_id}_{workflow_id}_{session_id}"
        return re.sub(r"[^A-Za-z0-9_.:-]+", "_", raw)[:240]

    def _reserve_compile_credit(
        self,
        *,
        reservation_id: str,
        plugin_id: str,
        workflow_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        return self._cloud_json(
            "/api/v1/usage/compile/reserve",
            method="POST",
            body={
                "reservation_id": reservation_id,
                "plugin_id": plugin_id,
                "workflow_id": workflow_id,
                "session_id": session_id,
            },
        )

    def _commit_compile_credit(self, reservation_id: str) -> dict[str, Any]:
        return self._cloud_json(
            "/api/v1/usage/compile/commit",
            method="POST",
            body={"reservation_id": reservation_id},
        )

    def _release_compile_credit(self, reservation_id: str) -> None:
        try:
            self._cloud_json(
                "/api/v1/usage/compile/release",
                method="POST",
                body={"reservation_id": reservation_id},
            )
        except Exception:
            pass

    def _publish_skill_pack_for_installer(
        self,
        *,
        company_slug: str,
        plugin: Any,
        version: str,
        release_notes: str,
        sink: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Publish the built skill pack and rewrite local pack.json with cloud tracking."""
        from conxa_core.config import settings as _settings
        import base64
        import urllib.request

        if not self._auto_publish_enabled():
            sink({"kind": "installer_build", "message": "Cloud publish skipped for local API base"})
            return {}

        data_dir = Path(_settings.data_dir)
        packs_dir = data_dir / "skill-packs" / company_slug
        pack_path = packs_dir / "pack.json"
        if not pack_path.is_file():
            raise _CommandError("pack_not_built", f"No built skill pack for {company_slug}")

        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        pack["skill_pack_version"] = version
        pack["release_notes"] = release_notes
        pack_path.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")

        files: list[dict[str, str]] = []
        for fpath in sorted(packs_dir.rglob("*")):
            if fpath.is_file():
                files.append(
                    {
                        "path": fpath.relative_to(packs_dir).as_posix(),
                        "content_base64": base64.b64encode(fpath.read_bytes()).decode("ascii"),
                    }
                )

        cloud_api = self._cloud_api_base()
        body = json.dumps(
            {
                "slug": company_slug,
                "display_name": str(getattr(plugin, "name", "") or company_slug),
                "target_url": str(getattr(plugin, "target_url", "") or pack.get("target_url") or ""),
                "protected_url": str(getattr(plugin, "protected_url", "") or pack.get("protected_url") or ""),
                "skill_pack_version": version,
                "release_notes": release_notes,
                "skills": list(pack.get("skills") or []),
                "files": files,
            }
        ).encode("utf-8")
        req = urllib.request.Request(f"{cloud_api}/api/v1/plugins/publish", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self._cloud_token()}")
        sink({"kind": "installer_build", "message": f"Publishing {company_slug} skill pack to Conxa Cloud..."})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                published = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise _CommandError("cloud_publish_failed", f"Cloud publish failed: {exc}") from exc

        tracking = dict(published.get("tracking") or {})
        tracking["tracking_url"] = f"{cloud_api}/api/tracking/{company_slug}/events"
        if not tracking.get("tracking_token"):
            raise _CommandError("cloud_publish_failed", "Cloud publish did not return a tracking token.")

        sync_token = str(published.get("sync_token") or "")
        if not sync_token:
            raise _CommandError(
                "cloud_publish_failed",
                "Cloud publish did not return a sync_token. "
                "The installer cannot be built — the runtime needs this token to pull skill-pack updates. "
                "Ensure the cloud backend is up-to-date.",
            )

        pack["tracking"] = tracking
        pack["sync_endpoint"] = f"{cloud_api}/api/v1/skill-packs/{company_slug}/delta"
        pack["sync_token"] = sync_token
        pack["published"] = {
            "cloud_api": cloud_api,
            "workspace_id": str(published.get("workspace_id") or ""),
            "published_at": published.get("published_at"),
        }
        pack_path.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
        workspace_id = str(published.get("workspace_id") or "")
        sink(
            {
                "kind": "installer_build",
                "message": (
                    "Cloud tokens embedded in pack.json "
                    f"(workspace {workspace_id or 'unknown'}, sync_token present, "
                    f"tracking_token present, url {tracking['tracking_url']})"
                ),
            }
        )
        return {
            "cloud_api": cloud_api,
            "workspace_id": workspace_id,
            "tracking_url": tracking["tracking_url"],
            "tracking_token_present": True,
            "sync_token_present": True,
            "sync_endpoint": pack["sync_endpoint"],
        }

    def _upload_installer_for_download(
        self,
        *,
        company_slug: str,
        result: dict[str, Any],
        release_notes: str,
        sink: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        import urllib.request

        if not self._auto_publish_enabled():
            return result

        installer_path = Path(str(result.get("installer_path") or ""))
        if not installer_path.is_file():
            raise _CommandError("installer_upload_failed", f"Installer not found: {installer_path}")

        cloud_api = self._cloud_api_base()
        params = urlencode(
            {
                "filename": str(result.get("filename") or installer_path.name),
                "version": str(result.get("version") or "0.0.0"),
                "release_notes": release_notes,
            }
        )
        url = f"{cloud_api}/api/v1/plugins/{quote(company_slug)}/installer/upload?{params}"
        req = urllib.request.Request(url, data=installer_path.read_bytes(), method="POST")
        req.add_header("Content-Type", "application/octet-stream")
        req.add_header("Authorization", f"Bearer {self._cloud_token()}")
        sink({"kind": "installer_build", "message": "Uploading installer to Conxa Cloud..."})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                uploaded = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                detail = str(error_payload.get("detail") or "")
            except Exception:
                detail = ""
            if detail in {"installer_limit_exceeded", "entitlements_unavailable"}:
                raise _CommandError(detail, self._entitlement_error_message(detail)) from exc
            if exc.code == 409:
                raise _CommandError(
                    "installer_version_exists",
                    f"Installer version {result.get('version') or ''} already exists in Conxa Cloud.",
                ) from exc
            if exc.code == 413:
                result = dict(result)
                result["cloud_upload_error"] = "installer_upload_too_large"
                sink(
                    {
                        "kind": "installer_build",
                        "message": "Installer upload skipped: cloud rejected the file as too large. The local installer still contains cloud tracking.",
                        "warning": True,
                    }
                )
                return result
            raise _CommandError("installer_upload_failed", f"Installer upload failed: {exc}") from exc
        except Exception as exc:
            raise _CommandError("installer_upload_failed", f"Installer upload failed: {exc}") from exc
        result = dict(result)
        result["cloud_download_url"] = f"{cloud_api}{uploaded.get('download_url', '')}"
        if uploaded.get("version_download_url"):
            result["cloud_version_download_url"] = f"{cloud_api}{uploaded.get('version_download_url', '')}"
        result["cloud_sha256"] = uploaded.get("sha256", "")
        sink({"kind": "installer_build", "message": "Installer uploaded to Conxa Cloud"})
        return result

    # -- command handlers ----------------------------------------------------

    def cmd_ping(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        return {"ok": True, "pid": os.getpid()}

    def cmd_deps_status(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        """Fast offline check — returns which deps are already present."""
        return _bootstrap_pkg.check_status()

    def cmd_deps_check(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        """Fetch the cloud manifest and return which deps are outdated.

        Pass {"force": true} to bypass the 24 h TTL cache.
        Returns {"outdated": [{"dep": str, "installed": str|None, "available": str}]}
        """
        force = bool(payload.get("force", False))
        outdated = _bootstrap_pkg.check_for_updates(self._cloud_api, force=force)
        return {"outdated": outdated}

    def cmd_deps_apply(self, _payload: dict[str, Any], rid: str) -> dict[str, Any]:
        """Apply all pending dependency updates.

        Downloads, verifies, and atomically installs each outdated dep.
        Streams progress events. Returns {"ok": true} on success.
        """
        return _bootstrap_pkg.ensure_all(self._cloud_api, on_event=_event_sink(rid))

    def cmd_bootstrap(self, _payload: dict[str, Any], rid: str) -> dict[str, Any]:
        return _bootstrap_pkg.ensure_all(self._cloud_api, on_event=_event_sink(rid))

    def cmd_login(self, _payload: dict[str, Any], rid: str) -> dict[str, Any]:
        return {"identity": self._auth_service().login(on_event=_event_sink(rid))}

    def cmd_logout(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        self._auth_service().logout()
        return {"ok": True}

    def cmd_whoami(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        return {"identity": self._auth_service().current_identity()}

    def cmd_start_recording(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import re
        from pathlib import Path
        from conxa_core.config import settings as _settings

        with self._rec_lock:
            if self._active_recording is not None:
                raise _CommandError("recording_in_progress", "A recording is already active.")

            plugin_id_raw = payload.get("plugin_id")
            plugin_id = _safe_id(plugin_id_raw, "plugin_id") if plugin_id_raw else ""
            workflow_name = payload.get("workflow_name")

            if plugin_id:
                plugin = _get_plugin(plugin_id)
                if not plugin:
                    raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
                auth_mode = (workflow_name == "__auth__")
                plugin_dir = Path(_settings.data_dir) / "plugins" / plugin_id
                auth_state_path = str(plugin_dir / "auth" / "auth.json")
                storage_state_path = auth_state_path
                storage_state_autosave = str(plugin_dir / "auth" / "auth.json") if auth_mode else ""
                if auth_mode:
                    start_url = str(plugin.target_url or "about:blank")
                else:
                    workflow_name = str(workflow_name or "").strip()
                    if not workflow_name:
                        raise _CommandError("invalid_input", "workflow_name is required")
                    if plugin.status != "ready" or plugin.auth is None:
                        raise _CommandError("auth_required", "Record auth before creating workflows.")
                    storage_state_path = str(plugin.auth.storage_state_path or auth_state_path)
                    if not Path(storage_state_path).is_file():
                        raise _CommandError("auth_required", "Saved auth session is missing. Re-record auth first.")
                    start_url = str((plugin.protected_url or plugin.target_url or "about:blank")).strip()
                    url_variables = payload.get("url_variables")
                    if isinstance(url_variables, dict) and url_variables:
                        pattern = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}")
                        start_url = pattern.sub(
                            lambda m: str(url_variables.get(m.group(1)) or m.group(0)),
                            start_url,
                        )
            else:
                start_url = str(payload.get("start_url") or "about:blank")
                auth_mode = bool(payload.get("auth_mode"))
                storage_state_path = str(payload.get("storage_state_path") or "")
                storage_state_autosave = str(payload.get("storage_state_autosave_path") or "")

            sess = _recorder_registry.create(
                start_url=start_url,
                storage_state_path=storage_state_path,
                storage_state_autosave_path=storage_state_autosave,
                auth_mode=auth_mode,
                capture_hover=bool(payload.get("capture_hover")),
            )
            try:
                self._loop.run(sess.start())
            except RuntimeError as exc:
                _recorder_registry.pop(sess.session_id)
                raise _CommandError("recorder_launch_failed", str(exc)) from exc
            result = {"session_id": sess.session_id, "start_url": start_url}
            if plugin_id and not auth_mode:
                from conxa_core.storage.plugin_store import add_workflow

                added = add_workflow(plugin_id, str(workflow_name), sess.session_id)
                if added is None:
                    self._loop.run(sess.stop())
                    _recorder_registry.pop(sess.session_id)
                    raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
                _plugin, workflow = added
                result["workflow_id"] = workflow.id
            self._active_recording = sess.session_id
            return result

    def cmd_stop_recording(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        registry = _recorder_registry

        session_id = _safe_id(payload.get("session_id"), "session_id")
        sess = registry.get(session_id)
        if sess is None:
            raise _CommandError("session_not_found", f"No session {session_id}")
        plugin_id = str(payload.get("plugin_id") or "").strip()
        auth_mode = bool(payload.get("auth_mode"))
        storage_state_path = ""
        final_url = ""
        storage_state_saved = False
        if auth_mode:
            if not plugin_id:
                raise _CommandError("invalid_input", "plugin_id is required")
            plugin_id = _safe_id(plugin_id, "plugin_id")
            plugin = _get_plugin(plugin_id)
            if plugin is None:
                raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")

            from conxa_core.config import settings as _settings

            storage_state_path = str(Path(_settings.data_dir) / "plugins" / plugin_id / "auth" / "auth.json")
            try:
                page = getattr(sess, "_active_page_sync", lambda: None)()
                if page is not None:
                    final_url = str(getattr(page, "url", "") or "")
                    remember = getattr(sess, "_remember_page_url_sync", None)
                    if callable(remember):
                        remember(page)
            except Exception:
                final_url = ""
            if not final_url:
                final_url = str(getattr(sess, "current_url", "") or "")
            try:
                context = getattr(sess, "_context", None)
                if context is not None:
                    path = Path(storage_state_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(path))
            except Exception as exc:
                if not Path(storage_state_path).is_file():
                    raise _CommandError("auth_capture_failed", f"Failed to save auth session: {exc}") from exc
        events = sess.snapshot_events()
        self._loop.run(sess.stop())
        with self._rec_lock:
            if self._active_recording == session_id:
                self._active_recording = None
        if auth_mode:
            from conxa_core.storage.plugin_store import set_plugin_auth

            storage_state_saved = Path(storage_state_path).is_file()
            if not storage_state_saved:
                raise _CommandError("auth_capture_failed", "Auth browser closed before a session could be saved.")
            protected_url = final_url if not _is_rejected_protected_url(final_url) else None
            updated = set_plugin_auth(plugin_id, session_id, storage_state_path, protected_url=protected_url)
            if updated is None:
                raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
            return {
                "session_id": session_id,
                "event_count": len(events),
                "plugin_status": updated.status,
                "storage_state_saved": storage_state_saved,
                "protected_url": updated.protected_url,
            }
        workflow_id = str(payload.get("workflow_id") or "").strip()
        if plugin_id and workflow_id:
            from conxa_core.storage.plugin_store import remove_workflow

            plugin_id = _safe_id(plugin_id, "plugin_id")
            workflow_id = _safe_id(workflow_id, "workflow_id")
            if len(events) == 0:
                remove_workflow(plugin_id, workflow_id)
                raise _CommandError("empty_recording", "No workflow actions were recorded.")
            return {
                "session_id": session_id,
                "event_count": len(events),
                "workflow_id": workflow_id,
                "status": "recorded",
                "workflow_kind": "workflow",
            }
        return {"session_id": session_id, "event_count": len(events)}

    def cmd_run_pipeline(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_compile.pipeline.run import run_pipeline
        from conxa_core.storage.session_events import read_session_events
        registry = _recorder_registry

        session_id = _safe_id(payload.get("session_id"), "session_id")
        sess = registry.get(session_id)
        raw = sess.snapshot_events() if sess else read_session_events(session_id)
        normalized = run_pipeline(raw)
        return {"session_id": session_id, "event_count": len(normalized)}

    def cmd_compile(self, payload: dict[str, Any], rid: str) -> dict[str, Any]:
        import time as _time
        from conxa_compile.compiler.build import compile_skill_package
        from conxa_compile.pipeline.run import run_pipeline
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_core.storage.plugin_store import get_plugin, save_plugin
        from conxa_core.storage.session_events import read_session_events
        from services.llm_proxy_client import CloudUnreachable, EntitlementBlocked, QuotaExceeded
        registry = _recorder_registry

        session_id = _safe_id(payload.get("session_id"), "session_id")
        plugin_id = str(payload.get("plugin_id") or "").strip()
        plugin = None
        workflow = None
        if plugin_id:
            plugin_id = _safe_id(plugin_id, "plugin_id")
            plugin = get_plugin(plugin_id)
            if plugin is None:
                raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
            workflow = next((wf for wf in plugin.workflows if wf.session_id == session_id), None)
            if workflow is None:
                raise _CommandError("workflow_not_found", f"No workflow recorded for session {session_id}")

        title = str(payload.get("skill_title") or "").strip()
        if not title and workflow is not None:
            title = workflow.name.strip()
        if not title:
            raise _CommandError("invalid_input", "skill_title is required")

        is_recompile = bool(workflow and workflow.skill_id) or str(payload.get("mode") or "").strip() == "recompile"
        usage_class = "human_edit" if is_recompile else "compile"
        reservation_id: str | None = None
        reservation_committed = False

        sink = _event_sink(rid)

        def _log(message: str, level: str = "info") -> None:
            sink({"phase": "compile_log", "message": message, "level": level, "ts": _time.time()})

        if not is_recompile:
            workflow_id = str(getattr(workflow, "id", "") or "")
            reservation_id = self._compile_reservation_id(rid, plugin_id, workflow_id, session_id)
            _log("Reserving one compile credit...")
            reserve = self._reserve_compile_credit(
                reservation_id=reservation_id,
                plugin_id=plugin_id,
                workflow_id=workflow_id,
                session_id=session_id,
            )
            sink({"phase": "quota", "meter": "compile_credits", "status": "reserved", **reserve})
        else:
            _log("Recompile selected: LLM work will use the Human Edit pool.")

        sink({"phase": "pipeline_start"})
        sink({"phase": "compile_step", "step": "normalize", "status": "running"})
        _log("Loading session events…")

        try:
            sess = registry.get(session_id)
            if sess is not None:
                # Frame extraction runs in the recorder thread after stop() and writes
                # frames to events.jsonl on disk — it never updates the in-memory
                # _materialized list. Wait for the thread to finish so the on-disk
                # events.jsonl is complete before we read it.
                thread = getattr(sess, '_thread', None)
                if thread is not None and thread.is_alive():
                    _log("Waiting for post-recording frame extraction to complete…")
                    thread.join(timeout=120)
                    if thread.is_alive():
                        _log("Frame extraction thread still running after 120 s — compiling without frames.", level="warn")
            raw = read_session_events(session_id)
            if sess is not None:
                errs = [e for e in (getattr(sess, 'binding_errors', None) or []) if 'frame_extraction' in e]
                for e in errs:
                    _log(f"Warning: {e}", level="warn")
        except Exception:
            if reservation_id and not reservation_committed:
                self._release_compile_credit(reservation_id)
            raise
        if not raw:
            if reservation_id and not reservation_committed:
                self._release_compile_credit(reservation_id)
            raise _CommandError("no_events", "No recorded events for this session.")

        if reservation_id:
            _log("Committing compile credit before LLM-assisted compiler work...")
            try:
                commit = self._commit_compile_credit(reservation_id)
                reservation_committed = True
                sink({"phase": "quota", "meter": "compile_credits", "status": "committed", **commit})
            except Exception:
                self._release_compile_credit(reservation_id)
                raise

        self._install_proxy_router(sink=sink, usage_class=usage_class)
        _log(f"Running normalization pipeline on {len(raw)} events…")
        try:
            normalized = run_pipeline(raw)
        except (CloudUnreachable, EntitlementBlocked, QuotaExceeded) as exc:
            _log(str(exc), level="error")
            sink({"phase": "compile_error", "message": str(exc), "failed_step": "normalize"})
            if isinstance(exc, EntitlementBlocked):
                raise _CommandError(exc.code, self._entitlement_error_message(exc.code)) from exc
            if isinstance(exc, QuotaExceeded):
                raise _CommandError("quota_exceeded", str(exc)) from exc
            raise _CommandError("cloud_unreachable", str(exc)) from exc
        except Exception as exc:
            _log(str(exc), level="error")
            sink({"phase": "compile_error", "message": str(exc), "failed_step": "normalize"})
            raise

        _log(f"Pipeline produced {len(normalized)} normalized events")
        sink({"phase": "pipeline_done", "event_count": len(normalized)})
        for step in ("normalize", "dedupe", "enrich"):
            sink({"phase": "compile_step", "step": step, "status": "done"})
        sink({"phase": "compile_step", "step": "selectors", "status": "running"})

        skill_id = f"skill_{session_id}"
        existing = read_skill(skill_id)
        version = int((existing.get("meta") or {}).get("version") or 0) + 1 if existing else 1

        _log("Starting compiler — generating selectors, assertions, recovery blocks…")
        sink({"phase": "compiler_start"})
        try:
            package = compile_skill_package(
                normalized,
                skill_id=skill_id,
                source_session_id=session_id,
                title=title,
                version=version,
            )
        except (CloudUnreachable, EntitlementBlocked, QuotaExceeded) as exc:
            _log(str(exc), level="error")
            sink({"phase": "compile_error", "message": str(exc), "failed_step": "selectors"})
            if isinstance(exc, EntitlementBlocked):
                raise _CommandError(exc.code, self._entitlement_error_message(exc.code)) from exc
            if isinstance(exc, QuotaExceeded):
                raise _CommandError("quota_exceeded", str(exc)) from exc
            raise _CommandError("cloud_unreachable", str(exc)) from exc
        except Exception as exc:
            _log(str(exc), level="error")
            sink({"phase": "compile_error", "message": str(exc), "failed_step": "selectors"})
            raise

        write_skill(skill_id, package.model_dump(mode="json"))
        step_count = len(package.skills[0].steps)
        sink({"phase": "compiler_done", "step_count": step_count})
        for step in ("selectors", "assertions", "recovery", "package"):
            sink({"phase": "compile_step", "step": step, "status": "done"})
            _log(f"Completed: {step}")
        if plugin is not None and workflow is not None:
            workflow.skill_id = skill_id
            workflow.status = "compiled"
            save_plugin(plugin)
        _log(f"Skill packaged: {skill_id} (version {version}, {step_count} steps)")
        sink({"phase": "compile_done", "skill_id": skill_id, "version": version, "step_count": step_count})
        return {"skill_id": skill_id, "version": version, "step_count": step_count}

    def cmd_create_plugin(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.plugin_store import create_plugin as _create

        name = str(payload.get("name") or "").strip()
        if not name:
            raise _CommandError("invalid_input", "name is required")
        target_url = str(payload.get("target_url") or "about:blank").strip()
        plugin = _create(name=name, target_url=target_url)
        return {"plugin": plugin.model_dump(mode="json")}

    def cmd_list_plugins(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.plugin_store import list_plugins as _list

        plugins = _list()
        return {"plugins": [p.model_dump(mode="json") for p in plugins]}

    def cmd_get_plugin(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.plugin_store import get_plugin
        from conxa_core.storage.json_store import read_skill

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        plugin = get_plugin(plugin_id)
        if plugin is None:
            raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
        data = plugin.model_dump(mode="json")
        for wf_data, wf in zip(data["workflows"], plugin.workflows):
            step_count = 0
            if wf.skill_id:
                try:
                    skill = read_skill(wf.skill_id)
                    if skill:
                        step_count = len((skill.get("skills") or [{}])[0].get("steps") or [])
                except Exception:
                    pass
            wf_data["step_count"] = step_count
        return {"plugin": data}

    def cmd_list_workflows(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.plugin_store import get_plugin

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        plugin = get_plugin(plugin_id)
        if plugin is None:
            raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
        return {
            "plugin_id": plugin_id,
            "workflows": [wf.model_dump(mode="json") for wf in plugin.workflows],
        }

    def cmd_build_plugin(self, payload: dict[str, Any], rid: str) -> dict[str, Any]:
        from conxa_compile.plugin_builder import build_plugin

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        version = str(payload.get("version") or "0.1.0")
        return build_plugin(plugin_id, version=version, realtime_sink=_event_sink(rid))

    def cmd_build_installer(self, payload: dict[str, Any], rid: str) -> dict[str, Any]:
        from pathlib import Path
        from services.installer_builder import build_installer

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        plugin = _get_plugin(plugin_id)
        if plugin is None:
            raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
        company_slug = str(payload.get("company_slug") or "").strip()
        if company_slug:
            company_slug = _safe_id(company_slug, "company_slug")
        else:
            company_slug = _plugin_company_slug(plugin)
            if not company_slug:
                raise _CommandError("invalid_plugin", "Built plugin is missing a runtime company slug.")
        version = _validate_release_version(payload.get("version"))
        release_notes = _validate_release_notes(payload.get("release_notes"))

        # Invariant: auth.json must never enter the installer input. Captured
        # auth lives under the plugin state dir, but the installer stages only
        # the built skill pack.
        from conxa_core.config import settings as _settings
        skill_pack_dir = Path(_settings.data_dir) / "skill-packs" / company_slug
        if skill_pack_dir.exists() and any(skill_pack_dir.rglob("auth.json")):
            raise _CommandError(
                "auth_file_in_build_input",
                "Refusing to build: auth.json found under the built skill pack.",
            )

        logo_path = str(payload.get("logo_path") or "").strip() or None
        sink = _event_sink(rid)
        publish_info = self._publish_skill_pack_for_installer(
            company_slug=company_slug,
            plugin=plugin,
            version=version,
            release_notes=release_notes,
            sink=sink,
        )
        result = build_installer(
            plugin_id,
            company_slug=company_slug,
            logo_path=logo_path,
            version=version,
            release_notes=release_notes,
            realtime_sink=sink,
        )
        if publish_info:
            result = dict(result)
            result["cloud_workspace_id"] = publish_info.get("workspace_id", "")
            result["cloud_tracking_url"] = publish_info.get("tracking_url", "")
            result["cloud_tracking_token_present"] = bool(publish_info.get("tracking_token_present"))
            result["cloud_sync_endpoint"] = publish_info.get("sync_endpoint", "")
            result["installed_runtime_path"] = (
                r"C:\Program Files\Conxa\runtime\runtime.exe"
                if sys.platform == "win32"
                else str(Path.home() / ".conxa" / "runtime" / "runtime")
            )
            sink(
                {
                    "kind": "installer_build",
                    "message": (
                        f"Post-install check: restart Claude, confirm Conxa MCP tools are available, "
                        f"run list_skills, then execute a skill. Runtime path: {result['installed_runtime_path']}"
                    ),
                }
            )
        return self._upload_installer_for_download(
            company_slug=company_slug,
            result=result,
            release_notes=release_notes,
            sink=sink,
        )

    def cmd_test_workflow(self, payload: dict[str, Any], rid: str) -> dict[str, Any]:
        """Run a built workflow end-to-end against the local Conxa runtime.

        Validates the workflow is built and compiled, stages the built skill pack
        and captured auth session into a local test runtime, then calls the
        shared MCP runtime's ``execute_skill`` tool over stdio.
        """
        from conxa_compile.conxa_runtime import (
            RuntimeToolError,
            call_runtime_tool,
            ensure_chromium_installed,
            resolve_runtime_dir,
            sync_skill_pack,
        )
        from conxa_core.config import settings as _settings
        from conxa_core.storage.plugin_store import (
            get_plugin,
            set_workflow_test_error,
            set_workflow_test_result,
        )

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        workflow_id = _safe_id(payload.get("workflow_id"), "workflow_id")
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}

        plugin = get_plugin(plugin_id)
        if plugin is None:
            raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
        workflow = next((wf for wf in plugin.workflows if wf.id == workflow_id), None)
        if workflow is None:
            raise _CommandError("workflow_not_found", f"No workflow {workflow_id}")
        if not workflow.skill_id:
            raise _CommandError("workflow_not_compiled", "Compile this workflow before testing.")
        if plugin.build is None:
            raise _CommandError("plugin_not_built", "Build the plugin before testing its workflows.")

        sink = _event_sink(rid)
        sink({"kind": "workflow_test", "message": f"Preparing test for {workflow.name!r}…"})

        runtime_dir = resolve_runtime_dir()
        if runtime_dir is None:
            raise _CommandError(
                "runtime_not_found",
                "Conxa runtime not found. Run dependency bootstrap so Build Studio downloads the cloud runtime, or set CONXA_DIR explicitly.",
            )

        company = _plugin_company_slug(plugin)
        if not company:
            raise _CommandError("invalid_plugin", "Built plugin is missing a runtime company slug.")

        data_dir = Path(_settings.data_dir)
        source_dir = data_dir / "skill-packs" / company
        if not source_dir.is_dir():
            raise _CommandError(
                "skill_pack_not_built",
                f"Built skill pack not found: skill-packs/{company}. Run Build Plugin again.",
            )

        studio_base = Path(os.environ.get("SKILL_DATA_DIR") or os.path.expanduser("~/.conxa-build-studio"))
        test_data_dir = studio_base / "test-data"
        test_data_dir.mkdir(parents=True, exist_ok=True)

        try:
            sink({"kind": "workflow_test", "message": "Staging skill pack for the runtime…"})
            sync_skill_pack(company, source_dir, runtime_dir, data_dir=test_data_dir)
            _stage_runtime_auth(plugin, company, test_data_dir)

            # Frozen builds run the packed runtime exe, which has no node_modules
            # for an npx-based Playwright install. Point it at the Studio-managed
            # Chromium (~/.conxa-build-studio/deps/chromium) — its revision matches the packed
            # runtime's bundled Playwright, so it launches directly. Dev keeps the
            # per-runtime chromium dir and the npx install path.
            if getattr(sys, "frozen", False):
                browsers_dir = _bootstrap_pkg.chromium_dir()
            else:
                browsers_dir = runtime_dir / "chromium"

            ensure_chromium_installed(
                browsers_dir,
                runtime_dir,
                log_sink=lambda msg: sink({"kind": "workflow_test", "message": msg}),
            )

            sink({"kind": "workflow_test", "message": f"Running {workflow.name!r}…"})
            result = call_runtime_tool(
                runtime_dir,
                "execute_skill",
                {
                    "skill": workflow.slug,
                    "company": company,
                    "inputs": inputs,
                    "watch": not bool(payload.get("headless")),
                },
                env={
                    "CONXA_DATA_DIR": str(test_data_dir),
                    "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir),
                },
            )
        except (RuntimeToolError, RuntimeError) as exc:
            message = str(exc)
            set_workflow_test_error(plugin_id, workflow_id, message)
            raise _CommandError("workflow_test_failed", message) from exc

        message = _runtime_result_text(result)
        if not message.startswith("Done."):
            failure = message or "Runtime test failed without a result message."
            set_workflow_test_error(plugin_id, workflow_id, failure)
            raise _CommandError("workflow_test_failed", failure)

        set_workflow_test_result(plugin_id, workflow_id, status="passed", inputs=inputs)
        sink({"kind": "workflow_test", "message": message})
        return {"status": "passed", "message": message, "company": company, "skill": workflow.slug}

    def cmd_publish(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import base64
        import urllib.request
        from pathlib import Path
        from conxa_core.config import settings as _settings

        slug = _safe_id(payload.get("slug"), "slug")
        packs_dir = Path(_settings.data_dir) / "skill-packs" / slug
        pack_path = packs_dir / "pack.json"
        if not pack_path.is_file():
            raise _CommandError("pack_not_built", f"No built skill pack for {slug}")
        pack = json.loads(pack_path.read_text(encoding="utf-8"))

        files: list[dict[str, str]] = []
        for fpath in sorted(packs_dir.rglob("*")):
            if fpath.is_file():
                rel = fpath.relative_to(packs_dir).as_posix()
                files.append({
                    "path": rel,
                    "content_base64": base64.b64encode(fpath.read_bytes()).decode("ascii"),
                })

        body = json.dumps({
            "slug": slug,
            "skill_pack_version": str(pack.get("skill_pack_version") or "0.1.0"),
            "skills": list(pack.get("skills") or []),
            "files": files,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._cloud_api}/api/v1/plugins/publish", data=body, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self._auth_service().get_token()}")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def cmd_get_usage(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import urllib.request

        try:
            entitlements = self._cloud_json("/api/v1/entitlements/current")
        except _CommandError as exc:
            entitlements = {
                "entitlements_unavailable": True,
                "error": {"code": exc.code, "message": exc.message},
            }

        try:
            req = urllib.request.Request(f"{self._cloud_api}/api/v1/llm/proxy/usage")
            req.add_header("X-Conxa-Client", os.environ.get("CONXA_PROXY_CLIENT", "build-studio"))
            req.add_header("Authorization", f"Bearer {self._auth_service().get_token()}")
            with urllib.request.urlopen(req, timeout=30) as resp:
                legacy = json.loads(resp.read().decode("utf-8"))
        except Exception:
            legacy = {}
        if "meters" in entitlements:
            return {**entitlements, "legacy_llm_usage": legacy}
        return {**entitlements, "legacy_llm_usage": legacy}

    # ─── helpers ────────────────────────────────────────────────────────────

    def _skill_response(
        self,
        skill_id: str,
        doc: dict[str, Any],
        revalidation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.config import settings
        from conxa_compile.editor.workflow_service import build_workflow_response

        asset_base_url = f"file://{Path(settings.data_dir) / 'skills' / skill_id / 'assets'}"
        workflow = build_workflow_response(skill_id, doc, asset_base_url=asset_base_url)
        return {
            "skill_id": skill_id,
            "meta": dict(doc.get("meta") or {}),
            "revalidation": revalidation or {},
            "workflow": workflow.model_dump(mode="json"),
        }

    # ─── plugin management ──────────────────────────────────────────────────

    def cmd_delete_plugin(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.plugin_store import delete_plugin

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        return {"deleted": bool(delete_plugin(plugin_id))}

    def cmd_delete_workflow(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.plugin_store import remove_workflow

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        workflow_id = _safe_id(payload.get("workflow_id"), "workflow_id")
        if remove_workflow(plugin_id, workflow_id) is None:
            raise _CommandError("not_found", "Plugin or workflow not found")
        return {"deleted": True}

    def cmd_re_record_auth(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        """Clear a plugin's captured auth so the user can record a fresh session.

        Drops the stored ``auth.json`` and resets the plugin back to the
        ``needs_auth`` state; the renderer then drives a new auth recording.
        """
        from pathlib import Path
        from conxa_core.config import settings as _settings
        from conxa_core.storage.plugin_store import get_plugin, save_plugin

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        plugin = get_plugin(plugin_id)
        if plugin is None:
            raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")

        plugin.auth = None
        plugin.status = "needs_auth"
        save_plugin(plugin)

        auth_file = Path(_settings.data_dir) / "plugins" / plugin_id / "auth" / "auth.json"
        if auth_file.is_file():
            auth_file.unlink()
        return {"status": "needs_auth"}

    def cmd_update_workflow(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.plugin_store import get_plugin, save_plugin

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        workflow_id = _safe_id(payload.get("workflow_id"), "workflow_id")
        plugin = get_plugin(plugin_id)
        if plugin is None:
            raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
        for wf in plugin.workflows:
            if wf.id == workflow_id:
                if "skill_id" in payload:
                    wf.skill_id = payload["skill_id"]
                if "status" in payload:
                    wf.status = payload["status"]
                save_plugin(plugin)
                return {"plugin_id": plugin_id, "workflow_id": workflow_id,
                        "skill_id": wf.skill_id, "status": wf.status}
        raise _CommandError("workflow_not_found", f"No workflow {workflow_id}")

    # ─── recording status ────────────────────────────────────────────────────

    def cmd_get_recording_status(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        session_id = _safe_id(payload.get("session_id"), "session_id")
        sess = _recorder_registry.get(session_id)
        if sess is None:
            raise _CommandError("session_not_found", f"No session {session_id}")
        return sess.status()

    # ─── skill workflow (human edit) ─────────────────────────────────────────

    def cmd_get_workflow(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.config import settings
        from conxa_core.storage.json_store import read_skill
        from conxa_compile.editor.workflow_service import build_workflow_response

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        document = read_skill(skill_id)
        if document is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        asset_base_url = f"file://{Path(settings.data_dir) / 'skills' / skill_id / 'assets'}"
        return build_workflow_response(skill_id, document, asset_base_url=asset_base_url).model_dump(mode="json")

    def cmd_patch_step(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.compiler.patch import revalidate_step

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        step_index = int(payload.get("step_index") or 0)
        patch = dict(payload.get("patch") or {})
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        snapshot = copy.deepcopy(doc)
        doc = dict(doc)
        skills = list(doc.get("skills") or [])
        if not skills:
            raise _CommandError("invalid_document", "No skills block")
        block = dict(skills[0])
        steps = list(block.get("steps") or [])
        if step_index < 0 or step_index >= len(steps):
            raise _CommandError("step_not_found", f"Step {step_index} out of range")
        step = _deep_merge(dict(steps[step_index]), patch)
        steps[step_index] = step
        block["steps"] = steps
        skills[0] = block
        doc["skills"] = skills
        meta = dict(doc.get("meta") or {})
        meta["version"] = int(meta.get("version", 1)) + 1
        doc["meta"] = meta
        revalidation = revalidate_step(step)
        self._push_undo(skill_id, snapshot)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc, revalidation)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_validate_workflow(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.json_store import read_skill
        from conxa_compile.editor.workflow_service import validate_skill_document

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        return validate_skill_document(doc)

    def cmd_reorder_steps(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.workflow_service import reorder_steps

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        new_order = list(payload.get("new_order") or [])
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        self._push_undo(skill_id, copy.deepcopy(doc))
        doc = reorder_steps(doc, new_order)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_insert_step(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.workflow_service import insert_step_after

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        action_kind = str(payload.get("action_kind") or "click")
        insert_after = payload.get("insert_after")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        self._push_undo(skill_id, copy.deepcopy(doc))
        doc = insert_step_after(doc, action_kind, insert_after)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_delete_step(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.workflow_service import delete_step_at

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        step_index = int(payload.get("step_index") or 0)
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        self._push_undo(skill_id, copy.deepcopy(doc))
        doc = delete_step_at(doc, step_index)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_update_workflow_inputs(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.workflow_service import merge_skill_inputs

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        inputs = list(payload.get("inputs") or [])
        title = payload.get("title")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        doc = merge_skill_inputs(doc, inputs, title)
        write_skill(skill_id, doc)
        return {"skill_id": skill_id, "ok": True}

    def cmd_replace_literals(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.workflow_service import replace_string_literals_in_skill_document

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        find = str(payload.get("find") or "")
        replace_with = str(payload.get("replace_with") or "")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        self._push_undo(skill_id, copy.deepcopy(doc))
        doc = replace_string_literals_in_skill_document(doc, find, replace_with)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_undo_workflow(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        undo_stack = self._undo_stacks.get(skill_id, [])
        if not undo_stack:
            raise _CommandError("nothing_to_undo", "No undo history for this skill")
        current = read_skill(skill_id)
        if current is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        self._redo_stacks.setdefault(skill_id, []).append(copy.deepcopy(current))
        prev_doc = undo_stack.pop()
        prev_doc = dict(prev_doc)
        meta = dict(prev_doc.get("meta") or {})
        meta["version"] = int(meta.get("version", 1)) + 1
        prev_doc["meta"] = meta
        write_skill(skill_id, prev_doc)
        result = self._skill_response(skill_id, prev_doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_redo_workflow(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        redo_stack = self._redo_stacks.get(skill_id, [])
        if not redo_stack:
            raise _CommandError("nothing_to_redo", "No redo history for this skill")
        current = read_skill(skill_id)
        if current is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        self._undo_stacks.setdefault(skill_id, []).append(copy.deepcopy(current))
        next_doc = redo_stack.pop()
        next_doc = dict(next_doc)
        meta = dict(next_doc.get("meta") or {})
        meta["version"] = int(meta.get("version", 1)) + 1
        next_doc["meta"] = meta
        write_skill(skill_id, next_doc)
        result = self._skill_response(skill_id, next_doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_sign_off_workflow(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import time
        from conxa_core.storage.plugin_store import list_plugins, save_plugin

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        for plugin in list_plugins():
            for wf in plugin.workflows:
                if wf.skill_id == skill_id:
                    wf.edited_at = time.time()
                    wf.signed_off = True
                    save_plugin(plugin)
                    return {"skill_id": skill_id, "signed_off": True}
        return {"skill_id": skill_id, "signed_off": True}

    def cmd_compile_updated(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.json_store import read_skill, write_skill

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        skill_title = str(payload.get("skill_title") or "").strip()
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        doc = dict(doc)
        meta = dict(doc.get("meta") or {})
        if skill_title:
            meta["title"] = skill_title
        meta["version"] = int(meta.get("version") or 1) + 1
        doc["meta"] = meta
        write_skill(skill_id, doc)
        return {"skill_id": skill_id, "ok": True}

    # ─── recording visuals ───────────────────────────────────────────────────

    def cmd_list_recording_screenshots(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.config import settings
        from conxa_core.storage.json_store import read_skill
        from conxa_compile.editor.recording_visual import screenshot_items_for_skill

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        asset_base_url = f"file://{Path(settings.data_dir) / 'skills' / skill_id / 'assets'}"
        session_id, items = screenshot_items_for_skill(skill_id, doc, asset_base_url=asset_base_url)
        return {"skill_id": skill_id, "session_id": session_id, "items": items}

    def cmd_apply_recording_visual(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.recording_visual import apply_recording_event_visual_to_step_or_raise
        from services.llm_proxy_client import CloudUnreachable, EntitlementBlocked, QuotaExceeded

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        step_index = int(payload.get("step_index") or 0)
        event_index = int(payload.get("event_index") or 0)
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        snapshot = copy.deepcopy(doc)
        self._install_proxy_router(usage_class="human_edit")
        try:
            doc = apply_recording_event_visual_to_step_or_raise(doc, step_index, event_index)
        except EntitlementBlocked as exc:
            raise _CommandError(exc.code, self._entitlement_error_message(exc.code)) from exc
        except QuotaExceeded as exc:
            raise _CommandError("quota_exceeded", str(exc)) from exc
        except CloudUnreachable as exc:
            raise _CommandError("cloud_unreachable", str(exc)) from exc
        self._push_undo(skill_id, snapshot)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_apply_step_frame(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.recording_visual import apply_step_frame_or_raise
        from services.llm_proxy_client import CloudUnreachable, EntitlementBlocked, QuotaExceeded

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        step_index = int(payload.get("step_index") or 0)
        frame_label = str(payload.get("frame_label") or "").strip()
        if not frame_label:
            raise _CommandError("invalid_frame_label", "frame_label is required")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        snapshot = copy.deepcopy(doc)
        self._install_proxy_router(usage_class="human_edit")
        try:
            doc = apply_step_frame_or_raise(doc, step_index, frame_label)
        except EntitlementBlocked as exc:
            raise _CommandError(exc.code, self._entitlement_error_message(exc.code)) from exc
        except QuotaExceeded as exc:
            raise _CommandError("quota_exceeded", str(exc)) from exc
        except CloudUnreachable as exc:
            raise _CommandError("cloud_unreachable", str(exc)) from exc
        self._push_undo(skill_id, snapshot)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_clear_step_visual(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.recording_visual import clear_step_visual_screenshots_or_raise

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        step_index = int(payload.get("step_index") or 0)
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        self._push_undo(skill_id, copy.deepcopy(doc))
        doc = clear_step_visual_screenshots_or_raise(doc, step_index)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    def cmd_update_visual_bbox(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import copy
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_compile.editor.recording_visual import (
            update_step_visual_bbox_and_regenerate_anchors_or_raise,
        )
        from services.llm_proxy_client import CloudUnreachable, EntitlementBlocked, QuotaExceeded

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        step_index = int(payload.get("step_index") or 0)
        bbox = {k: float(payload.get(k) or 0) for k in ("x", "y", "w", "h")}
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        snapshot = copy.deepcopy(doc)
        self._install_proxy_router(usage_class="human_edit")
        try:
            doc = update_step_visual_bbox_and_regenerate_anchors_or_raise(doc, step_index, bbox)
        except EntitlementBlocked as exc:
            raise _CommandError(exc.code, self._entitlement_error_message(exc.code)) from exc
        except QuotaExceeded as exc:
            raise _CommandError("quota_exceeded", str(exc)) from exc
        except CloudUnreachable as exc:
            raise _CommandError("cloud_unreachable", str(exc)) from exc
        self._push_undo(skill_id, snapshot)
        write_skill(skill_id, doc)
        result = self._skill_response(skill_id, doc)
        result.update(self._history_flags(skill_id))
        return result

    # ─── skill library ───────────────────────────────────────────────────────

    def cmd_list_skills(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.config import settings

        skills_dir = Path(settings.data_dir) / "skills"
        result = []
        if skills_dir.is_dir():
            for d in sorted(skills_dir.iterdir()):
                skill_json = d / "skill.json"
                if skill_json.is_file():
                    try:
                        doc = json.loads(skill_json.read_text(encoding="utf-8"))
                        meta = doc.get("meta") or {}
                        steps = (doc.get("skills") or [{}])[0].get("steps") or []
                        result.append({
                            "skill_id": d.name,
                            "title": str(meta.get("title") or d.name),
                            "version": int(meta.get("version") or 1),
                            "step_count": len(steps),
                            "modified_at": skill_json.stat().st_mtime,
                        })
                    except Exception:
                        pass
        return {"skills": result}

    def cmd_delete_skill(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        import shutil
        from pathlib import Path
        from conxa_core.config import settings

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        skill_dir = Path(settings.data_dir) / "skills" / skill_id
        if not skill_dir.is_dir():
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        title = skill_id
        skill_json = skill_dir / "skill.json"
        if skill_json.is_file():
            try:
                title = str(
                    (json.loads(skill_json.read_text(encoding="utf-8")).get("meta") or {}).get("title") or skill_id
                )
            except Exception:
                pass
        shutil.rmtree(skill_dir)
        return {"skill_id": skill_id, "title": title, "deleted": True}

    def cmd_rename_skill(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.json_store import read_skill, write_skill

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        title = str(payload.get("title") or "").strip()
        if not title:
            raise _CommandError("invalid_input", "title is required")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        doc = dict(doc)
        meta = dict(doc.get("meta") or {})
        meta["title"] = title
        doc["meta"] = meta
        write_skill(skill_id, doc)
        return {"skill_id": skill_id, "title": title}

    def cmd_get_skill_document(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.json_store import read_skill

        skill_id = _safe_id(payload.get("skill_id"), "skill_id")
        doc = read_skill(skill_id)
        if doc is None:
            raise _CommandError("skill_not_found", f"No skill {skill_id}")
        return doc

    def cmd_get_compiled_skill(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.storage.plugin_store import get_plugin

        plugin_id = _safe_id(payload.get("plugin_id"), "plugin_id")
        skill_slug = str(payload.get("skill_slug") or "").strip()
        if not skill_slug:
            raise _CommandError("invalid_input", "skill_slug is required")
        plugin = get_plugin(plugin_id)
        if plugin is None:
            raise _CommandError("plugin_not_found", f"No plugin {plugin_id}")
        if plugin.build is None:
            raise _CommandError("not_built", "Plugin has not been built yet")
        skill_dir = Path(plugin.build.output_path) / "skills" / skill_slug
        if not skill_dir.is_dir():
            raise _CommandError("skill_not_found", f"No compiled skill {skill_slug}")
        files: dict[str, Any] = {}
        for fname in ("execution.json", "recovery.json", "input.json"):
            fpath = skill_dir / fname
            files[fname] = json.loads(fpath.read_text(encoding="utf-8")) if fpath.is_file() else None
        return {"plugin_id": plugin_id, "skill_slug": skill_slug, "files": files}

    # ─── skill packages ──────────────────────────────────────────────────────

    def cmd_list_skill_packages(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.skill_packages import (
            list_skill_package_summaries,
            skill_package_root_dir,
        )

        root = skill_package_root_dir()
        packages = []
        for package in list_skill_package_summaries():
            package_name = str(package.get("package_name") or "")
            package_folder = f"{package_name}-plugin"
            packages.append(
                {
                    **package,
                    "package_folder": package_folder,
                    "package_path": str(root / package_folder),
                }
            )
        return {"packages": packages, "bundle_root": str(root)}

    def cmd_list_skill_package_files(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.skill_packages import read_skill_package_bundle_files

        package_name = str(payload.get("package_name") or "").strip()
        if not package_name:
            raise _CommandError("invalid_input", "package_name is required")
        files = read_skill_package_bundle_files(package_name)
        if files is None:
            raise _CommandError("package_not_found", f"No package {package_name}")
        return {"package_name": package_name, "files": files}

    def cmd_delete_skill_package(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.skill_packages import delete_skill_package_bundle

        package_name = str(payload.get("package_name") or "").strip()
        if not package_name:
            raise _CommandError("invalid_input", "package_name is required")
        if not delete_skill_package_bundle(package_name):
            raise _CommandError("package_not_found", f"No package {package_name}")
        return {"package_name": package_name, "deleted": True}

    def cmd_rename_skill_package(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_core.storage.skill_packages import rename_skill_package_bundle

        package_name = str(payload.get("package_name") or "").strip()
        new_name = str(payload.get("new_name") or "").strip()
        if not package_name or not new_name:
            raise _CommandError("invalid_input", "package_name and new_name are required")
        try:
            rename_skill_package_bundle(package_name, new_name)
        except FileNotFoundError:
            raise _CommandError("package_not_found", f"No package {package_name}")
        except ValueError as exc:
            message = str(exc)
            code = "already_exists" if "already exists" in message else "invalid_input"
            raise _CommandError(code, message)
        return {"package_name": new_name, "previous_name": package_name}

    def cmd_set_skill_pack_bundle_root(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        bundle_root = str(payload.get("bundle_root") or "").strip()
        if not bundle_root:
            raise _CommandError("invalid_input", "bundle_root is required")
        return {"bundle_root": bundle_root}

    # ─── runs ────────────────────────────────────────────────────────────────

    def cmd_list_runs(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.config import settings

        plugin_id = payload.get("plugin_id")
        since = payload.get("since")
        runs_dir = Path(settings.data_dir) / "runs"
        runs = []
        if runs_dir.is_dir():
            for fpath in sorted(runs_dir.glob("*.jsonl")):
                try:
                    for line in fpath.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if plugin_id and record.get("plugin_id") != plugin_id:
                                continue
                            if since is not None and record.get("ts", 0) < float(since):
                                continue
                            runs.append(record)
                        except (json.JSONDecodeError, TypeError):
                            continue
                except Exception:
                    continue
        runs.sort(key=lambda r: r.get("ts", 0), reverse=True)
        return {"runs": runs[:100]}

    def cmd_get_run(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.config import settings

        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            raise _CommandError("invalid_input", "run_id is required")
        runs_dir = Path(settings.data_dir) / "runs"
        if runs_dir.is_dir():
            for fpath in sorted(runs_dir.glob("*.jsonl")):
                try:
                    for line in fpath.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if record.get("run_id") == run_id:
                                return {"run": record}
                        except (json.JSONDecodeError, TypeError):
                            continue
                except Exception:
                    continue
        raise _CommandError("run_not_found", f"No run {run_id}")

    # ─── metrics ─────────────────────────────────────────────────────────────

    def cmd_get_metrics(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from pathlib import Path
        from conxa_core.config import settings
        from conxa_core.storage.plugin_store import list_plugins

        data_dir = Path(settings.data_dir)
        skills_dir = data_dir / "skills"
        skill_count = (
            sum(1 for d in skills_dir.iterdir() if d.is_dir() and (d / "skill.json").is_file())
            if skills_dir.is_dir()
            else 0
        )
        packs_dir = data_dir / "skill-packs"
        pack_count = sum(1 for d in packs_dir.iterdir() if d.is_dir()) if packs_dir.is_dir() else 0
        return {
            "skill_count": skill_count,
            "plugin_count": len(list_plugins()),
            "pack_count": pack_count,
        }

    # -- dispatch ------------------------------------------------------------

    def dispatch(self, msg: dict[str, Any]) -> None:
        rid = msg.get("id")
        cmd = str(msg.get("type") or "")
        payload = msg.get("payload") or {}
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            _write({"id": rid, "type": "error", "code": "unknown_command", "message": cmd})
            return
        try:
            result = handler(payload, rid)
            _write({"id": rid, "type": "result", "result": result})
        except _CommandError as exc:
            _write({"id": rid, "type": "error", "code": exc.code, "message": exc.message})
        except Exception as exc:  # noqa: BLE001 — report any handler failure to the renderer
            _write({
                "id": rid,
                "type": "error",
                "code": "internal_error",
                "message": str(exc),
                "trace": traceback.format_exc()[-2000:],
            })

    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                _write({"type": "error", "code": "bad_json", "message": line[:200]})
                continue
            # Each request is handled on its own thread so a long build does not
            # block recording stop/cancel commands.
            threading.Thread(target=self.dispatch, args=(msg,), daemon=True).start()


class _CommandError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursively merge patch into base, preserving unpatched nested keys."""
    result = dict(base)
    for k, v in patch.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _safe_id(value: object, field: str) -> str:
    from services.validation import InvalidInput, safe_identifier

    try:
        return safe_identifier(value, field)
    except InvalidInput as exc:
        raise _CommandError("invalid_input", str(exc)) from exc


if __name__ == "__main__":
    Backend().serve()
