"""Regression tests for the LLM-first Skill Pack Builder."""

from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient


def _raw_workflow() -> dict:
    return {
        "meta": {"title": "Delete Database Recording"},
        "steps": [
            {"action": "focus", "target": {"name": "Email"}},
            {"action": "type", "value": "person@example.com", "target": {"name": "Email"}},
            {"action": "type", "value": "secret", "target": {"name": "Password"}},
            {"action": "click", "target": {"inner_text": "Sign in"}},
            {"action": "scroll", "delta": 500},
            {"action": "click", "target": {"inner_text": "Delete Database"}},
        ],
    }


def _structured_workflow() -> dict:
    return {
        "goal": "Delete Database",
        "steps": [
            {"type": "navigate", "url": "https://example.test/login"},
            {"type": "fill", "selector": "input[name=email]", "value": "{{user_email}}"},
            {"type": "fill", "selector": "input[name=password]", "value": "{{user_password}}"},
            {"type": "click", "selector": "text=Sign in"},
            {"type": "click", "selector": "text={{db_name}}"},
            {"type": "click", "selector": "text=Delete Database"},
        ],
    }


def _structured_workflow_with_visuals() -> dict:
    return {
        "goal": "Delete Database Visual Assets Test",
        "steps": [
            {"type": "navigate", "url": "https://example.test/login"},
            {"type": "fill", "selector": "input[name=email]", "value": "{{user_email}}"},
            {"type": "click", "selector": "text=Delete Database"},
        ],
    }


