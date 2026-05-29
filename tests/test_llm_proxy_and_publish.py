"""Phase 1: LLM proxy metering + plugin publish / installer hosting."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import llm_metering

client = TestClient(app)
STUDIO_HEADER = {"X-Conxa-Client": settings.llm_proxy_client_header}


@pytest.fixture(autouse=True)
def _reset_quota():
    original = settings.llm_proxy_monthly_token_quota
    yield
    settings.llm_proxy_monthly_token_quota = original


# --- LLM proxy ---------------------------------------------------------------

def test_proxy_requires_studio_header():
    r = client.post("/api/v1/llm/proxy/text", json={"task": "intent", "payload": {}})
    assert r.status_code == 403
    assert r.json()["detail"] == "proxy_requires_build_studio_client"


def test_proxy_forwards_and_meters(monkeypatch):
    from app.api import llm_proxy_routes

    class FakeRouter:
        def route_text(self, task, payload, timeout_ms, *, error_detail=None):
            return {"text": "ok", "output": "ok"}

    monkeypatch.setattr(llm_proxy_routes, "get_router", lambda: FakeRouter())
    settings.llm_proxy_monthly_token_quota = 1_000_000

    before = llm_metering.get_usage("wrk_local")["requests"]
    r = client.post(
        "/api/v1/llm/proxy/text",
        json={"task": "intent", "payload": {"prompt": "hello world"}},
        headers=STUDIO_HEADER,
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "ok"
    after = llm_metering.get_usage("wrk_local")["requests"]
    assert after == before + 1


def test_proxy_enforces_quota(monkeypatch):
    from app.api import llm_proxy_routes

    monkeypatch.setattr(llm_proxy_routes, "get_router", lambda: object())
    settings.llm_proxy_monthly_token_quota = 1
    # Push usage over the 1-token quota.
    llm_metering.record_usage("wrk_local", input_tokens=10, output_tokens=10)

    r = client.post(
        "/api/v1/llm/proxy/text",
        json={"task": "intent", "payload": {"prompt": "x"}},
        headers=STUDIO_HEADER,
    )
    assert r.status_code == 429
    assert r.json()["detail"] == "quota_exceeded"


# --- Publish + installer hosting --------------------------------------------

def test_publish_and_sync_roundtrip():
    files = [
        {"path": "deploy/execution.json", "content_base64": base64.b64encode(b'{"steps":[]}').decode()},
    ]
    r = client.post(
        "/api/v1/plugins/publish",
        json={"slug": "acme-test", "skill_pack_version": "0.3.0", "skills": ["deploy"], "files": files},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "acme-test"
    assert body["files_written"] == 1

    # The delta endpoint should now serve the published pack.
    d = client.get("/api/v1/skill-packs/acme-test/delta?since=0")
    assert d.status_code == 200
    assert d.json()["current_version"] == "0.3.0"


def test_publish_rejects_path_traversal():
    files = [{"path": "../escape.json", "content_base64": base64.b64encode(b"x").decode()}]
    r = client.post(
        "/api/v1/plugins/publish",
        json={"slug": "trav-test", "skill_pack_version": "1", "skills": [], "files": files},
    )
    assert r.status_code == 400
    assert "invalid_file_path" in r.json()["detail"]


def test_installer_upload_and_public_download():
    payload = b"MZ\x90\x00fake-exe-bytes"
    up = client.post(
        "/api/v1/plugins/dl-test/installer/upload?filename=Acme-Setup.exe&version=1.2.0",
        content=payload,
    )
    assert up.status_code == 200, up.text
    sha = up.json()["sha256"]

    dl = client.get("/api/v1/installers/dl-test")
    assert dl.status_code == 200
    assert dl.content == payload
    assert dl.headers["X-Conxa-SHA256"] == sha


def test_installer_download_missing_is_404():
    r = client.get("/api/v1/installers/nope-not-here")
    assert r.status_code == 404
