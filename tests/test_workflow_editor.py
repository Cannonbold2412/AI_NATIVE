"""Workflow editor API, DTO mapping, patch gate, and assets path resolution."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
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
        wf = build_workflow_response("skill_test_editor", doc, asset_base_url="http://localhost:8000")
        self.assertEqual(len(wf.steps), 1)
        self.assertIn("Click", wf.steps[0].human_readable_description)
        self.assertTrue(wf.steps[0].screenshot.full_url.startswith("http://"))

    def test_apply_step_patch_assist_llm_false_skips_enrich(self) -> None:
        from app.compiler.patch import apply_step_patch

        doc = _minimal_skill_doc()
        with patch("app.compiler.patch.enrich_semantic") as es:
            apply_step_patch(doc, 0, {"target": {"primary_selector": "#go2"}}, assist_llm=False)
            es.assert_not_called()

    def test_validate_editor_patch_rejects_bad_selector(self) -> None:
        from app.editor.patch_gate import validate_editor_patch

        step = dict(_minimal_skill_doc()["skills"][0]["steps"][0])
        policy = {}
        with self.assertRaises(ValueError):
            validate_editor_patch(step, {"target": {"primary_selector": "bareword"}}, policy)

    def test_list_skills_endpoint(self) -> None:
        from app.main import app
        from app.storage import json_store

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            p.mkdir(parents=True, exist_ok=True)
            with patch.object(json_store, "skills_dir", return_value=p):
                client = TestClient(app)
                r = client.get("/skills")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json().get("skills"), [])
                (p / "skill_list_test.json").write_text(
                    json.dumps(_minimal_skill_doc("skill_list_test")),
                    encoding="utf-8",
                )
                r2 = client.get("/skills")
                self.assertEqual(r2.status_code, 200)
                rows = r2.json().get("skills") or []
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["skill_id"], "skill_list_test")

    def test_workflow_api_get_and_patch(self) -> None:
        from app.main import app
        from app.storage import json_store

        skill_id = "skill_workflow_api_test"
        doc = _minimal_skill_doc(skill_id)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            p.mkdir(parents=True, exist_ok=True)
            with patch.object(json_store, "skills_dir", return_value=p):
                (p / f"{skill_id}.json").write_text(json.dumps(doc), encoding="utf-8")
                client = TestClient(app)
                r = client.get(f"/skills/{skill_id}/workflow")
                self.assertEqual(r.status_code, 200)
                data = r.json()
                self.assertEqual(data["skill_id"], skill_id)
                self.assertEqual(len(data["steps"]), 1)
                pr = client.patch(
                    f"/skills/{skill_id}/steps/0",
                    json={"patch": {"target": {"primary_selector": "#submit"}}, "assist_llm": False},
                )
                self.assertEqual(pr.status_code, 200)
                self.assertEqual(pr.json()["meta"]["version"], 2)

    def test_reorder_and_delete(self) -> None:
        from app.editor.workflow_service import delete_step_at, reorder_steps

        doc = _minimal_skill_doc()
        s2 = dict(doc["skills"][0]["steps"][0])
        s2["intent"] = "second_step"
        doc["skills"][0]["steps"].append(s2)
        r = reorder_steps(doc, [1, 0])
        self.assertEqual(r["skills"][0]["steps"][0]["intent"], "second_step")
        d = delete_step_at(r, 0)
        self.assertEqual(len(d["skills"][0]["steps"]), 1)
        self.assertEqual(d["skills"][0]["steps"][0]["intent"], "click_submit_button")