class SkillPackBuilderTests(unittest.TestCase):
    def test_structure_steps_with_llm_validates_provider_json(self) -> None:
        from app.services.skill_pack_builder import structure_steps_with_llm

        with patch("app.services.skill_pack_builder._call_structuring_llm", return_value=_structured_workflow()):
            structured = structure_steps_with_llm(_raw_workflow()["steps"])

        self.assertEqual(structured["goal"], "Delete Database")
        self.assertEqual(structured["steps"][1], {"type": "fill", "selector": "input[name=email]", "value": "{{user_email}}"})

    def test_compile_execution_preserves_scroll_steps(self) -> None:
        from app.services.skill_pack_builder import compile_execution, generate_execution_plan

        structured = {
            "goal": "Reveal lazy content",
            "steps": [
                {"type": "navigate", "url": "https://example.test/app"},
                {"type": "scroll", "delta_y": 400},
                {"type": "scroll", "selector": "text=Load more"},
                {"type": "fill", "selector": "input[name=note]", "value": "{{note}}"},
                {"type": "click", "selector": "text=Save"},
            ],
        }
        plan = compile_execution(structured)
        self.assertEqual(plan[1], {"type": "scroll", "delta_y": 400.0})
        self.assertEqual(plan[2], {"type": "scroll", "selector": "text=Load more"})
        execution_md, _ = generate_execution_plan(structured)
        self.assertIn(". scroll delta_y", execution_md.lower())
        self.assertIn("into_view", execution_md.lower())

    def test_compile_execution_passes_steps_and_adds_only_minimal_guards(self) -> None:
        from app.services.skill_pack_builder import compile_execution, generate_execution_plan

        plan = compile_execution(_structured_workflow())

        self.assertEqual(
            plan,
            [
                {"type": "navigate", "url": "https://example.test/login"},
                {"type": "fill", "selector": "input[name=email]", "value": "{{user_email}}"},
                {"type": "fill", "selector": "input[name=password]", "value": "{{user_password}}"},
                {"type": "click", "selector": "text=Sign in"},
                {"type": "assert_visible", "selector": "text=Dashboard"},
                {"type": "click", "selector": "text={{db_name}}"},
                {"type": "assert_visible", "selector": "text=Delete Database"},
                {"type": "click", "selector": "text=Delete Database"},
            ],
        )
        self.assertNotIn('"wait"', json.dumps(plan))

        execution_md, md_plan = generate_execution_plan(_structured_workflow())
        self.assertEqual(md_plan, plan)
        self.assertIn("assert_visible text=Dashboard", execution_md)

    def test_validation_rejects_wait_xpath_and_generic_selectors(self) -> None:
        from app.services.skill_pack_builder import compile_execution, structure_steps_with_llm

        bad_payloads = [
            {"goal": "Bad", "steps": [{"type": "click", "selector": "button"}]},
            {"goal": "Bad", "steps": [{"type": "fill", "selector": "input", "value": "{{email}}"}]},
            {"goal": "Bad", "steps": [{"type": "click", "selector": "//button"}]},
            {"goal": "Bad", "steps": [{"type": "wait", "selector": "text=Done"}]},
        ]

        for payload in bad_payloads:
            with self.subTest(payload=payload), patch("app.services.skill_pack_builder._call_structuring_llm", return_value=payload):
                with self.assertRaises(ValueError):
                    structure_steps_with_llm([{"raw": True}])

        with self.assertRaises(ValueError):
            compile_execution({"goal": "Bad", "steps": [{"type": "wait", "selector": "text=Done"}]})

    def test_generate_recovery_uses_structured_steps(self) -> None:
        from app.services.skill_pack_builder import generateRecoveryMap, generate_recovery_map

        expected_delete_entry = {
            "step_id": 8,
            "intent": "click_delete_database",
            "target": {"text": "Delete Database", "type": "button", "section": "danger zone"},
            "anchors": ["danger zone", "bottom"],
            "fallback": {
                "text_variants": ["Delete Database", "Delete", "Remove"],
                "visual_hint": "red button",
            },
        }

        recovery = generate_recovery_map(_structured_workflow())
        self.assertIn(expected_delete_entry, recovery["steps"])
        self.assertEqual(generateRecoveryMap(_structured_workflow()), recovery)

    def test_parse_inputs_and_manifest_match_structured_variables(self) -> None:
        from app.services.skill_pack_builder import build_manifest, parse_inputs

        inputs = parse_inputs(_structured_workflow())
        self.assertEqual([item["name"] for item in inputs], ["user_email", "user_password", "db_name"])
        self.assertTrue(inputs[1]["sensitive"])

        manifest = build_manifest(inputs, "delete_database")
        self.assertEqual(manifest["name"], "delete_database")
        self.assertEqual(manifest["entry"]["execution"], "./execution.json")
        self.assertEqual(manifest["entry"]["recovery"], "./recovery.json")
        self.assertEqual(manifest["entry"]["inputs"], "./inputs.json")
        self.assertEqual(manifest["execution_mode"], "deterministic")
        self.assertFalse(manifest["llm_required"])
        self.assertEqual([item["name"] for item in manifest["inputs"]], ["user_email", "user_password", "db_name"])

    def test_build_skill_package_writes_clean_outputs(self) -> None:
        from app.services.skill_pack_builder import build_skill_package

        with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
            package = build_skill_package(json.dumps(_raw_workflow()))

        execution = json.loads(package["execution_json"])
        index = json.loads(package["index_json"])
        skill_md = package["skill_md"]
        self.assertEqual(package["name"], "delete_database")
        index_by_name = {item["name"]: item for item in index["workflows"]}
        self.assertEqual(index_by_name["delete_database"]["manifest"], "/skills/delete_database/manifest.json")
        self.assertTrue(package["used_llm"])
        self.assertEqual(package["input_count"], 3)
        self.assertFalse(any(step["type"] == "wait" for step in execution))
        self.assertIn({"type": "click", "selector": "text=Delete Database"}, execution)
        self.assertIn("1. Open login page", skill_md)
        self.assertIn("2. Enter {{user_email}}", skill_md)
        self.assertIn('4. Click "Sign in"', skill_md)
        self.assertIn("6. Delete Database", skill_md)

    def test_skill_pack_api_build_and_export(self) -> None:
        from app.main import app

        with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
            client = TestClient(app)
            build_response = client.post("/skill-pack/build", json={"json_text": json.dumps(_raw_workflow())})
            self.assertEqual(build_response.status_code, 200)
            payload = build_response.json()
            self.assertIn("index_json", payload)
            index_by_name = {item["name"]: item for item in json.loads(payload["index_json"])["workflows"]}
            self.assertEqual(index_by_name["delete_database"]["manifest"], "/skills/delete_database/manifest.json")
            files_response = client.get(f"/skill-pack/{payload['name']}")
            self.assertEqual(files_response.status_code, 200)
            files_payload = files_response.json()
            self.assertEqual(files_payload["package_name"], "delete_database")
            self.assertIn("index.json", files_payload["files"])
            self.assertIn("skill.md", files_payload["files"])
            self.assertIn("execution.json", files_payload["files"])
            self.assertIn("recovery.json", files_payload["files"])
            export_response = client.post(
                "/skill-pack/export",
                json={
                    "name": payload["name"],
                    "skill_md": payload["skill_md"],
                    "execution_json": payload["execution_json"],
                    "recovery_json": payload["recovery_json"],
                    "skill_json": payload["skill_json"],
                    "inputs_json": payload["inputs_json"],
                    "manifest_json": payload["manifest_json"],
                },
            )

        self.assertEqual(export_response.status_code, 200)
        with ZipFile(BytesIO(export_response.content)) as archive:
            names = archive.namelist()
            self.assertIn("skill_package/README.md", names)
            self.assertIn("skill_package/index.json", names)
            self.assertIn("skill_package/engine/execution.ts", names)
            self.assertIn("skill_package/engine/recovery.ts", names)
            self.assertIn("skill_package/engine/logging.ts", names)
            self.assertIn("skill_package/engine/config.ts", names)
            self.assertIn("skill_package/workflows/delete_database/skill.md", names)
            self.assertIn("skill_package/workflows/delete_database/execution.json", names)
            self.assertIn("skill_package/workflows/delete_database/recovery.json", names)
            self.assertIn("skill_package/workflows/delete_database/inputs.json", names)
            self.assertIn("skill_package/workflows/delete_database/manifest.json", names)
            self.assertNotIn("skill_package/workflows/delete_database/skill.json", names)
            index = json.loads(archive.read("skill_package/index.json"))
            self.assertEqual(index["workflows"][0]["manifest"], "/skills/delete_database/manifest.json")
            manifest = json.loads(archive.read("skill_package/workflows/delete_database/manifest.json"))
            self.assertEqual(manifest["entry"]["execution"], "./execution.json")

    def test_build_skill_package_persists_step_visuals_and_exports_them(self) -> None:
        from app.config import settings
        from app.services.skill_pack_builder import build_skill_package, build_skill_package_zip
        from app.storage.skill_packages import delete_skill_package, skill_package_dir

        payload = {
            "package_meta": {"source_session_id": "sess_visual_assets"},
            "steps": [
                {
                    "step_index": 0,
                    "screenshot": {
                        "full_url": "http://localhost:8000/skills/skill_visual/assets?path=images/step_1.jpg",
                    },
                },
                {
                    "step_index": 1,
                    "screenshot": {
                        "full_url": "http://localhost:8000/skills/skill_visual/assets?path=images/step_2.png",
                    },
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            session_dir = data_dir / "sessions" / "sess_visual_assets"
            images_dir = session_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / "launch.jpg").write_bytes(b"launch-image")
            (images_dir / "step_1.jpg").write_bytes(b"step-one-image")
            (images_dir / "step_2.png").write_bytes(b"step-two-image")
            (session_dir / "events.jsonl").write_text(
                json.dumps(
                    {
                        "visual": {"full_screenshot": "images/launch.jpg"},
                        "extras": {"session_id": "sess_visual_assets"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(settings, "data_dir", data_dir):
                with patch(
                    "app.services.skill_pack_builder.structure_steps_with_llm",
                    return_value=_structured_workflow_with_visuals(),
                ):
                    package = build_skill_package(json.dumps(payload))

                package_name = package["name"]
                visuals_dir = skill_package_dir(package_name) / "visuals"
                try:
                    self.assertEqual(package_name, "delete_database_visual_assets_test")
                    self.assertEqual((visuals_dir / "Image_0.jpg").read_bytes(), b"launch-image")
                    self.assertEqual((visuals_dir / "Image_1.jpg").read_bytes(), b"step-one-image")
                    self.assertEqual((visuals_dir / "Image_2.png").read_bytes(), b"step-two-image")

                    filename, zipped = build_skill_package_zip(
                        package_name=package_name,
                        skill_md=package["skill_md"],
                        skill_json=package["skill_json"],
                        inputs_json=package["inputs_json"],
                        manifest_json=package["manifest_json"],
                        execution_md=package["execution_md"],
                        execution_plan_json=package["execution_plan_json"],
                        execution_json=package["execution_json"],
                        recovery_json=package["recovery_json"],
                    )

                    self.assertEqual(filename, "skill_package_delete_database_visual_assets_test.zip")
                    with ZipFile(BytesIO(zipped)) as archive:
                        names = archive.namelist()
                        self.assertIn(
                            "skill_package/workflows/delete_database_visual_assets_test/visuals/Image_0.jpg",
                            names,
                        )
                        self.assertIn(
                            "skill_package/workflows/delete_database_visual_assets_test/visuals/Image_1.jpg",
                            names,
                        )
                        self.assertIn(
                            "skill_package/workflows/delete_database_visual_assets_test/visuals/Image_2.png",
                            names,
                        )
                        self.assertEqual(
                            archive.read(
                                "skill_package/workflows/delete_database_visual_assets_test/visuals/Image_0.jpg"
                            ),
                            b"launch-image",
                        )
                finally:
                    delete_skill_package(package_name)
