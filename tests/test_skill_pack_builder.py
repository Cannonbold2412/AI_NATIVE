"""Regression tests for Skill Pack Builder service + API."""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch

from fastapi.testclient import TestClient


def _sample_workflow() -> dict:
    return {
        "meta": {"title": "Customer Onboarding"},
        "inputs": [{"name": "api_token"}],
        "skills": [
            {
                "name": "default",
                "steps": [
                    {
                        "action": {"action": "type", "value": "{{user_email}}"},
                        "intent": "enter_user_email",
                        "target": {"name": "Email address", "role": "textbox"},
                        "validation": {"wait_for": {"type": "element_appear", "timeout": 5000}},
                    },
                    {
                        "action": {"action": "type", "value": "{{password}}"},
                        "intent": "enter_password",
                        "target": {"name": "Password", "role": "textbox"},
                        "validation": {"wait_for": {"type": "state_change", "timeout": 5000}},
                    },
                ],
            }
        ],
    }


class SkillPackBuilderTests(unittest.TestCase):
    def test_execution_mode_block_is_injected_once_before_steps(self) -> None:
        from app.services.skill_pack_builder import _EXECUTION_MODE_HEADING, build_skill_package

        with patch("app.services.skill_pack_builder.generate_skill_markdown_with_llm", return_value=None):
            package = build_skill_package(json.dumps(_sample_workflow()))

        skill_md = package["skill_md"]
        self.assertIn(_EXECUTION_MODE_HEADING, skill_md)
        self.assertEqual(skill_md.count(_EXECUTION_MODE_HEADING), 1)
        self.assertLess(skill_md.index(_EXECUTION_MODE_HEADING), skill_md.index("## Steps"))
        self.assertIn("## Inputs", skill_md)

    def test_parse_inputs_deduplicates_and_marks_sensitive(self) -> None:
        from app.services.skill_pack_builder import parse_inputs

        inputs = parse_inputs(_sample_workflow())
        names = [item["name"] for item in inputs]
        self.assertEqual(names, ["user_email", "password", "api_token"])
        self.assertTrue(inputs[1]["sensitive"])
        self.assertTrue(inputs[2]["sensitive"])

    def test_build_skill_package_falls_back_without_llm(self) -> None:
        from app.services.skill_pack_builder import build_skill_package

        with patch("app.services.skill_pack_builder.generate_skill_markdown_with_llm", return_value=None):
            package = build_skill_package(json.dumps(_sample_workflow()))
        self.assertEqual(package["name"], "customer_onboarding")
        self.assertEqual(package["step_count"], 2)
        self.assertEqual(package["input_count"], 3)
        self.assertFalse(package["used_llm"])
        self.assertIn("## Steps", package["skill_md"])
        self.assertIn("user_email", package["inputs_json"])
        self.assertIn("customer_onboarding", package["manifest_json"])

    def test_skill_markdown_uses_agent_friendly_steps_and_matching_inputs(self) -> None:
        from app.services.skill_pack_builder import build_skill_package

        workflow = _sample_workflow()
        workflow["meta"]["start_url"] = "https://example.test/login"
        workflow["skills"][0]["steps"].insert(
            0,
            {"action": {"action": "focus"}, "target": {"name": "Email address", "role": "textbox"}},
        )
        workflow["skills"][0]["steps"].insert(2, {"action": {"action": "scroll", "delta": 400}})
        workflow["skills"][0]["steps"][1]["input_binding"] = "email"

        with patch("app.services.skill_pack_builder.generate_skill_markdown_with_llm", return_value=None):
            package = build_skill_package(json.dumps(workflow))

        skill_md = package["skill_md"].lower()
        inputs = json.loads(package["inputs_json"])["inputs"]
        self.assertIn("1. open https://example.test/login.", skill_md)
        self.assertIn("enter email address using {{user_email}}", skill_md)
        self.assertNotIn("{{email}}", skill_md)
        self.assertNotIn("activate", skill_md)
        self.assertNotIn("focus", skill_md)
        self.assertNotIn("scroll", skill_md)
        self.assertEqual([item["name"] for item in inputs], ["user_email", "password", "api_token"])

    def test_existing_execution_mode_block_is_not_duplicated(self) -> None:
        from app.services.skill_pack_builder import _EXECUTION_MODE_BLOCK, _EXECUTION_MODE_HEADING, build_skill_package

        llm_markdown = "\n".join(
            [
                "# customer_onboarding",
                "",
                "## Inputs",
                "1. `{{user_email}}`: Enter user email.",
                "2. `{{password}}`: Enter password.",
                "3. `{{api_token}}`: Enter api token.",
                "",
                _EXECUTION_MODE_BLOCK,
                "",
                "## Steps",
                "1. Enter Email address using {{user_email}}.",
                "2. Enter Password using {{password}}.",
                "",
                "## Validation",
                "1. Wait until the expected content appears.",
                "2. Wait until the page updates.",
            ]
        )
        with patch("app.services.skill_pack_builder.generate_skill_markdown_with_llm", return_value=llm_markdown):
            package = build_skill_package(json.dumps(_sample_workflow()))

        self.assertTrue(package["used_llm"])
        self.assertEqual(package["skill_md"].count(_EXECUTION_MODE_HEADING), 1)

    def test_skill_pack_api_build_and_export(self) -> None:
        from app.main import app

        with patch("app.services.skill_pack_builder.generate_skill_markdown_with_llm", return_value=None):
            client = TestClient(app)
            build_response = client.post("/skill-pack/build", json={"json_text": json.dumps(_sample_workflow())})
            self.assertEqual(build_response.status_code, 200)
            payload = build_response.json()
            files_response = client.get(f"/skill-pack/{payload['name']}")
            self.assertEqual(files_response.status_code, 200)
            files_payload = files_response.json()
            self.assertEqual(files_payload["package_name"], "customer_onboarding")
            self.assertIn("skill.md", files_payload["files"])
            self.assertIn("inputs.json", files_payload["files"])
            export_response = client.post(
                "/skill-pack/export",
                json={
                    "name": payload["name"],
                    "skill_md": payload["skill_md"],
                    "inputs_json": payload["inputs_json"],
                    "manifest_json": payload["manifest_json"],
                },
            )
        self.assertEqual(export_response.status_code, 200)
        with ZipFile(BytesIO(export_response.content)) as archive:
            names = archive.namelist()
            self.assertIn("customer_onboarding/skill.md", names)
            self.assertIn("customer_onboarding/inputs.json", names)
            self.assertIn("customer_onboarding/manifest.json", names)
