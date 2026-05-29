from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.recorder.session import registry
from app.storage.plugin_store import add_workflow, create_plugin, get_plugin, set_plugin_auth


class ClosedAuthSession:
    browser_open = False
    _context = None

    def __init__(self, current_url: str) -> None:
        self.current_url = current_url
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _ready_plugin(tmp_path):
    plugin = create_plugin(
        name="Empty Workflow",
        target_url="https://example.com/login",
        protected_url="https://example.com/app",
    )
    auth_path = tmp_path / "plugins" / plugin.id / "auth" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text("{}", encoding="utf-8")
    set_plugin_auth(plugin.id, "auth-session", str(auth_path))
    return plugin


def test_create_plugin_without_protected_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)
    client = TestClient(app)

    response = client.post(
        "/api/v1/plugins",
        json={"name": "Auto URL", "target_url": "https://example.com/login"},
    )

    assert response.status_code == 200
    plugin = response.json()["plugin"]
    assert plugin["protected_url"] == ""
    assert plugin["status"] == "needs_auth"


def test_finalize_auth_captures_current_url_as_protected_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)
    plugin = create_plugin(name="Auto URL", target_url="https://example.com/login")
    auth_path = tmp_path / "plugins" / plugin.id / "auth" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text("{}", encoding="utf-8")
    sess = ClosedAuthSession("https://example.com/app?team=abc#leads")
    registry._sessions["auth-final"] = sess  # type: ignore[attr-defined]
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/plugins/{plugin.id}/auth/finalize",
            json={"session_id": "auth-final"},
        )
    finally:
        registry.pop("auth-final")

    assert response.status_code == 200
    assert response.json()["protected_url"] == "https://example.com/app?team=abc#leads"
    refreshed = get_plugin(plugin.id)
    assert refreshed is not None
    assert refreshed.status == "ready"
    assert refreshed.protected_url == "https://example.com/app?team=abc#leads"
    assert refreshed.auth is not None
    assert sess.stopped is True


def test_finalize_auth_rejects_login_like_final_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)
    plugin = create_plugin(name="Bad URL", target_url="https://example.com/login")
    auth_path = tmp_path / "plugins" / plugin.id / "auth" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text("{}", encoding="utf-8")
    registry._sessions["auth-login-url"] = ClosedAuthSession("https://example.com/login")
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/plugins/{plugin.id}/auth/finalize",
            json={"session_id": "auth-login-url"},
        )
    finally:
        registry.pop("auth-login-url")

    assert response.status_code == 400
    assert "login/auth page" in response.json()["detail"]
    refreshed = get_plugin(plugin.id)
    assert refreshed is not None
    assert refreshed.status == "needs_auth"
    assert refreshed.auth is None
    assert refreshed.protected_url == ""


def test_re_record_auth_replaces_existing_protected_url_on_success(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)
    plugin = create_plugin(
        name="Replace URL",
        target_url="https://example.com/login",
        protected_url="https://example.com/old",
    )
    auth_path = tmp_path / "plugins" / plugin.id / "auth" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text("{}", encoding="utf-8")
    set_plugin_auth(plugin.id, "old-auth", str(auth_path))
    client = TestClient(app)

    reset = client.post(f"/api/v1/plugins/{plugin.id}/auth/re-record")
    assert reset.status_code == 200
    refreshed = get_plugin(plugin.id)
    assert refreshed is not None
    assert refreshed.protected_url == "https://example.com/old"

    auth_path.write_text("{}", encoding="utf-8")
    registry._sessions["auth-new-url"] = ClosedAuthSession("https://example.com/new?tab=1")
    try:
        response = client.post(
            f"/api/v1/plugins/{plugin.id}/auth/finalize",
            json={"session_id": "auth-new-url"},
        )
    finally:
        registry.pop("auth-new-url")

    assert response.status_code == 200
    refreshed = get_plugin(plugin.id)
    assert refreshed is not None
    assert refreshed.protected_url == "https://example.com/new?tab=1"


def test_workflow_recording_rejects_missing_protected_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)
    plugin = create_plugin(name="Missing URL", target_url="https://example.com/login")
    auth_path = tmp_path / "plugins" / plugin.id / "auth" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text("{}", encoding="utf-8")
    set_plugin_auth(plugin.id, "auth-session", str(auth_path))

    client = TestClient(app)
    response = client.post(
        f"/api/v1/plugins/{plugin.id}/workflows/record",
        json={"name": "Do work"},
    )

    assert response.status_code == 400
    assert "missing a protected URL" in response.json()["detail"]


def test_finalize_open_workflow_does_not_stop_browser(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)
    plugin = _ready_plugin(tmp_path)
    result = add_workflow(plugin.id, "Still open", session_id="open-session")
    assert result is not None
    _, workflow = result

    class OpenSession:
        browser_open = True
        stopped = False

        async def stop(self) -> None:
            self.stopped = True

        def snapshot_events(self) -> list[dict]:
            return [{"action": {"action": "click", "timestamp": "2026-01-01T00:00:00Z"}}]

    sess = OpenSession()
    registry._sessions["open-session"] = sess  # type: ignore[attr-defined]
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/plugins/{plugin.id}/workflows/{workflow.id}/finalize",
            json={"session_id": "open-session", "workflow_id": workflow.id},
        )
    finally:
        registry.pop("open-session")

    assert response.status_code == 409
    assert "Close Chromium before saving" in response.json()["detail"]
    assert sess.stopped is False
    assert get_plugin(plugin.id) is not None


def test_finalize_empty_workflow_removes_precreated_workflow(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)
    plugin = _ready_plugin(tmp_path)
    result = add_workflow(plugin.id, "Should not persist", session_id="empty-session")
    assert result is not None
    _, workflow = result

    client = TestClient(app)
    response = client.post(
        f"/api/v1/plugins/{plugin.id}/workflows/{workflow.id}/finalize",
        json={"session_id": "empty-session", "workflow_id": workflow.id},
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("No workflow actions were recorded")
    refreshed = get_plugin(plugin.id)
    assert refreshed is not None
    assert refreshed.workflows == []
