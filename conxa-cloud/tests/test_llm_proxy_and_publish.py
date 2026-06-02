"""Phase 1: LLM proxy metering + plugin publish / installer hosting."""

from __future__ import annotations

import base64
import time

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
    original_proxy_secret = settings.api_proxy_shared_secret
    yield
    settings.llm_proxy_monthly_token_quota = original
    settings.api_proxy_shared_secret = original_proxy_secret


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


def test_tracking_dashboard_empty_workspace_has_v1_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")

    dashboard = client.get("/api/v1/tracking/dashboard?range=30d")

    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["range"] == "30d"
    assert set(body["metrics"]) == {
        "total_installs",
        "active_users",
        "active_companies",
        "total_executions",
        "executions_last_24h",
        "success_rate",
        "failed_executions",
        "recovery_rate",
        "average_execution_time",
    }
    assert [row["type"] for row in body["recovery_type_usage"]] == [
        "Selector",
        "Text Anchor",
        "Text Variant",
        "Vision",
    ]
    assert body["recovery_usage_by_step"] == []
    assert body["recovery_usage_by_workflow"] == []
    assert "recent_activity" not in body
    assert len(body["execution_trend"]) == 30


def test_tracking_dashboard_aggregates_workspace_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    now_ms = int(time.time() * 1000)

    db_set("sync_tokens", "acme", {"token": "sync", "workspace_id": "wrk_local"})
    db_set(
        "tracking_tokens",
        "acme",
        {"token": "track-token", "company": "acme", "workspace_id": "wrk_local", "version": "1.0.0"},
    )
    db_set(
        "tracking_tokens",
        "hidden",
        {"token": "hidden-token", "company": "hidden", "workspace_id": "wrk_other", "version": "1.0.0"},
    )

    for install_id in ("install-a", "install-b"):
        telemetry = client.post(
            "/api/v1/telemetry/runtime-start",
            json={
                "runtime_version": "1.0.0",
                "companies": ["acme"],
                "platform": "win32",
                "install_id": install_id,
            },
        )
        assert telemetry.status_code == 200, telemetry.text

    ok = client.post(
        "/api/tracking/acme/events",
        json={
            "rid": "run-ok",
            "pid": "workflow-a",
            "uid": "install-a",
            "evts": [
                {"e": "wf_start", "ts": now_ms - 60_000},
                {"e": "rec_ok", "ts": now_ms - 50_000, "si": 0, "sc": "selector"},
                {"e": "tier_ok", "ts": now_ms - 49_000, "si": 0, "tier": "tier2_a11y"},
                {"e": "rec_ok", "ts": now_ms - 48_000, "si": 0, "sc": "text_variant"},
                {"e": "tier_ok", "ts": now_ms - 45_000, "si": 1, "tier": "tier2_a11y"},
                {"e": "rec_ok", "ts": now_ms - 40_000, "si": 2, "sc": "text_variant"},
                {"e": "rec_ok", "ts": now_ms - 35_000, "si": 3, "sc": "vision"},
                {"e": "wf_ok", "ts": now_ms - 30_000, "dur": 1200, "tot": 4, "rec": 1},
            ],
        },
        headers={"X-Tracking-Token": "track-token"},
    )
    assert ok.status_code == 202, ok.text

    fail = client.post(
        "/api/tracking/acme/events",
        json={
            "rid": "run-fail",
            "pid": "workflow-b",
            "uid": "install-b",
            "evts": [
                {"e": "wf_start", "ts": now_ms - 20_000},
                {"e": "step_fail", "ts": now_ms - 15_000, "si": 2, "fc": "timeout"},
                {"e": "wf_fail", "ts": now_ms - 10_000, "dur": 3000, "fsi": 2, "fc": "timeout"},
            ],
        },
        headers={"X-Tracking-Token": "track-token"},
    )
    assert fail.status_code == 202, fail.text

    hidden = client.post(
        "/api/tracking/hidden/events",
        json={
            "rid": "run-hidden",
            "pid": "hidden-workflow",
            "evts": [{"e": "wf_start", "ts": now_ms}, {"e": "wf_fail", "ts": now_ms, "dur": 1}],
        },
        headers={"X-Tracking-Token": "hidden-token"},
    )
    assert hidden.status_code == 202, hidden.text

    dashboard = client.get("/api/v1/tracking/dashboard?range=7d")
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()

    assert body["range"] == "7d"
    assert body["metrics"]["total_installs"] == 2
    assert body["metrics"]["active_users"] == 2
    assert body["metrics"]["active_companies"] == 1
    assert body["metrics"]["total_executions"] == 2
    assert body["metrics"]["executions_last_24h"] == 2
    assert body["metrics"]["success_rate"] == 50
    assert body["metrics"]["failed_executions"] == 1
    assert body["metrics"]["recovery_rate"] == 50
    assert body["metrics"]["average_execution_time"] == 2100

    recovery = {row["type"]: row["count"] for row in body["recovery_type_usage"]}
    assert recovery == {"Selector": 1, "Text Anchor": 2, "Text Variant": 2, "Vision": 1}
    recovery_by_step = {
        (row["workflow"], row["step_index"], row["recovery_type"]): row["count"]
        for row in body["recovery_usage_by_step"]
    }
    assert recovery_by_step == {
        ("workflow-a", 0, "Selector"): 1,
        ("workflow-a", 0, "Text Anchor"): 1,
        ("workflow-a", 0, "Text Variant"): 1,
        ("workflow-a", 1, "Text Anchor"): 1,
        ("workflow-a", 2, "Text Variant"): 1,
        ("workflow-a", 3, "Vision"): 1,
    }
    workflow_recovery = body["recovery_usage_by_workflow"][0]
    assert workflow_recovery["company"] == "acme"
    assert workflow_recovery["workflow"] == "workflow-a"
    assert workflow_recovery["count"] == 6
    step_zero = next(step for step in workflow_recovery["steps"] if step["step_index"] == 0)
    assert step_zero["total_count"] == 3
    assert {
        (row["tier"], row["recovery_type"]): row["count"]
        for row in step_zero["tier_counts"]
    } == {
        ("Tier 1", "Selector"): 1,
        ("Tier 2", "Text Anchor"): 1,
        ("Tier 3", "Text Variant"): 1,
    }
    assert body["most_failed_workflows"][0]["workflow"] == "workflow-b"
    assert body["most_failed_steps"][0]["step_index"] == 2
    assert sum(row["executions"] for row in body["execution_trend"]) == 2
    assert all(item["company"] != "hidden" for item in body["recovery_usage_by_step"])
    assert "recent_activity" not in body


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


