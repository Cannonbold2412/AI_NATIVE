"""Phase 1: LLM proxy metering + plugin publish / installer hosting."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from conxa_core.config import settings
from conxa_core.db import db_get, db_set
from conxa_core.storage.plugin_store import create_plugin, list_plugins
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
        {
            "path": "pack.json",
            "content_base64": base64.b64encode(
                b'{"company":"acme-test","tracking":{"tracking_url":"http://127.0.0.1:8000/api/tracking/acme-test/events"}}'
            ).decode(),
        },
        {"path": "deploy/execution.json", "content_base64": base64.b64encode(b'{"steps":[]}').decode()},
    ]
    r = client.post(
        "/api/v1/plugins/publish",
        json={
            "slug": "acme-test",
            "display_name": "Acme Test",
            "target_url": "https://acme.test",
            "protected_url": "https://acme.test/app",
            "skill_pack_version": "0.3.0",
            "skills": ["deploy"],
            "files": files,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "acme-test"
    assert body["files_written"] == 2
    assert body["tracking"]["tracking_url"].endswith("/api/tracking/acme-test/events")
    assert body["tracking"]["tracking_token"]
    assert db_get("tracking_tokens", "acme-test")["workspace_id"] == "wrk_local"
    assert any(p.slug == "acme-test" for p in list_plugins(workspace_id="wrk_local"))

    # The delta endpoint should now serve the published pack.
    d = client.get("/api/v1/skill-packs/acme-test/delta?since=0")
    assert d.status_code == 200
    assert d.json()["current_version"] == "0.3.0"

    companies = client.get("/api/v1/tracking/companies")
    assert companies.status_code == 200
    assert any(row["company"] == "acme-test" for row in companies.json()["companies"])


def test_publish_upsert_updates_existing_plugin_slug(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    existing = create_plugin(
        name="Render",
        target_url="https://dashboard.render.com",
        workspace_id="wrk_local",
    )
    assert existing.slug != "render"

    r = client.post(
        "/api/v1/plugins/publish",
        json={
            "slug": "render",
            "display_name": "Render",
            "target_url": "https://dashboard.render.com",
            "skill_pack_version": "1.0.0",
            "skills": [],
            "files": [],
        },
    )

    assert r.status_code == 200, r.text
    plugins = [p for p in list_plugins(workspace_id="wrk_local") if p.name == "Render"]
    assert len(plugins) == 1
    assert plugins[0].id == existing.id
    assert plugins[0].slug == "render"
    assert plugins[0].workspace_id == "wrk_local"


def test_skill_pack_delta_is_public_when_cloud_auth_required(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    packs_dir = tmp_path / "skill-packs" / "public-sync"
    packs_dir.mkdir(parents=True)
    (packs_dir / "pack.json").write_text(
        '{"company":"public-sync","skill_pack_version":"9.9.9","skills":[]}',
        encoding="utf-8",
    )

    r = client.get("/api/v1/skill-packs/public-sync/delta?since=0")

    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == "9.9.9"


def test_tracking_ingest_requires_published_token_and_lists_runs():
    pub = client.post(
        "/api/v1/plugins/publish",
        json={"slug": "track-test", "skill_pack_version": "1.0.0", "skills": [], "files": []},
    )
    assert pub.status_code == 200, pub.text
    token = pub.json()["tracking"]["tracking_token"]

    denied = client.post(
        "/api/tracking/track-test/events",
        json={"rid": "run-denied", "evts": [{"e": "wf_start", "ts": 1}]},
        headers={"X-Tracking-Token": "wrong"},
    )
    assert denied.status_code == 401

    accepted = client.post(
        "/api/tracking/track-test/events",
        json={
            "rid": "run-ok",
            "pid": "delete-a-service",
            "pv": "1.0.0",
            "rv": "1.0.0",
            "evts": [{"e": "wf_start", "ts": 1}, {"e": "wf_ok", "ts": 2, "dur": 10, "tot": 2, "rec": 0}],
        },
        headers={"X-Tracking-Token": token},
    )
    assert accepted.status_code == 202

    runs = client.get("/api/v1/tracking/track-test/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["run_id"] == "run-ok"


def test_tracking_runs_report_workspace_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db_set(
        "tracking_tokens",
        "workspace-hidden-test",
        {"token": "hidden-token", "workspace_id": "wrk_other", "version": "1.0.0"},
    )

    accepted = client.post(
        "/api/tracking/workspace-hidden-test/events",
        json={
            "rid": "run-hidden",
            "pid": "hidden-skill",
            "evts": [{"e": "wf_start", "ts": 1}],
        },
        headers={"X-Tracking-Token": "hidden-token"},
    )
    assert accepted.status_code == 202

    runs = client.get("/api/v1/tracking/workspace-hidden-test/runs")
    assert runs.status_code == 200
    body = runs.json()
    assert body["runs"] == []
    assert body["workspace_id"] == "wrk_local"
    assert body["total_all_workspaces"] == 1
    assert body["hidden_workspace_runs"] == 1


def test_tracking_companies_discovers_token_backed_events_without_plugin(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db_set(
        "tracking_tokens",
        "token-only-company",
        {
            "token": "token-only-secret",
            "company": "token-only-company",
            "workspace_id": "wrk_local",
            "version": "1.0.0",
            "updated_at": 10,
        },
    )

    accepted = client.post(
        "/api/tracking/token-only-company/events",
        json={"rid": "run-token-only", "pid": "skill-a", "evts": [{"e": "wf_start", "ts": 1}]},
        headers={"X-Tracking-Token": "token-only-secret"},
    )
    assert accepted.status_code == 202

    companies = client.get("/api/v1/tracking/companies")
    assert companies.status_code == 200
    row = next((r for r in companies.json()["companies"] if r["company"] == "token-only-company"), None)
    assert row is not None
    assert row["workspace_id"] == "wrk_local"
    assert row["run_count"] == 1
    assert row["last_seen"] > 0


def test_tracking_companies_hides_other_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db_set(
        "tracking_tokens",
        "other-workspace-company",
        {
            "token": "other-workspace-secret",
            "company": "other-workspace-company",
            "workspace_id": "wrk_other",
            "version": "1.0.0",
        },
    )

    accepted = client.post(
        "/api/tracking/other-workspace-company/events",
        json={"rid": "run-other", "pid": "skill-b", "evts": [{"e": "wf_start", "ts": 1}]},
        headers={"X-Tracking-Token": "other-workspace-secret"},
    )
    assert accepted.status_code == 202

    companies = client.get("/api/v1/tracking/companies")
    assert companies.status_code == 200
    assert all(row["company"] != "other-workspace-company" for row in companies.json()["companies"])


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


def test_installer_upload_allows_build_artifact_larger_than_json_cap():
    payload = b"MZ" + (b"x" * (settings.max_json_body_bytes + 1024))
    up = client.post(
        "/api/v1/plugins/big-dl-test/installer/upload?filename=Big-Setup.exe&version=1.2.0",
        content=payload,
    )
    assert up.status_code == 200, up.text
    assert up.json()["size"] == len(payload)


def test_installer_download_missing_is_404():
    r = client.get("/api/v1/installers/nope-not-here")
    assert r.status_code == 404
