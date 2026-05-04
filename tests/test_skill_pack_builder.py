"""Regression tests for the LLM-first Skill Pack Builder."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Iterator
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

@contextmanager
def _temporary_skill_package_root() -> Iterator[Path]:
    """Hermetic bundle writes under a temp dir (avoids polluting workspace output/skill_package)."""

    td = Path(tempfile.mkdtemp())
    try:
        root = td / "skill_package"
        root.mkdir(parents=True, exist_ok=True)
        with patch("app.storage.skill_packages.skill_package_root_dir", return_value=root):
            yield root
    finally:
        shutil.rmtree(td, ignore_errors=True)


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


def _raw_workflow_two() -> dict:
    return {
        "meta": {"title": "Delete Web Service Recording"},
        "steps": [
            {"action": "click", "target": {"inner_text": "Settings"}},
            {"action": "scroll", "delta": 300},
            {"action": "click", "target": {"inner_text": "Delete Web Service"}},
            {"action": "type", "value": "delete web service", "target": {"name": "Confirm"}},
            {"action": "click", "target": {"inner_text": "Delete Web Service"}},
        ],
    }


def _structured_workflow_two() -> dict:
    return {
        "goal": "Delete Web Service",
        "steps": [
            {"type": "navigate", "url": "https://dashboard.render.com"},
            {"type": "click", "selector": "text={{service_name}}"},
            {"type": "click", "selector": "text=Settings"},
            {"type": "fill", "selector": "input[name=confirm]", "value": "{{text}}"},
            {"type": "click", "selector": "text=Delete Web Service"},
        ],
    }


def _multi_workflow_payload() -> dict:
    return {
        "skills": [
            {
                "title": "Delete Database",
                "steps": _raw_workflow()["steps"],
            },
            {
                "title": "Delete Web Service",
                "steps": _raw_workflow_two()["steps"],
            },
        ]
    }


class SkillPackPreprocessTests(unittest.TestCase):
    def test_preprocess_declarations_does_not_mutate_source(self) -> None:
        from app.services.skill_pack_builder import preprocess_skill_pack_declarations

        raw = {"steps": [{"a": 1}], "inputs": []}
        _ = preprocess_skill_pack_declarations(raw)
        self.assertIn("inputs", raw)

    def test_preprocess_declarations_strips_blocks_recursive(self) -> None:
        from app.services.skill_pack_builder import preprocess_skill_pack_declarations

        raw = {
            "meta": {"title": "T", "source_session_id": "sess1"},
            "inputs": [{"name": "email"}],
            "parameters": {"x": 1},
            "steps": [
                {
                    "action": "navigate",
                    "screenshot": {"full_url": "sessions/foo.png"},
                    "nested": {"variables": [{"id": "v"}]},
                },
            ],
        }
        out = preprocess_skill_pack_declarations(raw)
        self.assertNotIn("inputs", out)
        self.assertNotIn("parameters", out)
        self.assertEqual(out["meta"]["source_session_id"], "sess1")
        step = out["steps"][0]
        self.assertIn("screenshot", step)
        self.assertEqual(step["nested"], {})

    def test_sanitize_raw_steps_for_llm_removes_heavy_fields(self) -> None:
        from app.services.skill_pack_builder import sanitize_raw_steps_for_llm

        heavy = [
            {
                "action": "navigate",
                "screenshot": {"full_url": "x"},
                "signals": {"visual": {"a": 1}, "keep": True},
                "extras": {"session_id": "s", "meta": {}},
                "visual": {"b": 2},
            }
        ]
        slim = sanitize_raw_steps_for_llm(heavy)
        self.assertEqual(slim[0]["action"], "navigate")
        self.assertNotIn("screenshot", slim[0])
        self.assertNotIn("visual", slim[0])
        self.assertIn("signals", slim[0])
        self.assertNotIn("visual", slim[0]["signals"])
        self.assertEqual(slim[0]["signals"].get("keep"), True)
        self.assertEqual(slim[0]["extras"], {"meta": {}})
        self.assertIn("screenshot", heavy[0])

    def test_structure_steps_with_llm_passes_trimmed_steps_to_provider(self) -> None:
        from app.services.skill_pack_builder import structure_steps_with_llm

        captured: list[list[dict]] = []

        def capture(steps: list) -> dict:
            captured.append(list(steps))
            return _structured_workflow()

        with patch("app.services.skill_pack_builder._call_structuring_llm", side_effect=capture):
            structure_steps_with_llm(
                [
                    {
                        "action": "click",
                        "screenshot": {"full_url": "http://example.invalid/x.png"},
                    }
                ]
            )

        self.assertEqual(len(captured), 1)
        self.assertNotIn("screenshot", captured[0][0])


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

        recovery = generate_recovery_map(_structured_workflow())
        self.assertEqual(generateRecoveryMap(_structured_workflow()), recovery)
        self.assertEqual([step["step_id"] for step in recovery["steps"]], [2, 3, 4, 6, 8])

        delete_entry = next(step for step in recovery["steps"] if step["step_id"] == 8)
        self.assertEqual(delete_entry["intent"], "click_delete_database")
        self.assertEqual(delete_entry["target"], {"text": "Delete Database", "role": ""})
        self.assertEqual(
            delete_entry["anchors"],
            [{"text": "Danger Zone", "priority": 1}, {"text": "Delete Database", "priority": 2}],
        )
        self.assertEqual(
            delete_entry["fallback"],
            {"text_variants": ["Delete Database", "Delete", "Remove"], "role": ""},
        )
        self.assertEqual(delete_entry["selector_context"]["primary"], "text=Delete Database")
        self.assertEqual(delete_entry["selector_context"]["alternatives"], ['text="Delete Database"'])
        self.assertEqual(delete_entry["visual_metadata"]["available"], False)
        self.assertNotIn("visual_ref", delete_entry)

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
        self.assertEqual(manifest["recovery_mode"], "tiered")
        self.assertTrue(manifest["vision_enabled"])
        self.assertFalse(manifest["llm_required"])
        self.assertEqual([item["name"] for item in manifest["inputs"]], ["user_email", "user_password", "db_name"])

    def test_build_skill_package_writes_clean_outputs(self) -> None:
        from app.services.skill_pack_builder import build_skill_package

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
                package = build_skill_package(json.dumps(_raw_workflow()), bundle_slug="render")

            execution = json.loads(package["execution_json"])
            index = json.loads(package["index_json"])
            skill_md = package["skill_md"]
            self.assertEqual(package["name"], "delete_database_recording")
            index_by_name = {item["name"]: item for item in index["workflows"]}
            self.assertEqual(
                index_by_name["delete_database_recording"]["manifest"],
                "workflows/delete_database_recording/manifest.json",
            )
            self.assertTrue(package["used_llm"])
            self.assertEqual(package["input_count"], 3)
            self.assertNotIn("skill_json", package)
            self.assertNotIn("execution_md", package)
            self.assertNotIn("execution_plan_json", package)
            self.assertFalse(any(step["type"] == "wait" for step in execution))
            self.assertIn({"type": "click", "selector": "text=Delete Database"}, execution)
            self.assertIn("name: render", skill_md)
            self.assertIn("description: Render automation workflows", skill_md)
            self.assertIn('"workflow": "delete_database_recording"', skill_md)
            self.assertIn("Return ONLY JSON. No explanations.", skill_md)
            self.assertIn("* DO NOT output text outside JSON", skill_md)
            self.assertNotIn("* DO NOT include UI steps", skill_md)

    def test_build_skill_package_writes_claude_skill_only(self) -> None:
        from app.services.skill_pack_builder import build_skill_package
        from app.storage.skill_packages import bundle_root_dir, skill_package_dir

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
                package = build_skill_package(json.dumps(_raw_workflow()), bundle_slug="render")

            wf_dir = skill_package_dir("render", package["name"])
            br = bundle_root_dir("render")
            self.assertIsNotNone(br)
            cl = br / "claude" / "skills" / "render" / "SKILL.md"
            self.assertTrue(cl.is_file())
            text = cl.read_text(encoding="utf-8")
            self.assertIn('"workflow": "delete_database_recording"', text)
            self.assertFalse((br / ".opencode").exists())
            self.assertFalse((br / ".codex").exists())
            self.assertFalse((wf_dir / ".opencode").exists())

    def test_building_multiple_workflows_creates_multiple_bundle_folders(self) -> None:
        from app.services.skill_pack_builder import build_skill_package
        from app.storage.skill_packages import read_skill_package_files

        with _temporary_skill_package_root():
            with patch(
                "app.services.skill_pack_builder.structure_steps_with_llm",
                side_effect=[_structured_workflow(), _structured_workflow_two()],
            ):
                first = build_skill_package(
                    json.dumps(_raw_workflow()),
                    package_name="delete_database",
                    bundle_slug="default",
                )
                second = build_skill_package(
                    json.dumps(_raw_workflow_two()),
                    package_name="delete_web_service",
                    bundle_slug="default",
                )

            index = json.loads(second["index_json"])
            index_by_name = {item["name"]: item for item in index["workflows"]}
            self.assertEqual(set(index_by_name), {"delete_database", "delete_web_service"})
            self.assertEqual(
                index_by_name["delete_database"]["manifest"],
                "workflows/delete_database/manifest.json",
            )
            self.assertEqual(
                index_by_name["delete_web_service"]["manifest"],
                "workflows/delete_web_service/manifest.json",
            )
            self.assertIn("claude/skills/default/SKILL.md", read_skill_package_files("default", first["name"]))
            self.assertNotIn("skill.md", read_skill_package_files("default", second["name"]))

    def test_append_workflow_creates_new_folder_and_keeps_existing_files_unchanged(self) -> None:
        from app.services.skill_pack_builder import append_workflow_to_skill_package, build_skill_package
        from app.storage.skill_packages import read_skill_package_files

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
                build_skill_package(json.dumps(_raw_workflow()), package_name="delete_database", bundle_slug="default")

            before = read_skill_package_files("default", "delete_database")
            assert before is not None

            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow_two()):
                appended = append_workflow_to_skill_package(
                    "default",
                    json.dumps(_raw_workflow_two()),
                    appended_package_name="delete_web_service",
                )

            after = read_skill_package_files("default", "delete_database")
            appended_files = read_skill_package_files("default", "delete_web_service")
            assert after is not None
            assert appended_files is not None

            self.assertEqual(appended["name"], "delete_web_service")
            self.assertEqual(before["execution.json"], after["execution.json"])
            self.assertEqual(before["execution.json"], after["execution.json"])
            self.assertIn("bridge/run.js", appended_files)
            self.assertEqual(
                json.loads(appended["index_json"])["workflows"],
                [
                    {"name": "delete_database", "description": "Delete Database", "manifest": "workflows/delete_database/manifest.json"},
                    {"name": "delete_web_service", "description": "Delete Web Service", "manifest": "workflows/delete_web_service/manifest.json"},
                ],
            )

    def test_skill_pack_build_error_includes_build_log_payload(self) -> None:
        from app.main import app

        def _boom(_raw_steps: object) -> dict:
            raise ValueError("simulated structuring failure")

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", side_effect=_boom):
                client = TestClient(app)
                resp = client.post("/skill-pack/build", json={"json_text": json.dumps(_raw_workflow())})

        self.assertEqual(resp.status_code, 400)
        detail = resp.json()["detail"]
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail["message"], "simulated structuring failure")
        build_log = detail["build_log"]
        self.assertIsInstance(build_log, list)
        kinds = {row.get("kind") for row in build_log if isinstance(row, dict)}
        self.assertIn("persist_phase", kinds)
        self.assertIn("pipeline_phase", kinds)

    def test_skill_pack_build_stream_emits_log_and_done_sse(self) -> None:
        from app.main import app

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
                client = TestClient(app)
                with client.stream(
                    "POST",
                    "/skill-pack/build/stream",
                    json={"json_text": json.dumps(_raw_workflow()), "bundle_name": "default"},
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    blob = b"".join(resp.iter_bytes())

        self.assertIn(b'"event":"log"', blob)
        self.assertIn(b'"event":"done"', blob)
        self.assertIn(b'"name":', blob)

    def test_skill_pack_append_stream_emits_log_and_done_sse(self) -> None:
        from app.main import app

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
                client = TestClient(app)
                seeded = client.post(
                    "/skill-pack/build",
                    json={
                        "json_text": json.dumps(_raw_workflow()),
                        "bundle_name": "sse_append_bundle",
                        "package_name": "delete_database",
                    },
                )
                self.assertEqual(seeded.status_code, 200)

            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow_two()):
                client = TestClient(app)
                with client.stream(
                    "POST",
                    "/skill-pack/bundles/sse_append_bundle/append/stream",
                    json={"json_text": json.dumps(_raw_workflow_two()), "package_name": "delete_web_service"},
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    blob = b"".join(resp.iter_bytes())

        self.assertIn(b'"event":"log"', blob)
        self.assertIn(b'"event":"done"', blob)

    def test_skill_pack_api_build_and_export(self) -> None:
        from app.main import app

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow()):
                client = TestClient(app)
                build_response = client.post("/skill-pack/build", json={"json_text": json.dumps(_raw_workflow())})
                self.assertEqual(build_response.status_code, 200)
                payload = build_response.json()
                self.assertIn("index_json", payload)
                index_by_name = {item["name"]: item for item in json.loads(payload["index_json"])["workflows"]}
                self.assertEqual(
                    index_by_name["delete_database_recording"]["manifest"],
                    "workflows/delete_database_recording/manifest.json",
                )
                files_response = client.get(f"/skill-pack/bundles/default")
                self.assertEqual(files_response.status_code, 200)
                files_payload = files_response.json()
                self.assertEqual(files_payload["package_name"], "default")
                fn = files_payload["files"]
                wf_prefix = f"workflows/{payload['name']}/"
                self.assertIn("install.js", fn)
                self.assertIn("install.bat", fn)
                self.assertIn("render.js", fn)
                self.assertIn("render.bat", fn)
                self.assertIn("index.json", fn)
                self.assertIn("claude/skills/default/SKILL.md", fn)
                self.assertNotIn("skill.json", fn)
                self.assertNotIn("README.md", fn)
                self.assertIn(f"{wf_prefix}execution.json", fn)
                self.assertIn(f"{wf_prefix}recovery.json", fn)
                export_response = client.post(
                    "/skill-pack/export",
                    json={
                        "name": payload["name"],
                        "skill_md": payload["skill_md"],
                        "execution_json": payload["execution_json"],
                        "recovery_json": payload["recovery_json"],
                        "inputs_json": payload["inputs_json"],
                        "manifest_json": payload["manifest_json"],
                    },
                )

            self.assertEqual(export_response.status_code, 200)
            bundle_path = "default"
            wf = f"{bundle_path}/workflows/{payload['name']}"
            with ZipFile(BytesIO(export_response.content)) as archive:
                names = archive.namelist()
                self.assertIn(f"{bundle_path}/install.js", names)
                self.assertIn(f"{bundle_path}/install.bat", names)
                self.assertIn(f"{bundle_path}/render.js", names)
                self.assertIn(f"{bundle_path}/render.bat", names)
                self.assertIn(f"{bundle_path}/index.json", names)
                self.assertIn(f"{bundle_path}/engine/executor.js", names)
                self.assertNotIn(f"{bundle_path}/engine/recovery.js", names)
                self.assertIn(f"{bundle_path}/bridge/run.js", names)
                self.assertIn(f"{bundle_path}/claude/skills/default/SKILL.md", names)
                self.assertIn(f"{wf}/execution.json", names)
                self.assertIn(f"{wf}/recovery.json", names)
                self.assertIn(f"{wf}/inputs.json", names)
                self.assertIn(f"{wf}/manifest.json", names)
                self.assertNotIn(f"{wf}/skill.md", names)
                index = json.loads(archive.read(f"{bundle_path}/index.json"))
                self.assertEqual(
                    index["workflows"][0]["manifest"],
                    "workflows/delete_database_recording/manifest.json",
                )
                manifest = json.loads(archive.read(f"{wf}/manifest.json"))
                self.assertEqual(manifest["entry"]["execution"], "./execution.json")
                install_bat = archive.read(f"{bundle_path}/install.bat").decode("utf-8")
                install_js = archive.read(f"{bundle_path}/install.js").decode("utf-8")
                render_js = archive.read(f"{bundle_path}/render.js").decode("utf-8")
                render_bat = archive.read(f"{bundle_path}/render.bat").decode("utf-8")
                self.assertEqual(
                    install_bat,
                    '@echo off\r\ncd /d "%~dp0"\r\necho Installing Render Skill...\r\nnode install.js\r\necho Done!\r\npause\r\n',
                )
                self.assertIn('const claudeCandidates = [path.join(claudeRoot, "CLAUDE.md"), path.join(claudeRoot, "Claude.md")];', install_js)
                self.assertIn('fs.cpSync(source, target, { recursive: true, force: true });', install_js)
                self.assertIn('const fs = require("fs");', install_js)
                self.assertIn('const os = require("os");', install_js)
                self.assertIn('const path = require("path");', install_js)
                self.assertNotIn('require("child_process")', install_js)
                self.assertIn('Source skill path:', install_js)
                self.assertIn('Target skill path:', install_js)
                self.assertIn('CLAUDE.md path:', install_js)
                self.assertIn('console.log(`Registered ${skillName} in ${claudePath}`);', install_js)
                self.assertIn('const input = process.argv.slice(2).join(" ").trim();', render_js)
                self.assertIn('childProcess.spawnSync("claude", [input]', render_js)
                self.assertIn('const bridgePath = path.join(__dirname, "bridge", "run.js");', render_js)
                self.assertEqual(render_bat, '@echo off\r\ncd /d "%~dp0"\r\nnode "%~dp0render.js" %*\r\n')

    def test_skill_pack_api_rename_package(self) -> None:
        from app.main import app
        from app.storage.skill_packages import skill_package_dir, write_skill_package_files

        slug_old = "z_rename_unit_src"
        slug_new = "rename_unit_dst"
        bundle_slug = "rename_tests_bundle"

        manifest = {
            "name": slug_old,
            "description": "test",
            "version": "1.0.0",
            "entry": {
                "execution": "./execution.json",
                "recovery": "./recovery.json",
                "inputs": "./inputs.json",
            },
        }

        with _temporary_skill_package_root():
            write_skill_package_files(
                bundle_slug,
                slug_old,
                {
                    "execution.json": "[]",
                    "recovery.json": "{}",
                    "inputs.json": "{}",
                    "manifest.json": json.dumps(manifest),
                },
            )

            client = TestClient(app)
            res = client.patch(
                f"/skill-pack/bundles/{bundle_slug}/workflows/{slug_old}",
                json={"new_name": "Rename Unit Dst"},
            )
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json()
            self.assertEqual(data["package_name"], slug_new)
            self.assertEqual(data["previous_name"], slug_old)

            list_res = client.get("/skill-pack/packages")
            self.assertEqual(list_res.status_code, 200, list_res.text)
            self.assertIn("bundle_root", list_res.json())
            names = {p["package_name"] for p in list_res.json()["packages"]}
            self.assertIn(bundle_slug, names)

            man = json.loads((skill_package_dir(bundle_slug, slug_new) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(man["name"], slug_new)

    def test_rename_package_bundle_root_moves_directory(self) -> None:
        import shutil
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.storage import skill_packages as sp

        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "skill_package").mkdir(parents=True)
            (tmp / "skill_package" / "workflows").mkdir()

            with patch.object(sp, "PROJECT_ROOT", tmp):
                with self.assertRaises(ValueError):
                    sp.rename_package_bundle_root("my_agent_pack")
                self.assertEqual(sp.package_bundle_root_name(), "output/skill_package")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_build_skill_package_persists_step_visuals_and_exports_them(self) -> None:
        from app.config import settings
        from app.services.skill_pack_builder import build_skill_package, build_skill_package_zip
        from app.storage.skill_packages import skill_package_dir

        payload = {
            "package_meta": {
                "source_session_id": "sess_visual_assets",
                "title": "Delete Database Visual Assets Test",
            },
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
                with _temporary_skill_package_root():
                    with patch(
                        "app.services.skill_pack_builder.structure_steps_with_llm",
                        return_value=_structured_workflow_with_visuals(),
                    ):
                        package = build_skill_package(json.dumps(payload))

                    package_name = package["name"]
                    visuals_dir = skill_package_dir("default", package_name) / "visuals"
                    self.assertEqual(package_name, "delete_database_visual_assets_test")
                    self.assertEqual((visuals_dir / "Image_0.jpg").read_bytes(), b"launch-image")
                    self.assertEqual((visuals_dir / "Image_1.jpg").read_bytes(), b"step-one-image")
                    self.assertEqual((visuals_dir / "Image_2.png").read_bytes(), b"step-two-image")
                    recovery = json.loads(package["recovery_json"])
                    self.assertEqual(recovery["steps"][0]["visual_ref"], "visuals/Image_2.png")
                    self.assertNotIn("visual_ref", next(step for step in recovery["steps"] if step["step_id"] == 4))

                    filename, zipped = build_skill_package_zip(
                        package_name=package_name,
                        skill_md=package["skill_md"],
                        inputs_json=package["inputs_json"],
                        manifest_json=package["manifest_json"],
                        execution_json=package["execution_json"],
                        recovery_json=package["recovery_json"],
                    )

                    self.assertEqual(filename, "default_delete_database_visual_assets_test.zip")
                    wf_base = "default/workflows/delete_database_visual_assets_test"
                    bundle_base = "default"
                    with ZipFile(BytesIO(zipped)) as archive:
                        names = archive.namelist()
                        self.assertIn(f"{bundle_base}/claude/skills/default/SKILL.md", names)
                        self.assertIn(
                            f"{wf_base}/visuals/Image_0.jpg",
                            names,
                        )
                        self.assertIn(
                            f"{wf_base}/visuals/Image_1.jpg",
                            names,
                        )
                        self.assertIn(
                            f"{wf_base}/visuals/Image_2.png",
                            names,
                        )
                        self.assertEqual(
                            archive.read(
                                f"{wf_base}/visuals/Image_0.jpg",
                            ),
                            b"launch-image",
                        )

    def test_install_script_registration_block_is_deduplicated_and_uses_expected_paths(self) -> None:
        from app.storage.skill_packages import format_install_js_text

        install_js = format_install_js_text("render")
        self.assertIn('const source = path.join(__dirname, "claude", "skills", skillName);', install_js)
        self.assertIn('const target = path.join(claudeRoot, "skills", skillName);', install_js)
        self.assertIn('const claudeCandidates = [path.join(claudeRoot, "CLAUDE.md"), path.join(claudeRoot, "Claude.md")];', install_js)
        self.assertIn('* **render** (~/.claude/skills/render/SKILL.md) - Render automation workflows. Trigger: /render', install_js)
        self.assertIn('* mentions render automation tasks', install_js)
        self.assertIn('* OR uses /render', install_js)
        self.assertIn('if (!existing.includes(`# ${skillName}`) && !existing.includes(`skill: \\"${skillName}\\"`)) {', install_js)
        self.assertNotIn('require("playwright")', install_js)

    def test_recovery_get_visual_ref_supports_expected_extensions(self) -> None:
        from app.services.skill_pack_builder import get_visual_ref

        with tempfile.TemporaryDirectory() as tmp:
            visuals_dir = Path(tmp)
            for index, suffix in enumerate((".png", ".jpg", ".jpeg", ".webp"), start=1):
                (visuals_dir / f"Image_{index}{suffix}").write_bytes(b"img")
                self.assertEqual(get_visual_ref(index, visuals_dir), f"visuals/Image_{index}{suffix}")
            self.assertIsNone(get_visual_ref(99, visuals_dir))

    def test_recovery_generation_omits_non_action_steps_and_rejects_generic_content(self) -> None:
        from app.services.skill_pack_builder import generate_recovery

        recovery = generate_recovery(
            {
                "goal": "Mixed",
                "steps": [
                    {"type": "navigate", "url": "https://example.test"},
                    {"type": "scroll", "delta_y": 200},
                    {"type": "fill", "selector": "input[name=email]", "value": "{{user_email}}"},
                    {"type": "click", "selector": "text=Continue"},
                ],
            }
        )
        self.assertEqual([step["step_id"] for step in recovery["steps"]], [3, 4])
        self.assertTrue(all("validation" not in json.dumps(step).lower() for step in recovery["steps"]))
        self.assertTrue(all("scroll" not in json.dumps(step).lower() for step in recovery["steps"]))

        with self.assertRaises(ValueError):
            generate_recovery(
                {
                    "goal": "Bad",
                    "steps": [
                        {"type": "fill", "selector": "input[name=input]", "value": "{{value}}"},
                        {"type": "click", "selector": "//button"},
                    ],
                }
            )

    def test_build_skill_package_enumerates_multiple_workflows_from_single_payload(self) -> None:
        from app.services.skill_pack_builder import build_skill_package
        from app.storage.skill_packages import bundle_root_dir

        with _temporary_skill_package_root():
            with patch(
                "app.services.skill_pack_builder.structure_steps_with_llm",
                side_effect=[_structured_workflow(), _structured_workflow_two()],
            ):
                package = build_skill_package(json.dumps(_multi_workflow_payload()), bundle_slug="render")

            self.assertEqual(set(package["workflow_names"]), {"delete_database", "delete_web_service"})
            bundle_root = bundle_root_dir("render")
            assert bundle_root is not None
            self.assertTrue((bundle_root / "workflows" / "delete_database").is_dir())
            self.assertTrue((bundle_root / "workflows" / "delete_web_service").is_dir())
            skill_text = (bundle_root / "claude" / "skills" / "render" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn('"workflow": "delete_database"', skill_text)
            self.assertIn('"workflow": "delete_web_service"', skill_text)

    def test_existing_visuals_are_preserved_when_workflow_is_rewritten(self) -> None:
        from app.services.skill_pack_builder import build_skill_package
        from app.storage.skill_packages import skill_package_dir

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow_with_visuals()):
                package = build_skill_package(json.dumps(_raw_workflow()), package_name="delete_database_visual_assets_test")

            visuals_dir = skill_package_dir("default", package["name"]) / "visuals"
            visuals_dir.mkdir(parents=True, exist_ok=True)
            existing = visuals_dir / "Image_0.jpg"
            existing.write_bytes(b"keep-me")
            before = existing.read_bytes()

            with patch("app.services.skill_pack_builder.structure_steps_with_llm", return_value=_structured_workflow_with_visuals()):
                build_skill_package(json.dumps(_raw_workflow()), package_name="delete_database_visual_assets_test")

            self.assertEqual(existing.read_bytes(), before)

    def test_runtime_files_contain_expected_static_behaviors(self) -> None:
        from app.storage.skill_packages import format_render_bat_text, read_bridge_files, read_cli_files, read_engine_files

        engine_files = read_engine_files()
        bridge_files = read_bridge_files()
        cli_files = read_cli_files("render")
        self.assertIn("executeWorkflow(name, inputs = {})", engine_files["executor.js"])
        self.assertIn("execution.json for ${name} must be a JSON array.", engine_files["executor.js"])
        self.assertIn('console.log(`[executor] step ${index + 1}: ${JSON.stringify(rendered)}`);', engine_files["executor.js"])
        self.assertNotIn("waitFor", engine_files["executor.js"])
        self.assertNotIn("recoverStep", engine_files["executor.js"])
        self.assertIn("JSON.parse(raw)", bridge_files["run.js"])
        self.assertIn("Array.isArray(plan)", bridge_files["run.js"])
        self.assertIn("validateEntry(entry, index)", bridge_files["run.js"])
        self.assertIn('childProcess.spawnSync("claude", [input]', cli_files["render.js"])
        self.assertIn("extractFirstJsonArray", cli_files["render.js"])
        self.assertIn('process.execPath, [bridgePath, JSON.stringify(plan)]', cli_files["render.js"])
        self.assertEqual(format_render_bat_text("render"), '@echo off\r\ncd /d "%~dp0"\r\nnode "%~dp0render.js" %*\r\n')