def test_org_dashboard_sees_same_user_personal_publish(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "api_proxy_shared_secret", "proxy-secret")
    personal_headers = {
        "x-conxa-proxy-secret": "proxy-secret",
        "x-conxa-user-id": "user_same",
    }
    org_headers = {
        "x-conxa-proxy-secret": "proxy-secret",
        "x-conxa-user-id": "user_same",
        "x-conxa-org-id": "org_same",
    }

    pub = client.post(
        "/api/v1/plugins/publish",
        json={
            "slug": "personal-visible",
            "display_name": "Personal Visible",
            "target_url": "https://example.test",
            "skill_pack_version": "1.0.0",
            "skills": [],
            "files": [],
        },
        headers=personal_headers,
    )
    assert pub.status_code == 200, pub.text
    token_record = db_get("tracking_tokens", "personal-visible")
    assert token_record["workspace_id"] == "personal_user_same"
    assert token_record["owner_user_id"] == "user_same"

    accepted = client.post(
        "/api/tracking/personal-visible/events",
        json={
            "rid": "run-personal-visible",
            "pid": "skill-visible",
            "evts": [{"e": "wf_start", "ts": 1}, {"e": "wf_ok", "ts": 2, "dur": 10, "tot": 1, "rec": 0}],
        },
        headers={"X-Tracking-Token": pub.json()["tracking"]["tracking_token"]},
    )
    assert accepted.status_code == 202

    plugins = client.get("/api/v1/plugins", headers=org_headers)
    assert plugins.status_code == 200
    assert any(plugin["slug"] == "personal-visible" for plugin in plugins.json()["plugins"])

    companies = client.get("/api/v1/tracking/companies", headers=org_headers)
    assert companies.status_code == 200
    assert any(row["company"] == "personal-visible" for row in companies.json()["companies"])

    runs = client.get("/api/v1/tracking/personal-visible/runs", headers=org_headers)
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["run_id"] == "run-personal-visible"

    diagnostics = client.get("/api/v1/tracking/diagnostics", headers=org_headers)
    assert diagnostics.status_code == 200
    diagnostics_body = diagnostics.json()
    assert diagnostics_body["workspace_id"] == "org_same"
    assert diagnostics_body["personal_workspace_id"] == "personal_user_same"
    assert diagnostics_body["identity_source"] == "trusted_proxy"
    assert diagnostics_body["proxy_identity_trusted"] is True
    assert diagnostics_body["proxy_identity_status"] == "trusted"
    assert diagnostics_body["same_user_personal_company_count"] == 1


