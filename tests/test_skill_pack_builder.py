"""Regression tests for the LLM-first Skill Pack Builder."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
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


@contextmanager
def _patched_pack_llm_settings(**values: object) -> Iterator[None]:
    from app.config import settings
    from app.llm import pack_llm_keys

    defaults: dict[str, object] = {
        "pack_llm_enabled": True,
        "pack_llm_provider": "",
        "pack_llm_endpoint": "",
        "pack_llm_api_key": "",
        "pack_llm_api_keys": "",
        "pack_llm_model": "",
        "pack_llm_gemini_endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "pack_llm_gemini_api_key": "",
        "pack_llm_gemini_api_keys": "",
        "pack_llm_gemini_model": "gemini-2.5-flash",
        "pack_llm_nvidia_endpoint": "https://integrate.api.nvidia.com/v1",
        "pack_llm_nvidia_api_key": "",
        "pack_llm_nvidia_api_keys": "",
        "pack_llm_nvidia_model": "z-ai/glm-5.1",
        "pack_llm_timeout_ms": 600000,
        "pack_llm_max_attempts": 1,
        "pack_llm_structure_temperature": 0.0,
        "pack_llm_structure_max_tokens": None,
        "pack_llm_top_p": None,
        "llm_api_key": "",
        "llm_api_keys": "",
    }
    defaults.update(values)
    old_idx = pack_llm_keys._PACK_KEY_IDX
    pack_llm_keys._PACK_KEY_IDX = 0
    try:
        with ExitStack() as stack:
            for name, value in defaults.items():
                stack.enter_context(patch.object(settings, name, value))
            yield
    finally:
        pack_llm_keys._PACK_KEY_IDX = old_idx


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
        from app.services.skill_pack.compiler import preprocess_skill_pack_declarations

        raw = {"steps": [{"a": 1}], "inputs": []}
        _ = preprocess_skill_pack_declarations(raw)
        self.assertIn("inputs", raw)

    def test_preprocess_declarations_strips_blocks_recursive(self) -> None:
        from app.services.skill_pack.compiler import preprocess_skill_pack_declarations

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
        from app.services.skill_pack.compiler import sanitize_raw_steps_for_llm

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
        self.assertNotIn("signals", slim[0])  # entire signals block removed
        self.assertEqual(slim[0]["extras"], {"meta": {}})
        self.assertIn("screenshot", heavy[0])  # original untouched

    def test_structure_steps_with_llm_passes_trimmed_steps_to_provider(self) -> None:
        from app.services.skill_pack.compiler import structure_steps_with_llm

        captured: list[list[dict]] = []

        def capture(steps: list) -> dict:
            captured.append(list(steps))
            return _structured_workflow()

        with patch("app.services.skill_pack.compiler._call_structuring_llm", side_effect=capture):
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


class SkillPackLLMProviderToggleTests(unittest.TestCase):
    def test_gemini_provider_resolves_endpoint_model_and_key(self) -> None:
        from app.llm.pack_llm_config import resolved_pack_llm_config
        from app.llm.pack_llm_keys import configured_pack_keys

        with _patched_pack_llm_settings(
            pack_llm_provider="gemini",
            pack_llm_endpoint="https://legacy.invalid/v1",
            pack_llm_model="gemini-2.5-pro",
            pack_llm_api_key="legacy-pack-key",
            pack_llm_gemini_endpoint="https://generativelanguage.googleapis.com/v1beta/openai/",
            pack_llm_gemini_model="gemini-2.5-flash",
            pack_llm_gemini_api_key="gemini-single",
        ):
            cfg = resolved_pack_llm_config()
            keys = configured_pack_keys()

        self.assertEqual(cfg.provider, "gemini")
        self.assertEqual(cfg.endpoint, "https://generativelanguage.googleapis.com/v1beta/openai/")
        self.assertEqual(cfg.model, "gemini-2.5-pro")
        self.assertEqual(keys, ["gemini-single"])

    def test_nvidia_provider_resolves_endpoint_model_and_key(self) -> None:
        from app.llm.pack_llm_config import resolved_pack_llm_config
        from app.llm.pack_llm_keys import configured_pack_keys

        with _patched_pack_llm_settings(
            pack_llm_provider="nvidia",
            pack_llm_model="deepseek-ai/deepseek-v4-flash",
            pack_llm_api_key="legacy-pack-key",
            llm_api_key="legacy-general-key",
            pack_llm_nvidia_endpoint="https://integrate.api.nvidia.com/v1",
            pack_llm_nvidia_model="z-ai/glm-5.1",
            pack_llm_nvidia_api_key="nvidia-single",
        ):
            cfg = resolved_pack_llm_config()
            keys = configured_pack_keys()

        self.assertEqual(cfg.provider, "nvidia")
        self.assertEqual(cfg.endpoint, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(cfg.model, "deepseek-ai/deepseek-v4-flash")
        self.assertEqual(keys, ["nvidia-single"])

    def test_provider_keys_rotate_round_robin(self) -> None:
        from app.llm.pack_llm_keys import next_pack_api_key

        with _patched_pack_llm_settings(
            pack_llm_provider="gemini",
            pack_llm_gemini_api_keys="gemini-a, gemini-b",
            pack_llm_gemini_api_key="gemini-single",
        ):
            self.assertEqual(next_pack_api_key(), ("gemini-a", 1, 2))
            self.assertEqual(next_pack_api_key(), ("gemini-b", 2, 2))
            self.assertEqual(next_pack_api_key(), ("gemini-a", 1, 2))

    def test_selected_provider_without_provider_key_fails_before_request(self) -> None:
        from app.services.skill_pack import llm as pack_llm

        logs: list[dict[str, object]] = []
        with _patched_pack_llm_settings(
            pack_llm_provider="nvidia",
            pack_llm_api_keys="legacy-pack-key",
            pack_llm_nvidia_api_key="",
            pack_llm_nvidia_api_keys="",
        ), patch("app.services.skill_pack.llm.request.urlopen") as urlopen_mock, patch(
            "app.services.skill_pack.llm.skill_pack_log_append", side_effect=logs.append
        ):
            with self.assertRaisesRegex(ValueError, "SKILL_PACK_LLM_NVIDIA_API_KEYS"):
                pack_llm._call_structuring_llm([{"action": "click"}])

        urlopen_mock.assert_not_called()
        missing_key_log = next(row for row in logs if row.get("kind") == "llm_missing_api_key")
        self.assertEqual(missing_key_log["provider"], "nvidia")

    def test_gemini_request_includes_json_response_format(self) -> None:
        from app.services.skill_pack import llm as pack_llm

        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps({"goal": "Toggle", "steps": []})
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(req: object, timeout: float) -> FakeResponse:
            captured["url"] = getattr(req, "full_url")
            captured["authorization"] = req.get_header("Authorization")
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        logs: list[dict[str, object]] = []
        with _patched_pack_llm_settings(
            pack_llm_provider="gemini",
            pack_llm_endpoint="https://integrate.api.nvidia.com/v1",
            pack_llm_model="gemini-2.5-pro",
            pack_llm_gemini_api_key="gemini-key",
            pack_llm_gemini_model="gemini-2.5-flash",
        ), patch("app.services.skill_pack.llm.request.urlopen", side_effect=fake_urlopen), patch(
            "app.services.skill_pack.llm.skill_pack_log_append", side_effect=logs.append
        ):
            out = pack_llm._call_structuring_llm([{"action": "click"}])

        body = captured["body"]
        assert isinstance(body, dict)
        self.assertEqual(out, {"goal": "Toggle", "steps": []})
        self.assertEqual(captured["authorization"], "Bearer gemini-key")
        self.assertEqual(
            captured["url"],
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertEqual(body["model"], "gemini-2.5-pro")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        request_log = next(row for row in logs if row.get("kind") == "llm_request_sent")
        self.assertEqual(request_log["provider"], "gemini")
        self.assertEqual(request_log["model"], "gemini-2.5-pro")
        self.assertEqual(request_log["host"], "generativelanguage.googleapis.com")
        self.assertTrue(request_log["strict_json_response"])

    def test_nvidia_request_omits_json_response_format(self) -> None:
        from app.services.skill_pack import llm as pack_llm

        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps({"goal": "Toggle", "steps": []})
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(req: object, timeout: float) -> FakeResponse:
            captured["url"] = getattr(req, "full_url")
            captured["authorization"] = req.get_header("Authorization")
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        logs: list[dict[str, object]] = []
        with _patched_pack_llm_settings(
            pack_llm_provider="nvidia",
            pack_llm_nvidia_api_key="nvidia-key",
            pack_llm_nvidia_model="z-ai/glm-5.1",
        ), patch("app.services.skill_pack.llm.request.urlopen", side_effect=fake_urlopen), patch(
            "app.services.skill_pack.llm.skill_pack_log_append", side_effect=logs.append
        ):
            out = pack_llm._call_structuring_llm([{"action": "click"}])

        body = captured["body"]
        assert isinstance(body, dict)
        self.assertEqual(out, {"goal": "Toggle", "steps": []})
        self.assertEqual(captured["authorization"], "Bearer nvidia-key")
        self.assertEqual(body["model"], "z-ai/glm-5.1")
        self.assertNotIn("response_format", body)
        request_log = next(row for row in logs if row.get("kind") == "llm_request_sent")
        self.assertEqual(request_log["provider"], "nvidia")
        self.assertEqual(request_log["model"], "z-ai/glm-5.1")
        self.assertEqual(request_log["host"], "integrate.api.nvidia.com")
        self.assertFalse(request_log["strict_json_response"])


class SkillPackBuilderTests(unittest.TestCase):
    def test_structure_steps_with_llm_validates_provider_json(self) -> None:
        from app.services.skill_pack.compiler import structure_steps_with_llm

        with patch("app.services.skill_pack.compiler._call_structuring_llm", return_value=_structured_workflow()):
            structured = structure_steps_with_llm(_raw_workflow()["steps"])

        self.assertEqual(structured["goal"], "Delete Database")
        self.assertEqual(structured["steps"][1], {"type": "fill", "selector": "input[name=email]", "value": "{{user_email}}"})

    def test_compile_execution_preserves_scroll_steps(self) -> None:
        from app.services.skill_pack.compiler import compile_execution, generate_execution_plan

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

    def test_compile_execution_supports_exact_url_check(self) -> None:
        from app.services.skill_pack.compiler import compile_execution

        structured = {
            "goal": "Verify page",
            "steps": [
                {"type": "navigate", "url": "https://example.test/app"},
                {"type": "check", "kind": "url_exact", "url": "https://example.test/app"},
                {"type": "check", "kind": "url_must_be", "check_pattern": "https://example.test/settings"},
            ],
        }

        self.assertEqual(
            compile_execution(structured),
            [
                {"type": "navigate", "url": "https://example.test/app"},
                {"type": "check", "kind": "url_exact", "url": "https://example.test/app"},
                {"type": "check", "kind": "url_exact", "url": "https://example.test/settings"},
            ],
        )

    def test_compile_execution_passes_steps_and_adds_only_minimal_guards(self) -> None:
        from app.services.skill_pack.compiler import compile_execution, generate_execution_plan

        plan = compile_execution(_structured_workflow())

        self.assertEqual(
            plan,
            [
                {"type": "navigate", "url": "https://example.test/login"},
                {"type": "fill", "selector": "input[name=email]", "value": "{{user_email}}"},
                {"type": "fill", "selector": "input[name=password]", "value": "{{user_password}}"},
                {"type": "click", "selector": "text=Sign in"},
                {"type": "click", "selector": "text={{db_name}}"},
                {"type": "click", "selector": "text=Delete Database"},
            ],
        )
        self.assertNotIn('"wait"', json.dumps(plan))

        execution_md, md_plan = generate_execution_plan(_structured_workflow())
        self.assertEqual(md_plan, plan)
        self.assertNotIn("assert_visible", execution_md)

    def test_validation_rejects_wait_xpath_and_generic_selectors(self) -> None:
        from app.services.skill_pack.compiler import compile_execution, structure_steps_with_llm

        bad_payloads = [
            {"goal": "Bad", "steps": [{"type": "click", "selector": "button"}]},
            {"goal": "Bad", "steps": [{"type": "fill", "selector": "input", "value": "{{email}}"}]},
            {"goal": "Bad", "steps": [{"type": "click", "selector": "//button"}]},
            {"goal": "Bad", "steps": [{"type": "wait", "selector": "text=Done"}]},
        ]

        for payload in bad_payloads:
            with self.subTest(payload=payload), patch("app.services.skill_pack.compiler._call_structuring_llm", return_value=payload):
                with self.assertRaises(ValueError):
                    structure_steps_with_llm([{"raw": True}])

        with self.assertRaises(ValueError):
            compile_execution({"goal": "Bad", "steps": [{"type": "wait", "selector": "text=Done"}]})

    def test_generate_recovery_uses_structured_steps(self) -> None:
        from app.services.skill_pack.compiler import generate_recovery

        recovery = generate_recovery(_structured_workflow())
        self.assertEqual(generate_recovery(_structured_workflow()), recovery)
        self.assertEqual([step["step_id"] for step in recovery["steps"]], [2, 3, 4, 5, 6])

        delete_entry = next(step for step in recovery["steps"] if step["step_id"] == 6)
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
        from app.services.skill_pack.compiler import build_manifest, parse_inputs

        inputs = parse_inputs(_structured_workflow())
        self.assertEqual([item["name"] for item in inputs], ["user_email", "user_password", "db_name"])
        self.assertTrue(inputs[1]["sensitive"])

        manifest = build_manifest(inputs, "delete_database")
        self.assertEqual(manifest["name"], "delete_database")
        self.assertEqual(manifest["entry"]["execution"], "./execution.json")
        self.assertEqual(manifest["entry"]["recovery"], "./recovery.json")
        self.assertEqual(manifest["entry"]["input"], "./input.json")
        self.assertEqual(manifest["execution_mode"], "deterministic")
        self.assertEqual(manifest["recovery_mode"], "tiered")
        self.assertTrue(manifest["vision_enabled"])
        self.assertFalse(manifest["llm_required"])
        self.assertEqual([item["name"] for item in manifest["inputs"]], ["user_email", "user_password", "db_name"])

    def test_build_skill_package_writes_clean_outputs(self) -> None:
        from app.services.skill_pack.compiler import build_skill_package

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                package = build_skill_package(json.dumps(_raw_workflow()), bundle_slug="render")

            execution = json.loads(package["execution_json"])
            index = json.loads(package["index_json"])
            self.assertEqual(package["name"], "delete_database_recording")
            # New layout: index has "skills" key instead of "workflows"
            index_by_name = {item["name"]: item for item in index["skills"]}
            self.assertIn("delete_database_recording", index_by_name)
            self.assertEqual(
                index_by_name["delete_database_recording"]["execution"],
                "skills/delete_database_recording/execution.json",
            )
            self.assertTrue(package["used_llm"])
            self.assertEqual(package["input_count"], 3)
            self.assertNotIn("skill_json", package)
            self.assertNotIn("execution_md", package)
            self.assertNotIn("execution_plan_json", package)
            self.assertFalse(any(step["type"] == "wait" for step in execution))
            self.assertIn({"type": "click", "selector": "text=Delete Database"}, execution)

    def test_build_skill_package_writes_skill_files_in_new_layout(self) -> None:
        from app.services.skill_pack.compiler import build_skill_package
        from app.storage.skill_packages import bundle_root_dir

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                package = build_skill_package(json.dumps(_raw_workflow()), bundle_slug="render")

            wf_name = package["name"]
            br = bundle_root_dir("render")
            self.assertIsNotNone(br)
            assert br is not None
            # Per-skill SKILL.md under skills/{wf}/SKILL.md
            skill_md_path = br / "skills" / wf_name / "SKILL.md"
            self.assertTrue(skill_md_path.is_file())
            # Plugin index {slug}.json at bundle root
            plugin_index_path = br / "render.json"
            self.assertTrue(plugin_index_path.is_file())
            plugin_index = json.loads(plugin_index_path.read_text(encoding="utf-8"))
            skill_names = [s["name"] for s in plugin_index["skills"]]
            self.assertIn(wf_name, skill_names)
            # CLAUDE.md exists
            self.assertTrue((br / "CLAUDE.md").is_file())
            # Legacy dirs should NOT exist
            self.assertFalse((br / ".opencode").exists())
            self.assertFalse((br / ".codex").exists())
            self.assertFalse((br / "claude").exists())

    def test_building_multiple_workflows_creates_multiple_bundle_folders(self) -> None:
        from app.services.skill_pack.compiler import build_skill_package
        from app.storage.skill_packages import read_skill_package_files

        with _temporary_skill_package_root():
            with patch(
                "app.services.skill_pack.compiler.structure_steps_with_llm",
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
            index_by_name = {item["name"]: item for item in index["skills"]}
            self.assertEqual(set(index_by_name), {"delete_database", "delete_web_service"})
            self.assertEqual(
                index_by_name["delete_database"]["execution"],
                "skills/delete_database/execution.json",
            )
            self.assertEqual(
                index_by_name["delete_web_service"]["execution"],
                "skills/delete_web_service/execution.json",
            )
            first_files = read_skill_package_files("default", first["name"])
            self.assertIsNotNone(first_files)
            if first_files:
                self.assertIn("SKILL.md", first_files)
            second_files = read_skill_package_files("default", second["name"])
            self.assertIsNotNone(second_files)
            if second_files:
                self.assertNotIn("skill.md", second_files)

    def test_append_workflow_creates_new_folder_and_keeps_existing_files_unchanged(self) -> None:
        from app.services.skill_pack.compiler import append_workflow_to_skill_package, build_skill_package
        from app.storage.skill_packages import read_skill_package_files

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                build_skill_package(json.dumps(_raw_workflow()), package_name="delete_database", bundle_slug="default")

            before = read_skill_package_files("default", "delete_database")
            assert before is not None

            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow_two()):
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
            index_skills = json.loads(appended["index_json"])["skills"]
            skill_names = {s["name"] for s in index_skills}
            self.assertEqual(skill_names, {"delete_database", "delete_web_service"})

    def test_skill_pack_build_error_includes_build_log_payload(self) -> None:
        from app.main import app
        from app.config import settings

        def _boom(_raw_steps: object) -> dict:
            raise ValueError("simulated structuring failure")

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", side_effect=_boom):
                with patch.object(settings, "auth_required", False):
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

    def test_skill_pack_build_log_includes_preprocess_and_llm_size_metrics(self) -> None:
        from app.services.skill_pack.compiler import build_skill_package

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler._call_structuring_llm", return_value=_structured_workflow()):
                package = build_skill_package(json.dumps(_raw_workflow()), bundle_slug="default")

        build_log = package["build_log"]
        preprocess_done = [
            row
            for row in build_log
            if row.get("kind") == "preprocess_phase" and row.get("state") == "done"
        ]
        self.assertTrue(preprocess_done)
        self.assertTrue(
            all(
                "before_chars" in row
                and "after_chars" in row
                and "removed_chars" in row
                for row in preprocess_done
            )
        )

        # Verify pipeline_phase entries are emitted during compilation
        pipeline_kinds = {row.get("kind") for row in build_log if isinstance(row, dict)}
        self.assertIn("persist_phase", pipeline_kinds)

    def test_skill_pack_build_stream_emits_log_and_done_sse(self) -> None:
        from app.main import app
        from app.config import settings

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                with patch.object(settings, "auth_required", False):
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

    def test_unlocked_skill_package_writer_can_run_inside_bundle_lock(self) -> None:
        from app.storage.skill_packages import (
            _bundle_write_lock,
            write_skill_package_files_unlocked,
        )

        manifest = {
            "name": "inside_lock",
            "description": "test",
            "version": "1.0.0",
            "entry": {
                "execution": "./execution.json",
                "recovery": "./recovery.json",
                "input": "./input.json",
            },
        }

        with _temporary_skill_package_root():
            with _bundle_write_lock("inside_lock_bundle"):
                workflow_dir = write_skill_package_files_unlocked(
                    "inside_lock_bundle",
                    "inside_lock",
                    {
                        "execution.json": "[]",
                        "recovery.json": "{}",
                        "input.json": "{}",
                        "manifest.json": json.dumps(manifest),
                    },
                )

            self.assertTrue((workflow_dir / "manifest.json").is_file())
            self.assertTrue((workflow_dir.parent.parent / "inside_lock_bundle.json").is_file())

    def test_skill_pack_append_stream_emits_log_and_done_sse(self) -> None:
        from app.main import app
        from app.config import settings

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                with patch.object(settings, "auth_required", False):
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

            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow_two()):
                with patch.object(settings, "auth_required", False):
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
        from app.config import settings

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                with patch.object(settings, "auth_required", False):
                    client = TestClient(app)
                    build_response = client.post("/skill-pack/build", json={"json_text": json.dumps(_raw_workflow())})
                    self.assertEqual(build_response.status_code, 200)
                    payload = build_response.json()
                    self.assertIn("index_json", payload)
                    index_by_name = {item["name"]: item for item in json.loads(payload["index_json"])["skills"]}
                    self.assertIn("delete_database_recording", index_by_name)
                    self.assertEqual(
                        index_by_name["delete_database_recording"]["execution"],
                        "skills/delete_database_recording/execution.json",
                    )
                    files_response = client.get(f"/skill-pack/bundles/default")
                    self.assertEqual(files_response.status_code, 200)
                    files_payload = files_response.json()
                    self.assertEqual(files_payload["package_name"], "default")
                    fn = files_payload["files"]
                    wf_prefix = f"skills/{payload['name']}/"
                    self.assertIn("default.json", fn)
                    self.assertIn("README.md", fn)
                    self.assertNotIn("orchestration/index.md", fn)
                    self.assertNotIn("install.js", fn)
                    self.assertNotIn("install.bat", fn)
                    self.assertNotIn("index.json", fn)
                    self.assertNotIn("skill.json", fn)
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
            bundle_folder = "default-plugin"
            wf_name = payload["name"]
            skill_root = f"{bundle_folder}/skills/{wf_name}"
            with ZipFile(BytesIO(export_response.content)) as archive:
                names = archive.namelist()
                # Bundle-level files
                self.assertIn(f"{bundle_folder}/default.json", names)
                self.assertIn(f"{bundle_folder}/README.md", names)
                self.assertIn(f"{bundle_folder}/CLAUDE.md", names)
                # Gen 1 JS files must NOT be present (data-only zip)
                self.assertNotIn(f"{bundle_folder}/execution/executor.js", names)
                self.assertNotIn(f"{bundle_folder}/execution/tracker.js", names)
                self.assertNotIn(f"{bundle_folder}/package.json", names)
                # Per-skill files
                self.assertIn(f"{skill_root}/SKILL.md", names)
                self.assertIn(f"{skill_root}/execution.json", names)
                self.assertIn(f"{skill_root}/recovery.json", names)
                # Removed files must not exist
                self.assertNotIn(f"{bundle_folder}/auth/auth.json", names)
                self.assertNotIn(f"{bundle_folder}/auth/credentials.example.json", names)
                self.assertNotIn(f"{bundle_folder}/orchestration/index.md", names)
                self.assertNotIn(f"{bundle_folder}/orchestration/planner.md", names)
                self.assertNotIn(f"{bundle_folder}/orchestration/schema.json", names)
                self.assertNotIn(f"{skill_root}/input.json", names)
                self.assertNotIn(f"{skill_root}/manifest.json", names)
                self.assertNotIn(f"{skill_root}/tests/test-cases.json", names)
                # Old files must not exist
                self.assertNotIn(f"{bundle_folder}/install.js", names)
                self.assertNotIn(f"{bundle_folder}/install.bat", names)
                self.assertNotIn(f"{bundle_folder}/render.js", names)
                self.assertNotIn(f"{bundle_folder}/index.json", names)
                self.assertNotIn(f"{bundle_folder}/engine/executor.js", names)
                self.assertNotIn(f"{bundle_folder}/bridge/run.js", names)
                # Content checks
                plugin_index = json.loads(archive.read(f"{bundle_folder}/default.json"))
                self.assertEqual(plugin_index["skills"][0]["execution"], f"skills/{wf_name}/execution.json")
                self.assertEqual(plugin_index["skills"][0]["recovery"], f"skills/{wf_name}/recovery.json")

    def test_skill_pack_api_rename_package(self) -> None:
        from app.main import app
        from app.config import settings
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
                "input": "./input.json",
            },
        }

        with _temporary_skill_package_root():
            write_skill_package_files(
                bundle_slug,
                slug_old,
                {
                    "execution.json": "[]",
                    "recovery.json": "{}",
                    "input.json": "{}",
                    "manifest.json": json.dumps(manifest),
                },
            )

            with patch.object(settings, "auth_required", False):
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
        from app.services.skill_pack.compiler import build_skill_package, build_skill_package_zip
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
                    with patch.object(
                        settings, "pack_recovery_vision_enabled", False
                    ), patch(
                        "app.services.skill_pack.compiler.structure_steps_with_llm",
                        return_value=_structured_workflow_with_visuals(),
                    ), patch(
                        "app.llm.anchor_vision_llm.generate_anchors_from_image_bytes",
                        side_effect=AssertionError(
                            "package build should not call vision recovery by default"
                        ),
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
                    self.assertNotIn("visual_ref", next(step for step in recovery["steps"] if step["step_id"] == 3))

                    filename, zipped = build_skill_package_zip(
                        package_name=package_name,
                        skill_md=package["skill_md"],
                        inputs_json=package["inputs_json"],
                        manifest_json=package["manifest_json"],
                        execution_json=package["execution_json"],
                        recovery_json=package["recovery_json"],
                    )

                    self.assertEqual(filename, "default_delete_database_visual_assets_test.zip")
                    bundle_folder = "default-plugin"
                    skill_name = "delete_database_visual_assets_test"
                    skill_base = f"{bundle_folder}/skills/{skill_name}"
                    with ZipFile(BytesIO(zipped)) as archive:
                        names = archive.namelist()
                        self.assertIn(f"{bundle_folder}/default.json", names)
                        self.assertIn(f"{skill_base}/SKILL.md", names)
                        self.assertIn(f"{skill_base}/visuals/Image_0.jpg", names)
                        self.assertIn(f"{skill_base}/visuals/Image_1.jpg", names)
                        self.assertIn(f"{skill_base}/visuals/Image_2.png", names)
                        self.assertEqual(archive.read(f"{skill_base}/visuals/Image_0.jpg"), b"launch-image")

    def test_recovery_get_visual_ref_supports_expected_extensions(self) -> None:
        from app.services.skill_pack.compiler import get_visual_ref

        with tempfile.TemporaryDirectory() as tmp:
            visuals_dir = Path(tmp)
            for index, suffix in enumerate((".png", ".jpg", ".jpeg", ".webp"), start=1):
                (visuals_dir / f"Image_{index}{suffix}").write_bytes(b"img")
                self.assertEqual(get_visual_ref(index, visuals_dir), f"visuals/Image_{index}{suffix}")
            self.assertIsNone(get_visual_ref(99, visuals_dir))

    def test_recovery_generation_omits_non_action_steps_and_rejects_generic_content(self) -> None:
        from app.services.skill_pack.compiler import generate_recovery

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
        from app.services.skill_pack.compiler import build_skill_package
        from app.storage.skill_packages import bundle_root_dir

        with _temporary_skill_package_root():
            with patch(
                "app.services.skill_pack.compiler.structure_steps_with_llm",
                side_effect=[_structured_workflow(), _structured_workflow_two()],
            ):
                package = build_skill_package(json.dumps(_multi_workflow_payload()), bundle_slug="render")

            self.assertEqual(set(package["workflow_names"]), {"delete_database", "delete_web_service"})
            bundle_root = bundle_root_dir("render")
            assert bundle_root is not None
            self.assertTrue((bundle_root / "skills" / "delete_database").is_dir())
            self.assertTrue((bundle_root / "skills" / "delete_web_service").is_dir())
            # Plugin index should list both skills
            plugin_index = json.loads((bundle_root / "render.json").read_text(encoding="utf-8"))
            skill_names = {s["name"] for s in plugin_index["skills"]}
            self.assertIn("delete_database", skill_names)
            self.assertIn("delete_web_service", skill_names)

    def test_build_skill_package_compiles_workflow_llm_calls_concurrently(self) -> None:
        import threading
        import time

        from app.services.skill_pack.compiler import build_skill_package

        payload = {
            "skills": [
                {"title": f"Flow {index}", "steps": _raw_workflow()["steps"]}
                for index in range(7)
            ]
        }
        lock = threading.Lock()
        active = 0
        max_active = 0

        def slow_structuring(_steps: list[dict]) -> dict:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.1)
                return _structured_workflow()
            finally:
                with lock:
                    active -= 1

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", side_effect=slow_structuring):
                package = build_skill_package(json.dumps(payload), bundle_slug="render")

        self.assertEqual(len(package["workflow_names"]), 7)
        self.assertGreater(max_active, 1)
        self.assertLessEqual(max_active, 10)

    def test_build_skill_package_keeps_successful_workflows_when_one_llm_task_fails(self) -> None:
        from app.services.skill_pack.compiler import build_skill_package

        def structure_or_fail(raw_steps: list[dict]) -> dict:
            if any(
                str(step.get("target", {}).get("inner_text") or "") == "Settings"
                for step in raw_steps
                if isinstance(step, dict)
            ):
                return _structured_workflow_two()
            raise ValueError("simulated per-workflow failure")

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", side_effect=structure_or_fail):
                package = build_skill_package(json.dumps(_multi_workflow_payload()), bundle_slug="render")

        self.assertEqual(package["workflow_names"], ["delete_web_service"])
        log_blob = json.dumps(package["build_log"])
        self.assertIn("workflow_compile_failed", log_blob)
        self.assertIn("simulated per-workflow failure", log_blob)

    def test_existing_visuals_are_preserved_when_workflow_is_rewritten(self) -> None:
        from app.services.skill_pack.compiler import build_skill_package
        from app.storage.skill_packages import skill_package_dir

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow_with_visuals()):
                package = build_skill_package(json.dumps(_raw_workflow()), package_name="delete_database_visual_assets_test")

            visuals_dir = skill_package_dir("default", package["name"]) / "visuals"
            visuals_dir.mkdir(parents=True, exist_ok=True)
            existing = visuals_dir / "Image_0.jpg"
            existing.write_bytes(b"keep-me")
            before = existing.read_bytes()

            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow_with_visuals()):
                build_skill_package(json.dumps(_raw_workflow()), package_name="delete_database_visual_assets_test")

            self.assertEqual(existing.read_bytes(), before)

    def test_bundle_scaffold_creates_expected_directories(self) -> None:
        from app.storage.skill_packages import ensure_bundle_scaffold

        with _temporary_skill_package_root():
            root = ensure_bundle_scaffold("render")
            self.assertTrue((root / "skills").is_dir())
            self.assertTrue((root / "auth").is_dir())
            self.assertTrue((root / "execution").is_dir())
            self.assertFalse((root / "engine").exists())
            self.assertFalse((root / "bridge").exists())


# ─────────────────────────────────────────────────
# URL normalization
# ─────────────────────────────────────────────────

class TestNormalizeUrlPattern(unittest.TestCase):
    def _norm(self, url: str) -> str:
        from app.services.skill_pack.compiler import _normalize_url_pattern
        return _normalize_url_pattern(url)

    def test_plain_path_is_kept_literal(self) -> None:
        pattern = self._norm("https://dashboard.render.com/services")
        self.assertRegex(pattern, r"\^.*services.*\$")
        import re
        self.assertIsNotNone(re.match(pattern, "https://dashboard.render.com/services"))
        self.assertIsNone(re.match(pattern, "https://dashboard.render.com/settings"))

    def test_numeric_segment_replaced(self) -> None:
        pattern = self._norm("https://app.example.com/items/12345")
        self.assertIn("[^/]+", pattern)
        import re
        self.assertIsNotNone(re.match(pattern, "https://app.example.com/items/99999"))
        self.assertIsNotNone(re.match(pattern, "https://app.example.com/items/1"))

    def test_hex_id_segment_replaced(self) -> None:
        pattern = self._norm("https://app.example.com/deploys/a1b2c3d4e5f6")
        self.assertIn("[^/]+", pattern)
        import re
        self.assertIsNotNone(re.match(pattern, "https://app.example.com/deploys/deadbeefcafe"))

    def test_long_alphanumeric_segment_replaced(self) -> None:
        # 16+ char mixed segment that looks like a generated ID
        pattern = self._norm("https://dashboard.render.com/services/srv-cg1234567890abcdef")
        self.assertIn("[^/]+", pattern)
        import re
        self.assertIsNotNone(re.match(pattern, "https://dashboard.render.com/services/srv-aaaaaaaaaaaaaaaa"))

    def test_multiple_dynamic_segments(self) -> None:
        # /services/<id>/deploys/<id>
        pattern = self._norm("https://dashboard.render.com/services/srv-cg1234567890abcdef/deploys/dep-0q1234567890abcdef")
        self.assertEqual(pattern.count("[^/]+"), 2)

    def test_host_is_kept_literal_and_escaped(self) -> None:
        pattern = self._norm("https://my.app.example.com/page")
        self.assertIn(r"my\.app\.example\.com", pattern)

    def test_volatile_query_params_dropped(self) -> None:
        pattern = self._norm("https://app.example.com/search?q=hello&utm_source=email&ts=12345")
        import re
        self.assertIsNotNone(re.match(pattern, "https://app.example.com/search?q=hello"))
        # utm and ts stripped; q= should remain
        self.assertNotIn("utm", pattern)

    def test_empty_url_returns_empty(self) -> None:
        self.assertEqual(self._norm(""), "")

    def test_relative_url_returns_empty(self) -> None:
        self.assertEqual(self._norm("/services/123"), "")

    def test_pattern_anchored_start_and_end(self) -> None:
        pattern = self._norm("https://app.example.com/dashboard")
        self.assertTrue(pattern.startswith("^"))
        self.assertTrue(pattern.endswith("$"))


# ─────────────────────────────────────────────────
# url_state attachment to compiled steps
# ─────────────────────────────────────────────────

def _make_raw_steps_with_url_state(before_urls: list[str], after_urls: list[str]) -> list[dict]:
    """Build fake recorded events that carry url_state."""
    assert len(before_urls) == len(after_urls)
    steps = []
    for b, a in zip(before_urls, after_urls):
        steps.append({
            "action": {"action": "click"},
            "target": {"inner_text": "Click"},
            "page": {"url": b},
            "url_state": {
                "before": {"url": b, "title": "Before Page"},
                "after": {"url": a, "title": "After Page"},
            },
        })
    return steps


class TestBuildUrlStateForSteps(unittest.TestCase):
    def _call(self, exec_plan, raw_steps, skill_name="test_skill"):
        from app.services.skill_pack.compiler import _build_url_state_for_steps
        return _build_url_state_for_steps(exec_plan, raw_steps, skill_name)

    def test_attaches_url_state_to_each_step(self) -> None:
        exec_plan = [
            {"type": "click", "selector": "text=Deploy"},
            {"type": "fill", "selector": "input[name=branch]", "value": "{{branch}}"},
        ]
        raw = _make_raw_steps_with_url_state(
            ["https://dashboard.render.com/services/srv-cg1234567890abcdef",
             "https://dashboard.render.com/services/srv-cg1234567890abcdef/deploys"],
            ["https://dashboard.render.com/services/srv-cg1234567890abcdef/deploys",
             "https://dashboard.render.com/services/srv-cg1234567890abcdef/deploys/dep-0q1234567890abcdef"],
        )
        augmented, url_state_json = self._call(exec_plan, raw)
        self.assertEqual(len(augmented), 2)
        for step in augmented:
            self.assertIn("url_state", step)
            us = step["url_state"]
            self.assertIn("before", us)
            self.assertIn("after", us)
            self.assertEqual(set(us["before"]), {"url_pattern"})
            self.assertEqual(set(us["after"]), {"url_pattern"})
            self.assertNotIn("edited_by_user", us)

    def test_url_patterns_have_dynamic_id_replaced(self) -> None:
        exec_plan = [{"type": "click", "selector": "text=Deploy"}]
        raw = _make_raw_steps_with_url_state(
            ["https://dashboard.render.com/services/srv-cg1234567890abcdef"],
            ["https://dashboard.render.com/services/srv-cg1234567890abcdef/deploys"],
        )
        augmented, _ = self._call(exec_plan, raw)
        before_pattern = augmented[0]["url_state"]["before"]["url_pattern"]
        self.assertIn("[^/]+", before_pattern)
        import re
        self.assertIsNotNone(re.match(before_pattern, "https://dashboard.render.com/services/srv-aaaaaaaaaaaaaaaa"))

    def test_url_state_json_is_not_generated(self) -> None:
        exec_plan = [{"type": "click", "selector": "text=Deploy"}]
        raw = _make_raw_steps_with_url_state(
            ["https://app.example.com/page"],
            ["https://app.example.com/next"],
        )
        augmented, url_state_json = self._call(exec_plan, raw, skill_name="my_skill")
        self.assertEqual(url_state_json, "")
        self.assertIn("url_state", augmented[0])

    def test_no_url_state_in_raw_steps_produces_empty_states(self) -> None:
        exec_plan = [{"type": "click", "selector": "text=Deploy"}]
        raw = [{"action": {"action": "click"}, "target": {"inner_text": "Deploy"}}]
        augmented, url_state_json = self._call(exec_plan, raw)
        # No url_state attached when raw steps have none
        self.assertNotIn("url_state", augmented[0])
        self.assertEqual(url_state_json, "")

    def test_empty_execution_plan_returns_empty_states(self) -> None:
        _, url_state_json = self._call([], [])
        self.assertEqual(url_state_json, "")

    def test_url_state_stays_inline_and_no_url_state_file_written_to_skill_bundle(self) -> None:
        from app.services.skill_pack.compiler import build_skill_package
        from app.storage.skill_packages import read_skill_package_files

        raw = _raw_workflow()
        # Inject url_state into raw steps
        for step in raw["steps"]:
            step["url_state"] = {
                "before": {"url": "https://app.example.com/before", "title": "Before"},
                "after": {"url": "https://app.example.com/after", "title": "After"},
            }

        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                result = build_skill_package(json.dumps(raw), package_name="delete_database", bundle_slug="default")

        files = result.get("files") or {}
        self.assertNotIn("url_state.json", files)
        self.assertIn("url_state", result.get("execution_json", ""))

        from app.storage.skill_packages import read_skill_package_files
        with _temporary_skill_package_root():
            with patch("app.services.skill_pack.compiler.structure_steps_with_llm", return_value=_structured_workflow()):
                build_skill_package(json.dumps(raw), package_name="delete_database", bundle_slug="default")
            pkg_files = read_skill_package_files("default", "delete_database")
            self.assertIsNotNone(pkg_files)
            if pkg_files:
                self.assertNotIn("url_state.json", pkg_files)
                self.assertIn("url_state", pkg_files.get("execution.json", ""))


class TestCompilerBuildUrlState(unittest.TestCase):
    def test_compiler_url_state_contains_only_patterns(self) -> None:
        from app.compiler.build import _build_url_state

        state = _build_url_state({
            "url_state": {
                "before": {
                    "url": "https://dashboard.render.com/",
                    "title": "Render Dashboard",
                },
                "after": {
                    "url": "https://dashboard.render.com/d/dpg-d7v5mqvavr4c739h2or0-a",
                    "title_includes": "conxa-db Database Render Dashboard",
                },
                "edited_by_user": False,
            }
        })

        self.assertEqual(set(state), {"before", "after"})
        self.assertEqual(set(state["before"]), {"url_pattern"})
        self.assertEqual(set(state["after"]), {"url_pattern"})
        self.assertEqual(state["before"]["url_pattern"], r"^https://dashboard\.render\.com/$")
        self.assertEqual(state["after"]["url_pattern"], r"^https://dashboard\.render\.com/d/[^/]+$")
