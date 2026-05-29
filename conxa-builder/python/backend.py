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
from typing import Any, Callable

# Make this `python` dir importable (for the local `services` package and the
# bundled `conxa_compile` pipeline), regardless of launch CWD. The shared
# `conxa_core` package is installed as a dependency, not imported by path.
_PY_DIR = os.path.abspath(os.path.dirname(__file__))
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

from services import bootstrap as _bootstrap_pkg  # noqa: E402


# --- stdout protocol ---------------------------------------------------------

_stdout_lock = threading.Lock()


def _write(obj: dict[str, Any]) -> None:
    with _stdout_lock:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
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
    def __init__(self) -> None:
        self._loop = _Loop()
        self._active_recording: str | None = None
        self._rec_lock = threading.Lock()
        self._auth = None  # AuthService, lazily built once configured
        self._cloud_api = os.environ.get("CONXA_CLOUD_API", "http://127.0.0.1:8000")

    # -- lazy auth wiring ----------------------------------------------------

    def _auth_service(self):
        if self._auth is None:
            from services.auth_service import AuthService

            self._auth = AuthService(
                clerk_domain=os.environ.get("CONXA_CLERK_DOMAIN", ""),
                client_id=os.environ.get("CONXA_CLERK_CLIENT_ID", ""),
                cloud_api=self._cloud_api,
            )
        return self._auth

    def _install_proxy_router(self) -> None:
        """Redirect every compiler LLM call to the metered cloud proxy."""
        from services.llm_proxy_client import LLMProxyClient
        from conxa_core import llm as core_llm

        client = LLMProxyClient(
            self._cloud_api,
            token_provider=lambda: self._auth_service().get_token(),
            client_header=os.environ.get("CONXA_PROXY_CLIENT", "build-studio"),
        )
        core_llm.set_router(client)

    # -- command handlers ----------------------------------------------------

    def cmd_ping(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        return {"ok": True, "pid": os.getpid()}

    def cmd_bootstrap(self, _payload: dict[str, Any], rid: str) -> dict[str, Any]:
        return _bootstrap_pkg.ensure_all(self._cloud_api, on_event=_event_sink(rid))

    def cmd_login(self, _payload: dict[str, Any], rid: str) -> dict[str, Any]:
        return self._auth_service().login(on_event=_event_sink(rid))

    def cmd_logout(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        self._auth_service().logout()
        return {"ok": True}

    def cmd_whoami(self, _payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        return {"identity": self._auth_service().current_identity()}

    def cmd_start_recording(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_compile.recorder.session import registry

        with self._rec_lock:
            if self._active_recording is not None:
                raise _CommandError("recording_in_progress", "A recording is already active.")
            start_url = str(payload.get("start_url") or "about:blank")
            auth_mode = bool(payload.get("auth_mode"))
            storage_state_path = str(payload.get("storage_state_path") or "")
            storage_state_autosave = str(payload.get("storage_state_autosave_path") or "")
            sess = registry.create(
                start_url=start_url,
                storage_state_path=storage_state_path,
                storage_state_autosave_path=storage_state_autosave,
                auth_mode=auth_mode,
                capture_hover=bool(payload.get("capture_hover")),
            )
            try:
                self._loop.run(sess.start())
            except RuntimeError as exc:
                registry.pop(sess.session_id)
                raise _CommandError("recorder_launch_failed", str(exc)) from exc
            self._active_recording = sess.session_id
            return {"session_id": sess.session_id, "start_url": start_url}

    def cmd_stop_recording(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_compile.recorder.session import registry

        session_id = _safe_id(payload.get("session_id"), "session_id")
        sess = registry.get(session_id)
        if sess is None:
            raise _CommandError("session_not_found", f"No session {session_id}")
        events = sess.snapshot_events()
        self._loop.run(sess.stop())
        with self._rec_lock:
            if self._active_recording == session_id:
                self._active_recording = None
        return {"session_id": session_id, "event_count": len(events)}

    def cmd_run_pipeline(self, payload: dict[str, Any], _rid: str) -> dict[str, Any]:
        from conxa_compile.pipeline.run import run_pipeline
        from conxa_core.storage.session_events import read_session_events
        from conxa_compile.recorder.session import registry

        session_id = _safe_id(payload.get("session_id"), "session_id")
        sess = registry.get(session_id)
        raw = sess.snapshot_events() if sess else read_session_events(session_id)
        normalized = run_pipeline(raw)
        return {"session_id": session_id, "event_count": len(normalized)}

    def cmd_compile(self, payload: dict[str, Any], rid: str) -> dict[str, Any]:
        from conxa_compile.compiler.build import compile_skill_package
        from conxa_compile.pipeline.run import run_pipeline
        from conxa_core.storage.json_store import read_skill, write_skill
        from conxa_core.storage.session_events import read_session_events
        from conxa_compile.recorder.session import registry

        session_id = _safe_id(payload.get("session_id"), "session_id")
        title = str(payload.get("skill_title") or "").strip()
        if not title:
            raise _CommandError("invalid_input", "skill_title is required")

        self._install_proxy_router()
        sink = _event_sink(rid)
        sink({"phase": "pipeline_start"})

        sess = registry.get(session_id)
        raw = sess.snapshot_events() if sess else read_session_events(session_id)
        if not raw:
            raise _CommandError("no_events", "No recorded events for this session.")
        normalized = run_pipeline(raw)
        sink({"phase": "pipeline_done", "event_count": len(normalized)})

        skill_id = f"skill_{session_id}"
        existing = read_skill(skill_id)
        version = int((existing.get("meta") or {}).get("version") or 0) + 1 if existing else 1

        sink({"phase": "compiler_start"})
        package = compile_skill_package(
            normalized,
            skill_id=skill_id,
            source_session_id=session_id,
            title=title,
            version=version,
        )
        write_skill(skill_id, package.model_dump(mode="json"))
        step_count = len(package.skills[0].steps)
        sink({"phase": "compiler_done", "step_count": step_count})
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
        company_slug = _safe_id(payload.get("company_slug"), "company_slug")

        # Invariant: auth.json must never enter the installer input.
        from conxa_core.config import settings as _settings
        plugin_dir = Path(_settings.data_dir) / "plugins" / plugin_id
        if plugin_dir.exists() and any(plugin_dir.rglob("auth.json")):
            raise _CommandError(
                "auth_file_in_build_input",
                "Refusing to build: auth.json found under the plugin directory.",
            )

        return build_installer(
            plugin_id, company_slug=company_slug, realtime_sink=_event_sink(rid)
        )

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

        req = urllib.request.Request(f"{self._cloud_api}/api/v1/llm/proxy/usage")
        req.add_header("X-Conxa-Client", os.environ.get("CONXA_PROXY_CLIENT", "build-studio"))
        req.add_header("Authorization", f"Bearer {self._auth_service().get_token()}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

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


def _safe_id(value: object, field: str) -> str:
    from services.validation import InvalidInput, safe_identifier

    try:
        return safe_identifier(value, field)
    except InvalidInput as exc:
        raise _CommandError("invalid_input", str(exc)) from exc


if __name__ == "__main__":
    Backend().serve()
