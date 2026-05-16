"""Tests for publish_routes — OAuth status and publish preview endpoints."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture()
def client():
    with patch.object(settings, "auth_required", False):
        yield TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# GitHub status
# ─────────────────────────────────────────────────────────────────────────────


def test_github_status_disconnected(client):
    with patch("app.api.publish_routes.get_status", return_value={"connected": False, "login": None, "scopes": None}):
        resp = client.get("/api/v1/integrations/github/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["login"] is None


def test_github_status_connected(client):
    with patch(
        "app.api.publish_routes.get_status",
        return_value={"connected": True, "login": "testuser", "scopes": ["repo", "read:user"]},
    ):
        resp = client.get("/api/v1/integrations/github/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["login"] == "testuser"


def test_github_disconnect(client):
    with patch("app.api.publish_routes.revoke") as mock_revoke:
        resp = client.post("/api/v1/integrations/github/disconnect")
    assert resp.status_code == 200
    mock_revoke.assert_called_once()


def test_github_connect_uses_configured_client_id(client):
    with patch.object(settings, "github_oauth_client_id", "test-client-id"):
        resp = client.get("/api/v1/integrations/github/connect", follow_redirects=False)
    assert resp.status_code == 302
    params = parse_qs(urlparse(resp.headers["location"]).query)
    assert params["client_id"] == ["test-client-id"]


def test_github_callback_public_when_auth_required():
    with patch.object(settings, "auth_required", True):
        with TestClient(app, raise_server_exceptions=False) as auth_client:
            resp = auth_client.get("/api/v1/integrations/github/callback?error=access_denied")
    assert resp.status_code == 200
    assert "github-oauth-error" in resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Publish preview
# ─────────────────────────────────────────────────────────────────────────────


def test_publish_preview_not_found(client):
    with patch("app.api.publish_routes.get_plugin", return_value=None):
        resp = client.get("/api/v1/plugins/nonexistent/publish/preview")
    assert resp.status_code == 404


def test_publish_preview_no_build(client):
    from app.models.plugin import Plugin

    plugin = Plugin(
        id="p1",
        slug="test-p",
        name="Test Plugin",
        target_url="https://example.com",
        protected_url="https://example.com/dashboard",
        build=None,
    )
    with patch("app.api.publish_routes.get_plugin", return_value=plugin):
        resp = client.get("/api/v1/plugins/p1/publish/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_status"] == "unlinked"
    assert data["has_build"] is False
    assert "next_versions" in data
    assert "patch" in data["next_versions"]


def test_publish_preview_with_build(client, tmp_path):
    from app.models.plugin import Plugin, PluginBuild

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "plugin.json").write_text("{}")

    plugin = Plugin(
        id="p2",
        slug="my-plugin",
        name="My Plugin",
        target_url="https://example.com",
        protected_url="https://example.com/dashboard",
        build=PluginBuild(
            last_built_at=time.time(),
            output_path=str(bundle),
            version="0.1.0",
        ),
        repository_url="https://github.com/user/my-plugin",
        last_published_version="0.1.0",
    )
    with patch("app.api.publish_routes.get_plugin", return_value=plugin):
        resp = client.get("/api/v1/plugins/p2/publish/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_status"] == "linked"
    assert data["has_build"] is True
    assert data["current_version"] == "0.1.0"
    assert "plugin.json" in data["bundle_files"]


# ─────────────────────────────────────────────────────────────────────────────
# Publish endpoint guards
# ─────────────────────────────────────────────────────────────────────────────


def test_publish_requires_build(client):
    from app.models.plugin import Plugin

    plugin = Plugin(
        id="p3",
        slug="test",
        name="Test",
        target_url="https://example.com",
        protected_url="https://example.com/dashboard",
        build=None,
    )
    with patch("app.api.publish_routes.get_plugin", return_value=plugin):
        resp = client.post("/api/v1/plugins/p3/publish", json={"version_bump": "patch"})
    assert resp.status_code == 400
    assert "built" in resp.json()["detail"].lower()


def test_publish_requires_github_connection(client):
    from app.models.plugin import Plugin, PluginBuild

    plugin = Plugin(
        id="p4",
        slug="test",
        name="Test",
        target_url="https://example.com",
        protected_url="https://example.com/dashboard",
        build=PluginBuild(last_built_at=time.time(), output_path="/fake", version="0.1.0"),
    )
    with patch("app.api.publish_routes.get_plugin", return_value=plugin):
        with patch(
            "app.api.publish_routes.get_status",
            return_value={"connected": False, "login": None, "scopes": None},
        ):
            resp = client.post("/api/v1/plugins/p4/publish", json={"version_bump": "patch"})
    assert resp.status_code == 401


def test_publish_version_already_published(client):
    from app.models.plugin import Plugin, PluginBuild
    from app.services.github_publisher import VersionAlreadyPublished

    plugin = Plugin(
        id="p5",
        slug="test",
        name="Test",
        target_url="https://example.com",
        protected_url="https://example.com/dashboard",
        build=PluginBuild(last_built_at=time.time(), output_path="/fake", version="0.1.0"),
    )
    with patch("app.api.publish_routes.get_plugin", return_value=plugin):
        with patch(
            "app.api.publish_routes.get_status",
            return_value={"connected": True, "login": "user", "scopes": ["repo"]},
        ):
            with patch(
                "app.api.publish_routes.publish",
                side_effect=VersionAlreadyPublished("Version v0.1.1 already published"),
            ):
                resp = client.post("/api/v1/plugins/p5/publish", json={"version_bump": "patch"})
    assert resp.status_code == 409
    assert "already published" in resp.json()["detail"].lower()
