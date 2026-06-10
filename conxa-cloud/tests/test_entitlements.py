from __future__ import annotations

from fastapi.testclient import TestClient

from conxa_core.config import settings
from conxa_core.db import db_set
from app.main import app
from app.services import llm_metering
from app.services.entitlements import current_period, usage_key
from app.services.saas import upsert_billing

client = TestClient(app)
STUDIO_HEADER = {"X-Conxa-Client": settings.llm_proxy_client_header}


def _set_plan(plan: str, **limits: int) -> None:
    patch: dict[str, object] = {"plan": plan}
    if limits:
        patch["entitlement_overrides"] = limits
    upsert_billing("wrk_local", patch)


def test_basic_plan_maps_to_starter(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    _set_plan("basic")

    r = client.get("/api/v1/entitlements/current")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "starter"
    assert body["meters"]["seats"]["limit"] == 3
    assert body["meters"]["installer_slots"]["limit"] == 3
    assert body["meters"]["compile_credits"]["limit"] == 300
    assert body["meters"]["human_edit_tokens"]["limit"] == 10_000_000


def test_compile_reserve_commit_release_idempotency(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "entitlements_enforce_compile", True)
    _set_plan("free")

    body = {
        "reservation_id": "cmp_test_one",
        "plugin_id": "plugin_1",
        "workflow_id": "wf_1",
        "session_id": "sess_1",
    }
    first = client.post("/api/v1/usage/compile/reserve", json=body)
    duplicate = client.post("/api/v1/usage/compile/reserve", json=body)
    commit = client.post("/api/v1/usage/compile/commit", json={"reservation_id": "cmp_test_one"})
    duplicate_commit = client.post("/api/v1/usage/compile/commit", json={"reservation_id": "cmp_test_one"})
    release_after_commit = client.post("/api/v1/usage/compile/release", json={"reservation_id": "cmp_test_one"})

    assert first.status_code == 200, first.text
    assert duplicate.status_code == 200, duplicate.text
    assert first.json()["remaining_compile_credits"] == 49
    assert duplicate.json()["remaining_compile_credits"] == 49
    assert commit.status_code == 200, commit.text
    assert duplicate_commit.status_code == 200, duplicate_commit.text
    assert release_after_commit.status_code == 200, release_after_commit.text
    assert release_after_commit.json()["status"] == "committed"

    entitlements = client.get("/api/v1/entitlements/current").json()
    assert entitlements["meters"]["compile_credits"]["used"] == 1
    assert entitlements["meters"]["compile_credits"]["remaining"] == 49


def test_compile_reserve_blocks_last_credit_concurrently(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "entitlements_enforce_compile", True)
    _set_plan("free", compile_credits=1)

    first = client.post("/api/v1/usage/compile/reserve", json={"reservation_id": "cmp_last_1"})
    second = client.post("/api/v1/usage/compile/reserve", json={"reservation_id": "cmp_last_2"})

    assert first.status_code == 200, first.text
    assert second.status_code == 402
    assert second.json()["detail"] == "compile_credit_limit_exceeded"


def test_expired_reservation_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "entitlements_enforce_compile", True)
    _set_plan("free", compile_credits=1)
    period = current_period()
    db_set(
        "compile_reservations",
        "cmp_expired",
        {
            "reservation_id": "cmp_expired",
            "workspace_id": "wrk_local",
            "period": period,
            "amount": 1,
            "status": "reserved",
            "expires_at": 1,
        },
    )

    reserve = client.post("/api/v1/usage/compile/reserve", json={"reservation_id": "cmp_after_expired"})

    assert reserve.status_code == 200, reserve.text
    assert reserve.json()["remaining_compile_credits"] == 0


def test_human_edit_pool_blocks_when_exhausted(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "entitlements_enforce_human_edit", True)
    _set_plan("free", human_edit_tokens=5)
    period = current_period()
    db_set(
        "entitlement_usage",
        usage_key("wrk_local", period),
        {
            "workspace_id": "wrk_local",
            "period": period,
            "human_edit_input_tokens": 5,
            "human_edit_output_tokens": 0,
        },
    )

    r = client.post(
        "/api/v1/llm/proxy/text",
        json={"task": "selector_repair", "payload": {"prompt": "x"}, "usage_class": "human_edit"},
        headers=STUDIO_HEADER,
    )

    assert r.status_code == 402
    assert r.json()["detail"] == "human_edit_pool_exceeded"


def test_compile_llm_usage_does_not_consume_human_edit_pool(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    _set_plan("free")
    from app.api import llm_proxy_routes

    class FakeRouter:
        def route_text(self, task, payload, timeout_ms, *, error_detail=None):
            return {"text": "ok"}

    before = llm_metering.get_usage("wrk_local")["requests"]
    monkeypatch.setattr(llm_proxy_routes, "get_router", lambda: FakeRouter())
    r = client.post(
        "/api/v1/llm/proxy/text",
        json={"task": "intent", "payload": {"prompt": "hello"}, "usage_class": "compile"},
        headers=STUDIO_HEADER,
    )

    assert r.status_code == 200, r.text
    assert llm_metering.get_usage("wrk_local")["requests"] == before + 1
    entitlements = client.get("/api/v1/entitlements/current").json()
    assert entitlements["meters"]["human_edit_tokens"]["used"] == 0


def test_installer_slots_block_new_slug_but_allow_same_slug_update(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "entitlements_enforce_installers", True)
    _set_plan("free", installer_slots=1)

    first = client.post(
        "/api/v1/plugins/slot-one/installer/upload?filename=Setup.exe&version=1.0.0&release_notes=First",
        content=b"MZfirst",
    )
    duplicate = client.post(
        "/api/v1/plugins/slot-one/installer/upload?filename=Setup.exe&version=1.0.0&release_notes=Duplicate",
        content=b"MZduplicate",
    )
    update = client.post(
        "/api/v1/plugins/slot-one/installer/upload?filename=Setup.exe&version=1.0.1&release_notes=Second",
        content=b"MZsecond",
    )
    blocked = client.post(
        "/api/v1/plugins/slot-two/installer/upload?filename=Setup.exe&version=1.0.0&release_notes=First",
        content=b"MZother",
    )

    assert first.status_code == 200, first.text
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "installer_version_exists"
    assert update.status_code == 200, update.text
    assert blocked.status_code == 402
    assert blocked.json()["detail"] == "installer_limit_exceeded"


def test_development_plan_is_unlimited(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "entitlements_enforce_compile", True)
    monkeypatch.setattr(settings, "entitlements_enforce_installers", True)
    _set_plan("development")

    entitlements = client.get("/api/v1/entitlements/current")
    reserve = client.post("/api/v1/usage/compile/reserve", json={"reservation_id": "cmp_dev"})

    assert entitlements.status_code == 200, entitlements.text
    assert entitlements.json()["meters"]["compile_credits"]["unlimited"] is True
    assert entitlements.json()["meters"]["installer_slots"]["unlimited"] is True
    assert reserve.status_code == 200, reserve.text
    assert reserve.json()["remaining_compile_credits"] is None
