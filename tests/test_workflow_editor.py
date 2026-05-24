"""Workflow editor API, DTO mapping, patch gate, and assets path resolution."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


def _minimal_skill_doc(skill_id: str = "skill_test_editor") -> dict:
    return {
        "meta": {
            "id": skill_id,
            "version": 1,
            "title": "Test",
            "created_at": "2026-01-01T00:00:00Z",
            "source_session_id": None,
            "compiler_policy_version": "",
            "compiler_policy_hash": "",
        },
        "inputs": [{"id": "svc", "label": "Service", "type": "text", "default": "conxa-web"}],
        "skills": [
            {
                "name": "default",
                "steps": [
                    {
                        "action": {"action": "click"},
                        "intent": "click_submit_button",
                        "target": {
                            "primary_selector": "#submit",
                            "fallback_selectors": [],
                            "role": "button",
                            "type": "button",
                        },
                        "signals": {
                            "dom": {"tag": "button", "inner_text": "Submit"},
                            "selectors": {"css": "#submit", "aria": "", "text_based": "", "xpath": ""},
                            "semantic": {"final_intent": "click_submit_button", "llm_intent": "click_submit_button"},
                            "context": {"page_url": "https://example.com", "page_title": "Ex"},
                            "anchors": [{"kind": "text", "value": "Submit"}],
                            "visual": {
                                "full_screenshot": "images/evt_0001_full.jpg",
                                "bbox": {"x": 1, "y": 2, "w": 10, "h": 20},
                            },
                        },
                        "validation": {
                            "wait_for": {"type": "element_appear", "target": "#submit", "timeout": 5000},
                            "success_conditions": {},
                        },
                        "recovery": {
                            "intent": "click_submit_button",
                            "final_intent": "click_submit_button",
                            "anchors": [],
                            "strategies": ["semantic match"],
                        },
                        "confidence_protocol": {},
                        "decision_policy": {},
                    }
                ],
            }
        ],
        "policies": {},
        "llm": {},
    }


def _write_session_events(data_dir: Path, session_id: str, events: list[dict]) -> None:
    session_dir = data_dir / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(40):
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"succeeded", "failed", "canceled"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish")


def test_compile_updated_job_rebuilds_same_skill_from_raw_recording(tmp_path, monkeypatch) -> None:
    from app.config import settings
    from app.main import app
    from app.storage.json_store import read_skill, write_skill
    import app.api.workflow_routes as workflow_routes

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)

    skill_id = "skill_recompile_from_raw"
    session_id = "sess_recompile_from_raw"
    write_skill(skill_id, _minimal_skill_doc(skill_id))
    original = read_skill(skill_id)
    assert original is not None
    original["meta"]["source_session_id"] = session_id
    original["meta"]["version"] = 3
    original["skills"][0]["steps"][0]["target"]["primary_selector"] = "#edited"
    write_skill(skill_id, original)

    _write_session_events(
        tmp_path,
        session_id,
        [{"action": {"action": "click"}, "extras": {"session_id": session_id}}],
    )

    def fake_compile_skill_package(normalized, *, skill_id, source_session_id, title, version):
        return SimpleNamespace(
            skills=[SimpleNamespace(steps=[SimpleNamespace(action={"action": "click"}, signals={})])],
            model_dump=lambda mode="json": {
                "meta": {
                    "id": skill_id,
                    "version": version,
                    "title": title,
                    "created_at": "2026-01-01T00:00:00Z",
                    "source_session_id": source_session_id,
                },
                "inputs": [],
                "skills": [
                    {
                        "name": "recorded",
                        "steps": [
                            {
                                "action": {"action": "click"},
                                "target": {"primary_selector": "#fresh-from-raw"},
                                "signals": {},
                            }
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(workflow_routes, "run_pipeline", lambda raw: raw)
    monkeypatch.setattr(workflow_routes, "compile_skill_package", fake_compile_skill_package)
    monkeypatch.setattr(workflow_routes, "_build_audit_report", lambda steps: ([], []))

    client = TestClient(app)
    response = client.post(f"/api/v1/jobs/skills/{skill_id}/compile-updated", json={"skill_title": None})
    assert response.status_code == 200

    job = _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"
    assert job["result"]["skill_id"] == skill_id
    assert job["result"]["version"] == 4

    rebuilt = read_skill(skill_id)
    assert rebuilt is not None
    assert rebuilt["meta"]["id"] == skill_id
    assert rebuilt["meta"]["source_session_id"] == session_id
    assert rebuilt["meta"]["version"] == 4
    assert rebuilt["skills"][0]["steps"][0]["target"]["primary_selector"] == "#fresh-from-raw"


def test_compile_updated_rejects_missing_raw_recording(tmp_path, monkeypatch) -> None:
    from app.config import settings
    from app.main import app
    from app.storage.json_store import write_skill

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "auth_required", False)

    skill_id = "skill_missing_raw_recording"
    doc = _minimal_skill_doc(skill_id)
    doc["meta"]["source_session_id"] = "missing-session"
    write_skill(skill_id, doc)

    client = TestClient(app)
    response = client.post(f"/api/v1/skills/{skill_id}/compile-updated", json={"skill_title": None})

    assert response.status_code == 409
    assert response.json()["detail"] == "session_events_missing_cannot_full_recompile"


class WorkflowEditorTests(unittest.TestCase):
    def test_resolve_skill_asset_rejects_traversal(self) -> None:
        from app.editor.assets import resolve_skill_asset

        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "images").mkdir(parents=True)
            (t / "images" / "ok.jpg").write_bytes(b"x")
            with patch("app.editor.assets.settings") as s:
                s.data_dir = t
                p = resolve_skill_asset("images/ok.jpg")
                self.assertTrue(p.is_file())
            with patch("app.editor.assets.settings") as s:
                s.data_dir = t
                with self.assertRaises(ValueError):
                    resolve_skill_asset("../images/ok.jpg")

    def test_build_workflow_contains_description(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="/api/v1")
        self.assertEqual(len(wf.steps), 1)
        self.assertIn("Click", wf.steps[0].human_readable_description)
        self.assertTrue(wf.steps[0].screenshot.full_url.startswith("/api/v1/skills/"))
        self.assertEqual(
            wf.steps[0].anchors_signals,
            [{"element": "Submit", "relation": "near"}],
        )

    def test_build_workflow_surfaces_frame_context(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        doc["skills"][0]["steps"][0]["frame"] = {
            "chain": [
                {
                    "selector": 'iframe[id="object-builder-ui"]',
                    "fallback_selectors": ['iframe[data-test-id="object-builder-ui-iframe"]'],
                    "url": "https://app-na2.hubspot.com/object-builder/246242636/0-1/embed?",
                    "url_pattern": "^https://app\\-na2\\.hubspot\\.com/object\\-builder/[^/]+/0\\-1/embed$",
                }
            ]
        }

        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="/api/v1")

        self.assertEqual(wf.steps[0].frame["chain"][0]["selector"], 'iframe[id="object-builder-ui"]')

    def test_apply_step_patch_allows_frame_context(self) -> None:
        from app.compiler.patch import apply_step_patch
        from app.editor.patch_gate import validate_editor_patch
        from app.policy.bundle import get_policy_bundle

        doc = _minimal_skill_doc()
        patch_payload = {
            "frame": {
                "chain": [
                    {
                        "selector": 'iframe[id="object-builder-ui"]',
                        "fallback_selectors": ['iframe[data-test-id="object-builder-ui-iframe"]'],
                        "url": "https://app-na2.hubspot.com/object-builder/246242636/0-1/embed?",
                        "url_pattern": "^https://app\\-na2\\.hubspot\\.com/object\\-builder/[^/]+/0\\-1/embed$",
                    }
                ]
            }
        }
        validate_editor_patch(doc["skills"][0]["steps"][0], patch_payload, get_policy_bundle().data)

        patched = apply_step_patch(doc, 0, patch_payload, assist_llm=False)

        self.assertEqual(
            patched["skills"][0]["steps"][0]["frame"]["chain"][0]["selector"],
            'iframe[id="object-builder-ui"]',
        )

    def test_build_workflow_surfaces_vision_anchor_fallback_suggestion(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        doc["skills"][0]["steps"][0]["confidence_protocol"] = {
            "compile_warnings": {
                "vision_anchor_fallback": {
                    "reason": "vision_llm_request_failed",
                    "step_index": 0,
                    "fallback": "deterministic_anchors",
                }
            }
        }

        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="/api/v1")
        match = next((item for item in wf.suggestions if item.code == "vision_anchor_fallback"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match.step_index, 0)
        self.assertEqual(match.severity, "warn")

    def test_workflow_response_does_not_backfill_initial_navigate_step(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="/api/v1")
        self.assertEqual(len(wf.steps), 1)
        self.assertEqual(wf.steps[0].action_type, "click")

    def test_build_workflow_rewrites_legacy_image_path_with_source_session(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        doc["meta"]["source_session_id"] = "sess_123"
        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="/api/v1")
        full_url = wf.steps[0].screenshot.full_url or ""
        self.assertIn("path=sessions%2Fsess_123%2Fimages%2Fevt_0001_full.jpg", full_url)

    def test_url_check_workflow_does_not_surface_anchors(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        step = doc["skills"][0]["steps"][0]
        step["action"] = {"action": "check"}
        step["intent"] = "check_url_contains_dashboard"
        step["check_kind"] = "url"
        step["check_pattern"] = "/dashboard"
        step["signals"]["anchors"] = [{"element": "Dashboard", "relation": "above"}]
        step["recovery"]["anchors"] = [{"element": "Dashboard", "relation": "above"}]

        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="/api/v1")
        self.assertEqual(wf.steps[0].action_type, "check")
        self.assertEqual(wf.steps[0].check_kind, "url")
        self.assertEqual(wf.steps[0].anchors_signals, [])
        self.assertEqual(wf.steps[0].anchors_recovery, [])

    def test_url_exact_check_workflow_does_not_surface_anchors(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        step = doc["skills"][0]["steps"][0]
        step["action"] = {"action": "check"}
        step["intent"] = "check_url_must_be_dashboard"
        step["check_kind"] = "url_exact"
        step["check_pattern"] = "https://example.com/dashboard"
        step["signals"]["anchors"] = [{"element": "Dashboard", "relation": "above"}]
        step["recovery"]["anchors"] = [{"element": "Dashboard", "relation": "above"}]

        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="/api/v1")
        self.assertEqual(wf.steps[0].action_type, "check")
        self.assertEqual(wf.steps[0].check_kind, "url_exact")
        self.assertEqual(wf.steps[0].anchors_signals, [])
        self.assertEqual(wf.steps[0].anchors_recovery, [])

    def test_workflow_click_description_prefers_parameterized_primary_selector(self) -> None:
        """Sidebar copy uses describe_step(); it must reflect {{var}} in primary_selector, not frozen DOM text."""
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        step = doc["skills"][0]["steps"][0]
        step["target"]["primary_selector"] = "{{db_name}}"
        step["signals"]["dom"]["inner_text"] = "conxa-db"
        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="http://localhost:8000")
        self.assertIn("{{db_name}}", wf.steps[0].human_readable_description)
        self.assertNotIn("conxa-db", wf.steps[0].human_readable_description)

    def test_workflow_click_description_unwraps_playwright_text_locator(self) -> None:
        """text="..." wrappers should not appear verbatim in sidebar copy (nested quotes)."""
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        step = doc["skills"][0]["steps"][0]
        step["target"]["primary_selector"] = 'text="{{db_name}}"'
        step["signals"]["dom"]["inner_text"] = "conxa-db"
        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="http://localhost:8000")
        desc = wf.steps[0].human_readable_description
        self.assertIn("{{db_name}}", desc)
        self.assertNotIn("text=", desc)
        self.assertNotIn("conxa-db", desc)

    def test_workflow_hover_description_uses_hover_copy(self) -> None:
        from app.editor.workflow_service import build_workflow_response

        doc = _minimal_skill_doc()
        step = doc["skills"][0]["steps"][0]
        step["action"]["action"] = "hover"
        step["intent"] = "hover_menu_item"
        step["signals"]["dom"]["inner_text"] = "CRM"
        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="http://localhost:8000")
        self.assertIn('Hover over "CRM"', wf.steps[0].human_readable_description)

    def test_apply_step_patch_assist_llm_false_skips_enrich(self) -> None:
        from app.compiler.patch import apply_step_patch

        doc = _minimal_skill_doc()
        with patch("app.compiler.patch.enrich_semantic") as es:
            apply_step_patch(doc, 0, {"target": {"primary_selector": "#go2"}}, assist_llm=False)
            es.assert_not_called()

    def test_apply_step_patch_normalizes_legacy_anchor_schema(self) -> None:
        from app.compiler.patch import apply_step_patch

        doc = _minimal_skill_doc()
        updated = apply_step_patch(
            doc,
            0,
            {
                "signals": {"anchors": [{"kind": "text", "value": "Confirm"}]},
                "recovery": {"anchors": [{"type": "above", "text": "Password"}]},
            },
            assist_llm=False,
        )
        step = updated["skills"][0]["steps"][0]
        self.assertEqual(step["signals"]["anchors"], [{"element": "Confirm", "relation": "near"}])
        self.assertEqual(step["recovery"]["anchors"], [{"element": "Password", "relation": "above"}])

    def test_apply_step_patch_ignores_url_state(self) -> None:
        from app.compiler.patch import apply_step_patch

        doc = _minimal_skill_doc()
        updated = apply_step_patch(
            doc,
            0,
            {
                "url_state": {
                    "before": {"url_pattern": "^https://example\\.com$"},
                    "after": {"url_pattern": "^https://example\\.com/done$"},
                },
            },
            assist_llm=False,
        )
        self.assertNotIn("url_state", updated["skills"][0]["steps"][0])

    def test_validate_editor_patch_rejects_bad_selector(self) -> None:
        from app.editor.patch_gate import validate_editor_patch

        step = dict(_minimal_skill_doc()["skills"][0]["steps"][0])
        policy = {}
        with self.assertRaises(ValueError):
            validate_editor_patch(step, {"target": {"primary_selector": "bareword"}}, policy)

    def test_list_skills_endpoint(self) -> None:
        from app.main import app
        from app.config import settings
        from app.storage import json_store

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            p.mkdir(parents=True, exist_ok=True)
            with patch.object(json_store, "skills_dir", return_value=p):
                with patch.object(settings, "auth_required", False):
                    client = TestClient(app)
                    r = client.get("/api/v1/skills")
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(r.json().get("skills"), [])
                    (p / "skill_list_test.json").write_text(
                        json.dumps(_minimal_skill_doc("skill_list_test")),
                        encoding="utf-8",
                    )
                    r2 = client.get("/api/v1/skills")
                    self.assertEqual(r2.status_code, 200)
                    rows = r2.json().get("skills") or []
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["skill_id"], "skill_list_test")

    def test_workflow_api_get_and_patch(self) -> None:
        from app.main import app
        from app.config import settings
        from app.storage import json_store

        skill_id = "skill_workflow_api_test"
        doc = _minimal_skill_doc(skill_id)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            p.mkdir(parents=True, exist_ok=True)
            with patch.object(json_store, "skills_dir", return_value=p):
                (p / f"{skill_id}.json").write_text(json.dumps(doc), encoding="utf-8")
                with patch.object(settings, "auth_required", False):
                    client = TestClient(app)
                    r = client.get(f"/api/v1/skills/{skill_id}/workflow")
                    self.assertEqual(r.status_code, 200)
                    data = r.json()
                    self.assertEqual(data["skill_id"], skill_id)
                    self.assertEqual(len(data["steps"]), 1)
                    self.assertEqual(data["steps"][0]["action_type"], "click")
                    self.assertTrue(data["steps"][0]["screenshot"]["full_url"].startswith("/api/v1/skills/"))

                    r_api = client.get(f"/api/v1/skills/{skill_id}/workflow")
                    self.assertEqual(r_api.status_code, 200)
                    data_api = r_api.json()
                    self.assertTrue(data_api["steps"][0]["screenshot"]["full_url"].startswith("/api/v1/skills/"))

                    pr = client.patch(
                        f"/api/v1/skills/{skill_id}/steps/0",
                        json={"patch": {"target": {"primary_selector": "#submit"}}, "assist_llm": False},
                    )
                    self.assertEqual(pr.status_code, 200)
                    self.assertEqual(pr.json()["meta"]["version"], 2)

                    add = client.post(
                        f"/api/v1/skills/{skill_id}/steps",
                        json={"action_kind": "fill", "insert_after": 0},
                    )
                    self.assertEqual(add.status_code, 200)
                    added = add.json()
                    self.assertEqual(added["workflow"]["steps"][1]["action_type"], "fill")
                    self.assertEqual(added["workflow"]["steps"][1]["value"], "")

    def test_reorder_and_delete(self) -> None:
        from app.editor.workflow_service import delete_step_at, insert_step_after, reorder_steps

        doc = _minimal_skill_doc()
        s2 = dict(doc["skills"][0]["steps"][0])
        s2["intent"] = "second_step"
        doc["skills"][0]["steps"].append(s2)
        r = reorder_steps(doc, [1, 0])
        self.assertEqual(r["skills"][0]["steps"][0]["intent"], "second_step")
        d = delete_step_at(r, 0)
        self.assertEqual(len(d["skills"][0]["steps"]), 1)
        self.assertEqual(d["skills"][0]["steps"][0]["intent"], "click_submit_button")
        inserted = insert_step_after(d, "scroll", 0)
        self.assertEqual(len(inserted["skills"][0]["steps"]), 2)
        self.assertEqual(inserted["skills"][0]["steps"][1]["action"]["action"], "scroll")
        self.assertEqual(inserted["skills"][0]["steps"][1]["action"]["delta"], 600)
        inserted_hover = insert_step_after(d, "hover", 0)
        self.assertEqual(inserted_hover["skills"][0]["steps"][1]["action"]["action"], "hover")
        self.assertEqual(inserted_hover["skills"][0]["steps"][1]["intent"], "hover_target")

    def test_action_registry_covers_recorder_and_structured_actions(self) -> None:
        from typing import get_args

        from app.editor.action_registry import ACTION_KIND_ORDER, action_spec_dict
        from app.models.events import ActionKind
        from app.services.skill_pack.common import _ALLOWED_STRUCTURED_TYPES

        registered = set(ACTION_KIND_ORDER)
        self.assertTrue(set(get_args(ActionKind)).issubset(registered))
        self.assertTrue(set(_ALLOWED_STRUCTURED_TYPES).issubset(registered))
        self.assertTrue(action_spec_dict("dblclick")["insertable"])
        self.assertTrue(action_spec_dict("download_observed")["marker"])

    def test_insert_step_after_supports_extended_actions_and_rejects_markers(self) -> None:
        from app.editor.workflow_service import insert_step_after

        doc = _minimal_skill_doc()
        inserted = insert_step_after(doc, "dblclick", 0)
        self.assertEqual(inserted["skills"][0]["steps"][1]["action"]["action"], "dblclick")

        inserted_wait = insert_step_after(doc, "wait", 0)
        wait_step = inserted_wait["skills"][0]["steps"][1]
        self.assertEqual(wait_step["action"]["action"], "wait")
        self.assertEqual(wait_step["action"]["ms"], 1000)
        self.assertEqual(wait_step["value"], "1000")

        with self.assertRaises(ValueError):
            insert_step_after(doc, "download_observed", 0)

    def test_replace_string_literals_in_skill_document(self) -> None:
        from app.editor.workflow_service import replace_string_literals_in_skill_document

        doc = _minimal_skill_doc()
        doc["skills"][0]["steps"][0]["signals"]["dom"]["inner_text"] = "Host conxa-db ok"
        doc["skills"][0]["steps"][0]["signals"]["context"]["page_url"] = "https://conxa-db.example.com"
        doc["inputs"][0]["label"] = "Service conxa-db"

        out = replace_string_literals_in_skill_document(doc, "conxa-db", "{{db_name}}")
        self.assertEqual(out["skills"][0]["steps"][0]["signals"]["dom"]["inner_text"], "Host {{db_name}} ok")
        self.assertEqual(
            out["skills"][0]["steps"][0]["signals"]["context"]["page_url"],
            "https://{{db_name}}.example.com",
        )
        self.assertEqual(out["inputs"][0]["label"], "Service {{db_name}}")
        self.assertGreater(int(out["meta"]["version"]), int(doc["meta"]["version"]))  # type: ignore[arg-type]

    def test_workflow_replace_literals_api(self) -> None:
        from app.main import app
        from app.config import settings
        from app.storage import json_store

        skill_id = "skill_replace_literals_test"
        doc = _minimal_skill_doc(skill_id)
        doc["skills"][0]["steps"][0]["signals"]["dom"]["inner_text"] = "Use conxa-db here"
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            p.mkdir(parents=True, exist_ok=True)
            with patch.object(json_store, "skills_dir", return_value=p):
                (p / f"{skill_id}.json").write_text(json.dumps(doc), encoding="utf-8")
                with patch.object(settings, "auth_required", False):
                    client = TestClient(app)
                    pr = client.post(
                        f"/api/v1/skills/{skill_id}/workflow:replace-literals",
                        json={"find": "conxa-db", "replace_with": "{{db_name}}"},
                    )
                    self.assertEqual(pr.status_code, 200)
                    payload = pr.json()
                    self.assertEqual(payload["skill_id"], skill_id)
                    dumped = json.dumps(payload["workflow"])
                    self.assertNotIn("conxa-db", dumped)
                    self.assertIn("{{db_name}}", dumped)

                    r2 = client.get(f"/api/v1/skills/{skill_id}/workflow")
                    self.assertEqual(r2.status_code, 200)
                    self.assertIn("{{db_name}}", json.dumps(r2.json()))
                    self.assertNotIn("conxa-db", json.dumps(r2.json()))

    def test_apply_recording_visual_copies_frame_context(self) -> None:
        from app.editor.recording_visual import apply_recording_event_visual_to_step_or_raise

        doc = _minimal_skill_doc()
        doc["meta"]["source_session_id"] = "sess_frame_visual"
        fresh_anchors = [{"element": "Create", "relation": "target"}]
        event = {
            "visual": {
                "full_screenshot": "images/evt_0001_full.jpg",
                "bbox": {"x": 10, "y": 20, "w": 80, "h": 24},
                "viewport": "1280x720",
                "scroll_position": "0,0",
            },
            "frame": {
                "chain": [
                    {
                        "selector": 'iframe[id="object-builder-ui"]',
                        "fallback_selectors": ['iframe[data-test-id="object-builder-ui-iframe"]'],
                        "url": "https://app-na2.hubspot.com/object-builder/246242636/0-1/embed?",
                        "url_pattern": "^https://app\\-na2\\.hubspot\\.com/object\\-builder/[^/]+/0\\-1/embed$",
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "evt_0001_full.jpg"
            image.write_bytes(b"x")
            with patch("app.storage.session_events.read_session_events", return_value=[event]), patch(
                "app.editor.recording_visual.resolve_skill_asset",
                return_value=image,
            ), patch(
                "app.editor.recording_visual.generate_anchors_for_step_or_raise",
                return_value=fresh_anchors,
            ):
                updated = apply_recording_event_visual_to_step_or_raise(doc, 0, 0)

        updated_step = updated["skills"][0]["steps"][0]
        self.assertEqual(updated_step["frame"]["chain"][0]["selector"], 'iframe[id="object-builder-ui"]')
        self.assertEqual(updated_step["signals"]["visual"]["bbox"], {"x": 10, "y": 20, "w": 80, "h": 24})

    def test_clear_step_visual_strips_images_and_anchors(self) -> None:
        from app.editor.recording_visual import clear_step_visual_screenshots_or_raise

        doc = _minimal_skill_doc()
        sig_before = doc["skills"][0]["steps"][0]["signals"]
        self.assertEqual(sig_before["visual"]["full_screenshot"], "images/evt_0001_full.jpg")

        cleared = clear_step_visual_screenshots_or_raise(dict(doc), 0)
        sig_after = cleared["skills"][0]["steps"][0]["signals"]
        visual = dict(sig_after["visual"])
        self.assertNotIn("full_screenshot", visual)
        self.assertNotIn("bbox", visual)
        self.assertEqual(sig_after["anchors"], [])
        self.assertGreater(int((cleared.get("meta") or {}).get("version", 0)), int((doc.get("meta") or {}).get("version", 0)))  # type: ignore[arg-type]

    def test_update_visual_bbox_regenerates_anchors(self) -> None:
        from app.editor.recording_visual import update_step_visual_bbox_and_regenerate_anchors_or_raise

        doc = _minimal_skill_doc()
        doc["meta"]["source_session_id"] = "sess_bbox"
        step = doc["skills"][0]["steps"][0]
        step["signals"]["visual"]["full_screenshot"] = "sessions/sess_bbox/images/evt_0001_full.jpg"
        step["signals"]["anchors"] = [{"element": "Old", "relation": "near"}]
        step["recovery"]["anchors"] = [{"element": "Old", "relation": "near"}]

        fresh_anchors = [
            {"element": "Submit order", "relation": "target"},
            {"element": "Checkout", "relation": "near"},
        ]
        with patch(
            "app.editor.recording_visual.generate_anchors_for_step_or_raise",
            return_value=fresh_anchors,
        ) as gen:
            updated = update_step_visual_bbox_and_regenerate_anchors_or_raise(
                doc,
                0,
                {"x": 12.2, "y": 20.8, "w": 80.1, "h": 24.9},
            )

        gen.assert_called_once()
        ev_arg = gen.call_args.args[0]
        self.assertEqual(ev_arg["visual"]["bbox"], {"x": 12, "y": 21, "w": 80, "h": 25})
        updated_step = updated["skills"][0]["steps"][0]
        self.assertEqual(updated_step["signals"]["visual"]["bbox"], {"x": 12, "y": 21, "w": 80, "h": 25})
        self.assertEqual(updated_step["signals"]["anchors"], fresh_anchors)
        self.assertEqual(updated_step["recovery"]["anchors"], fresh_anchors)
        self.assertGreater(int(updated["meta"]["version"]), int(doc["meta"]["version"]))
