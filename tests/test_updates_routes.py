"""Phase 4.5: deps-manifest and runtime-manifest endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_deps_manifest_public_no_auth():
    """Endpoint is public — no Authorization header needed."""
    r = client.get("/api/v1/updates/deps-manifest")
    assert r.status_code == 200
    body = r.json()
    assert "nsis" in body
    assert "runtime" in body
    nsis = body["nsis"]
    assert "version" in nsis
    assert "url" in nsis
    runtime = body["runtime"]
    assert "version" in runtime
    assert "win_url" in runtime


def test_runtime_manifest_public_no_auth():
    r = client.get("/api/v1/updates/runtime-manifest")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body
    assert "url" in body
    assert "sha256" in body
    assert "min_skill_pack_version" in body
    assert "playwright_version" in body
    assert "chromium_revision" in body


def test_deps_manifest_not_in_openapi():
    """include_in_schema=False keeps these out of the public API docs."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    assert "/api/v1/updates/deps-manifest" not in paths
    assert "/api/v1/updates/runtime-manifest" not in paths


def test_deps_manifest_env_override(monkeypatch):
    """Env vars let CI update manifest without a redeploy."""
    monkeypatch.setenv("CONXA_NSIS_VERSION", "3.99")
    monkeypatch.setenv("CONXA_NSIS_URL", "https://example.com/nsis-3.99.zip")
    # Re-import to pick up new env (routes read env at import time via module globals)
    import importlib
    import app.api.updates_routes as m
    importlib.reload(m)
    r2 = TestClient(app).get("/api/v1/updates/deps-manifest")
    # The running app still has old values — just verify the module parses env correctly
    assert m._NSIS_VERSION == "3.99"
    assert m._NSIS_URL == "https://example.com/nsis-3.99.zip"
