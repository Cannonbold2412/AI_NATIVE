"""Phase 2: Build Studio stdio backend dispatcher + input sanitization."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from types import SimpleNamespace

import pytest

_PY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "conxa-builder", "python")
sys.path.insert(0, os.path.abspath(_PY_DIR))


@pytest.fixture()
def backend():
    spec = importlib.util.spec_from_file_location(
        "cbackend", os.path.join(_PY_DIR, "backend.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out: list[dict] = []
    mod._write = lambda obj: out.append(obj)  # capture protocol output
    b = mod.Backend()
    return b, out


def _last(out):
    return out[-1]


def test_ping(backend):
    b, out = backend
    b.dispatch({"id": "1", "type": "ping", "payload": {}})
    assert _last(out)["type"] == "result"
    assert _last(out)["result"]["ok"] is True


def test_unknown_command(backend):
    b, out = backend
    b.dispatch({"id": "2", "type": "frobnicate", "payload": {}})
    assert _last(out)["type"] == "error"
    assert _last(out)["code"] == "unknown_command"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "a\\b", "x\x00y", ""])
def test_path_traversal_rejected(backend, bad):
    b, out = backend
    b.dispatch({"id": "3", "type": "stop_recording", "payload": {"session_id": bad}})
    assert _last(out)["type"] == "error"
    assert _last(out)["code"] == "invalid_input"


def test_missing_plugin_reported(backend):
    b, out = backend
    b.dispatch({"id": "4", "type": "list_workflows", "payload": {"plugin_id": "ghost"}})
    assert _last(out)["type"] == "error"
    assert _last(out)["code"] == "plugin_not_found"


def test_validation_module():
    from services.validation import InvalidInput, safe_identifier

    assert safe_identifier("skill_abc-123", "x") == "skill_abc-123"
    for bad in ["../etc", "a/b", "a\\b", "x\x00y", "  "]:
        with pytest.raises(InvalidInput):
            safe_identifier(bad, "x")


def test_proxy_router_injection_swaps_singleton(backend, monkeypatch):
    b, _out = backend
    monkeypatch.setenv("CONXA_CLERK_DOMAIN", "https://clerk.example.com")
    monkeypatch.setenv("CONXA_CLERK_CLIENT_ID", "client_x")

    b._install_proxy_router()
    from conxa_core import llm as core_llm
    from services.llm_proxy_client import LLMProxyClient

    assert isinstance(core_llm.get_router(), LLMProxyClient)


def test_installer_publish_rewrites_pack_with_cloud_tracking(backend, monkeypatch, tmp_path):
    import urllib.request

    b, _out = backend
    from conxa_core.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    b._cloud_api = "https://apis.conxa.in"
    b._auth = SimpleNamespace(get_token=lambda: "studio-token")

    packs_dir = tmp_path / "skill-packs" / "render"
    packs_dir.mkdir(parents=True)
    (packs_dir / "pack.json").write_text(
        json.dumps(
            {
                "company": "render",
                "company_display": "Render",
                "skill_pack_version": "0.1.0",
                "target_url": "https://dashboard.render.com",
                "protected_url": "https://dashboard.render.com/",
                "skills": ["delete-a-service"],
                "tracking": {"tracking_url": "http://127.0.0.1:8000/api/tracking/render/events"},
            }
        ),
        encoding="utf-8",
    )
    skill_dir = packs_dir / "delete-a-service"
    skill_dir.mkdir()
    (skill_dir / "execution.json").write_text("[]", encoding="utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "tracking": {
                        "enabled": True,
                        "tracking_url": "https://internal.example/api/tracking/render/events",
                        "tracking_token": "cloud-token",
                        "company_id": "render",
                        "schema_version": 1,
                        "protocol_version": 1,
                    },
                    "sync_token": "sync-token",
                    "workspace_id": "wrk_123",
                    "published_at": 123.0,
                }
            ).encode("utf-8")

    seen: dict[str, object] = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        seen["timeout"] = timeout
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    logs: list[dict] = []

    publish_info = b._publish_skill_pack_for_installer(
        company_slug="render",
        plugin=SimpleNamespace(name="Render", target_url="https://dashboard.render.com", protected_url="https://dashboard.render.com/"),
        version="1.2.3",
        release_notes="Release message",
        sink=logs.append,
    )

    rewritten = json.loads((packs_dir / "pack.json").read_text(encoding="utf-8"))
    assert seen["url"] == "https://apis.conxa.in/api/v1/plugins/publish"
    assert seen["auth"] == "Bearer studio-token"
    assert seen["body"]["skill_pack_version"] == "1.2.3"
    assert seen["body"]["release_notes"] == "Release message"
    assert rewritten["skill_pack_version"] == "1.2.3"
    assert rewritten["release_notes"] == "Release message"
    assert rewritten["tracking"]["tracking_url"] == "https://apis.conxa.in/api/tracking/render/events"
    assert rewritten["tracking"]["tracking_token"] == "cloud-token"
    assert rewritten["sync_endpoint"] == "https://apis.conxa.in/api/v1/skill-packs/render/delta"
    assert rewritten["sync_token"] == "sync-token"
    assert publish_info["workspace_id"] == "wrk_123"
    assert publish_info["tracking_url"] == "https://apis.conxa.in/api/tracking/render/events"
    assert publish_info["tracking_token_present"] is True
    assert any("workspace wrk_123" in entry["message"] for entry in logs)


def test_cmd_build_installer_forwards_release_metadata(backend, monkeypatch, tmp_path):
    b, _out = backend

    from conxa_core.config import settings
    from conxa_core.storage.plugin_store import create_plugin
    from services import installer_builder

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    plugin = create_plugin("Render", "https://dashboard.render.com")
    seen: dict[str, object] = {}

    def fake_publish(**kwargs):
        seen["publish"] = kwargs
        return {}

    def fake_build(plugin_id, **kwargs):
        seen["build_plugin_id"] = plugin_id
        seen["build"] = kwargs
        return {
            "installer_path": str(tmp_path / "Render-Claude-Setup.exe"),
            "filename": "Render-Claude-Setup.exe",
            "company": kwargs["company_slug"],
            "plugin_id": plugin_id,
            "version": kwargs["version"],
            "runtime_version": "v1.0.0",
            "release_notes": kwargs["release_notes"],
        }

    def fake_upload(**kwargs):
        seen["upload"] = kwargs
        return dict(kwargs["result"], cloud_download_url="https://apis.conxa.in/api/v1/installers/render")

    monkeypatch.setattr(b, "_publish_skill_pack_for_installer", fake_publish)
    monkeypatch.setattr(installer_builder, "build_installer", fake_build)
    monkeypatch.setattr(b, "_upload_installer_for_download", fake_upload)

    result = b.cmd_build_installer(
        {
            "plugin_id": plugin.id,
            "company_slug": "render",
            "logo_path": "C:/logo.png",
            "version": "2.0.0",
            "release_notes": "Ship it",
        },
        "rid",
    )

    assert seen["publish"]["version"] == "2.0.0"
    assert seen["publish"]["release_notes"] == "Ship it"
    assert seen["build"]["version"] == "2.0.0"
    assert seen["build"]["release_notes"] == "Ship it"
    assert seen["upload"]["release_notes"] == "Ship it"
    assert result["version"] == "2.0.0"
    assert result["release_notes"] == "Ship it"


def test_auth_stop_recording_marks_plugin_ready(backend, monkeypatch, tmp_path):
    b, _out = backend
    globals_ = b.cmd_stop_recording.__globals__

    from conxa_core.config import settings
    from conxa_core.storage.plugin_store import create_plugin, get_plugin

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")

    plugin = create_plugin("Example Plugin", "https://example.test/login")

    class FakeContext:
        def storage_state(self, path: str) -> None:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"cookies": [], "origins": []}, fh)

    class FakePage:
        url = "https://example.test/dashboard"

    class FakeSession:
        current_url = "https://example.test/dashboard"
        _context = FakeContext()

        def _active_page_sync(self):
            return FakePage()

        def _remember_page_url_sync(self, _page):
            self.current_url = "https://example.test/dashboard"

        def snapshot_events(self):
            return []

        async def stop(self):
            return None

    class FakeRegistry:
        def get(self, session_id: str):
            return FakeSession() if session_id == "sess-1" else None

    monkeypatch.setitem(globals_, "_recorder_registry", FakeRegistry())

    result = b.cmd_stop_recording(
        {"plugin_id": plugin.id, "session_id": "sess-1", "auth_mode": True},
        "rid",
    )

    updated = get_plugin(plugin.id)
    assert result["plugin_status"] == "ready"
    assert result["storage_state_saved"] is True
    assert result["protected_url"] == "https://example.test/dashboard"
    assert updated is not None
    assert updated.auth is not None
    assert updated.auth.session_id == "sess-1"
    assert updated.status == "ready"


def test_auth_stop_recording_uses_autosaved_state_after_browser_close(backend, monkeypatch, tmp_path):
    b, _out = backend
    globals_ = b.cmd_stop_recording.__globals__

    from conxa_core.config import settings
    from conxa_core.storage.plugin_store import create_plugin, get_plugin

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")

    plugin = create_plugin("Closed Browser Plugin", "https://example.test/login")
    auth_path = tmp_path / "plugins" / plugin.id / "auth" / "auth.json"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

    class ClosedContext:
        def storage_state(self, path: str) -> None:
            raise RuntimeError("Target page, context or browser has been closed")

    class FakeSession:
        current_url = "https://example.test/app"
        _context = ClosedContext()

        def _active_page_sync(self):
            return None

        def snapshot_events(self):
            return []

        async def stop(self):
            return None

    class FakeRegistry:
        def get(self, session_id: str):
            return FakeSession() if session_id == "sess-closed" else None

    monkeypatch.setitem(globals_, "_recorder_registry", FakeRegistry())

    result = b.cmd_stop_recording(
        {"plugin_id": plugin.id, "session_id": "sess-closed", "auth_mode": True},
        "rid",
    )

    updated = get_plugin(plugin.id)
    assert result["plugin_status"] == "ready"
    assert result["storage_state_saved"] is True
    assert result["protected_url"] == "https://example.test/app"
    assert updated is not None
    assert updated.auth is not None
    assert updated.status == "ready"


def test_delete_plugin_removes_metadata_and_artifact_dir(monkeypatch, tmp_path):
    from conxa_core.config import settings
    from conxa_core.storage.plugin_store import create_plugin, delete_plugin, get_plugin

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")

    plugin = create_plugin("Delete Me", "https://example.test")
    plugin_file = tmp_path / "plugins" / f"{plugin.id}.json"
    plugin_dir = tmp_path / "plugins" / plugin.id
    auth_file = plugin_dir / "auth" / "auth.json"
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

    assert plugin_file.is_file()
    assert auth_file.is_file()

    assert delete_plugin(plugin.id) is True
    assert get_plugin(plugin.id) is None
    assert not plugin_file.exists()
    assert not plugin_dir.exists()
    assert delete_plugin(plugin.id) is False


def test_delete_plugin_command_is_idempotent_for_stale_renderer_rows(backend, monkeypatch, tmp_path):
    b, _out = backend

    from conxa_core.config import settings
    from conxa_core.storage.plugin_store import create_plugin

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")

    plugin = create_plugin("Delete Me", "https://example.test")

    assert b.cmd_delete_plugin({"plugin_id": plugin.id}, "rid") == {"deleted": True}
    assert b.cmd_delete_plugin({"plugin_id": plugin.id}, "rid") == {"deleted": False}


def test_compile_derives_title_from_plugin_workflow_and_marks_compiled(
    backend, monkeypatch, tmp_path
):
    b, out = backend

    from conxa_core.config import settings
    from conxa_core.storage.plugin_store import add_workflow, create_plugin, get_plugin
    import conxa_compile.compiler.build as compiler_build
    import conxa_compile.pipeline.run as pipeline_run
    import conxa_core.storage.session_events as session_events

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(b, "_install_proxy_router", lambda sink=None: None)
    monkeypatch.setattr(session_events, "read_session_events", lambda session_id: [{"type": "click"}])
    monkeypatch.setattr(pipeline_run, "run_pipeline", lambda raw: raw)

    plugin = create_plugin("Example Plugin", "https://example.test")
    added = add_workflow(plugin.id, "Submit Invoice", "sess-compile")
    assert added is not None

    captured: dict[str, object] = {}

    def fake_compile_skill_package(
        events,
        *,
        skill_id: str,
        source_session_id: str,
        title: str,
        version: int,
    ):
        captured.update(
            {
                "events": events,
                "skill_id": skill_id,
                "source_session_id": source_session_id,
                "title": title,
                "version": version,
            }
        )
        return SimpleNamespace(
            skills=[SimpleNamespace(steps=[{"kind": "click"}])],
            model_dump=lambda mode="json": {
                "meta": {
                    "id": skill_id,
                    "source_session_id": source_session_id,
                    "title": title,
                    "version": version,
                },
                "skills": [{"steps": [{"kind": "click"}]}],
            },
        )

    monkeypatch.setattr(compiler_build, "compile_skill_package", fake_compile_skill_package)

    result = b.cmd_compile(
        {"plugin_id": plugin.id, "session_id": "sess-compile"},
        "compile-request",
    )

    assert result["skill_id"] == "skill_sess-compile"
    assert captured["title"] == "Submit Invoice"
    updated = get_plugin(plugin.id)
    assert updated is not None
    workflow = updated.workflows[0]
    assert workflow.status == "compiled"
    assert workflow.skill_id == "skill_sess-compile"
    assert any(
        event.get("type") == "event"
        and event.get("id") == "compile-request"
        and event.get("phase") == "compile_done"
        for event in out
    )