def test_org_dashboard_cannot_see_other_user_personal_publish(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "api_proxy_shared_secret", "proxy-secret")

    pub = client.post(
        "/api/v1/plugins/publish",
        json={
            "slug": "personal-hidden",
            "display_name": "Personal Hidden",
            "target_url": "https://example.test",
            "skill_pack_version": "1.0.0",
            "skills": [],
            "files": [],
        },
        headers={
            "x-conxa-proxy-secret": "proxy-secret",
            "x-conxa-user-id": "user_other",
        },
    )
    assert pub.status_code == 200, pub.text

    org_headers = {
        "x-conxa-proxy-secret": "proxy-secret",
        "x-conxa-user-id": "user_same",
        "x-conxa-org-id": "org_same",
    }
    plugins = client.get("/api/v1/plugins", headers=org_headers)
    assert plugins.status_code == 200
    assert all(plugin["slug"] != "personal-hidden" for plugin in plugins.json()["plugins"])

    companies = client.get("/api/v1/tracking/companies", headers=org_headers)
    assert companies.status_code == 200
    assert all(row["company"] != "personal-hidden" for row in companies.json()["companies"])


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
        "/api/v1/plugins/dl-test/installer/upload?filename=Acme-Setup.exe&version=1.2.0&release_notes=Initial%20release",
        content=payload,
    )
    assert up.status_code == 200, up.text
    sha = up.json()["sha256"]
    assert up.json()["version_download_url"] == "/api/v1/installers/dl-test/versions/1.2.0"

    dl = client.get("/api/v1/installers/dl-test")
    assert dl.status_code == 200
    assert dl.content == payload
    assert dl.headers["X-Conxa-SHA256"] == sha

    exact = client.get("/api/v1/installers/dl-test/versions/1.2.0")
    assert exact.status_code == 200
    assert exact.content == payload


def test_installer_upload_allows_build_artifact_larger_than_json_cap():
    payload = b"MZ" + (b"x" * (settings.max_json_body_bytes + 1024))
    up = client.post(
        "/api/v1/plugins/big-dl-test/installer/upload?filename=Big-Setup.exe&version=1.2.0&release_notes=Large%20installer",
        content=payload,
    )
    assert up.status_code == 200, up.text
    assert up.json()["size"] == len(payload)


def test_installer_upload_rejects_duplicate_version_and_preserves_history():
    first = b"MZfirst"
    second = b"MZsecond"
    slug = "versioned-dl-test"

    up1 = client.post(
        f"/api/v1/plugins/{slug}/installer/upload?filename=Versioned-Setup.exe&version=1.2.0&release_notes=First%20release",
        content=first,
    )
    assert up1.status_code == 200, up1.text

    duplicate = client.post(
        f"/api/v1/plugins/{slug}/installer/upload?filename=Versioned-Setup.exe&version=1.2.0&release_notes=Duplicate",
        content=second,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "installer_version_exists"

    up2 = client.post(
        f"/api/v1/plugins/{slug}/installer/upload?filename=Versioned-Setup.exe&version=1.2.1&release_notes=Second%20release",
        content=second,
    )
    assert up2.status_code == 200, up2.text

    latest = client.get(f"/api/v1/installers/{slug}")
    assert latest.status_code == 200
    assert latest.content == second

    old = client.get(f"/api/v1/installers/{slug}/versions/1.2.0")
    assert old.status_code == 200
    assert old.content == first

    versions = client.get(f"/api/v1/plugins/{slug}/installer/versions")
    assert versions.status_code == 200, versions.text
    rows = versions.json()["versions"]
    assert [row["version"] for row in rows[:2]] == ["1.2.1", "1.2.0"]
    assert rows[0]["is_latest"] is True
    assert rows[0]["release_notes"] == "Second release"
    assert rows[1]["is_latest"] is False


def test_installer_upload_updates_plugin_latest_metadata():
    slug = "plugin-meta-installer"
    pub = client.post(
        "/api/v1/plugins/publish",
        json={
            "slug": slug,
            "display_name": "Plugin Meta Installer",
            "target_url": "https://example.test",
            "skill_pack_version": "1.0.0",
            "skills": [],
            "files": [],
        },
    )
    assert pub.status_code == 200, pub.text

    up = client.post(
        f"/api/v1/plugins/{slug}/installer/upload?filename=Meta-Setup.exe&version=1.4.0&release_notes=Dashboard%20release",
        content=b"MZmeta",
    )
    assert up.status_code == 200, up.text

    plugins = client.get("/api/v1/plugins")
    assert plugins.status_code == 200
    plugin = next(row for row in plugins.json()["plugins"] if row["slug"] == slug)
    assert plugin["installer"]["version"] == "1.4.0"
    assert plugin["installer"]["release_notes"] == "Dashboard release"


def test_installer_download_missing_is_404():
    r = client.get("/api/v1/installers/nope-not-here")
    assert r.status_code == 404
