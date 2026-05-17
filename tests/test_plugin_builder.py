"""Tests for app/services/plugin_builder.py — Phase 1 (Foundation)."""

from __future__ import annotations

import json
import re

from PIL import Image

from app.services.plugin_builder import (
    _build_workflow_from_saved_skill,
    _is_login_step,
    _normalize_saved_skill_inputs,
    _render_credentials_example,
    _render_license,
    _render_readme,
    build_plugin,
    strip_login_steps,
)




# ─────────────────────────────────────────────────
# _render_readme
# ─────────────────────────────────────────────────

class TestRenderReadme:
    def test_contains_plugin_name(self):
        md = _render_readme("Render.com", "render_abc", "https://render.com", ["deploy"])
        assert "Render.com" in md

    def test_contains_target_url(self):
        md = _render_readme("Test", "test_abc", "https://app.test.com", [])
        assert "https://app.test.com" in md

    def test_lists_skills(self):
        md = _render_readme("Test", "test_abc", "https://test.com", ["create-service", "deploy"])
        assert "create-service" in md
        assert "deploy" in md

    def test_contains_install_snippet(self):
        md = _render_readme("Test", "test_slug", "https://test.com", [])
        assert "npx -y conxa install" in md

    def test_install_snippet_uses_package_id_when_given(self):
        md = _render_readme("Test", "test_slug", "https://test.com", [], package_id="acme/x")
        assert "npx -y conxa install acme/x" in md

    def test_contains_auth_reference(self):
        md = _render_readme("Test", "test_slug", "https://test.com", [])
        assert "auth" in md.lower()


# ─────────────────────────────────────────────────
# _render_credentials_example
# ─────────────────────────────────────────────────

class TestRenderCredentialsExample:
    def test_valid_json(self):
        parsed = json.loads(_render_credentials_example())
        assert "username" in parsed
        assert "password" in parsed

    def test_has_comment(self):
        parsed = json.loads(_render_credentials_example())
        assert "_comment" in parsed


# ─────────────────────────────────────────────────
# _render_license
# ─────────────────────────────────────────────────

class TestRenderLicense:
    def test_contains_mit(self):
        assert "MIT License" in _render_license()

    def test_contains_year(self):
        import datetime
        year = str(datetime.datetime.now().year)
        assert year in _render_license()


# ─────────────────────────────────────────────────
# login step detection
# ─────────────────────────────────────────────────

class TestLoginStepDetection:
    def _make_step(self, url="", title="", inner_text="", semantic="", aria="") -> dict:
        return {
            "page": {"url": url, "title": title},
            "target": {"inner_text": inner_text, "aria_label": aria},
            "semantic": {"normalized_text": semantic},
        }

    def test_detects_password_field_step(self):
        step = self._make_step(inner_text="password")
        assert _is_login_step(step) is True

    def test_detects_sign_in_url(self):
        step = self._make_step(url="https://app.example.com/sign-in")
        assert _is_login_step(step) is True

    def test_detects_login_title(self):
        step = self._make_step(title="Log in to Render")
        assert _is_login_step(step) is True

    def test_neutral_step_not_detected(self):
        step = self._make_step(url="https://dashboard.render.com/services", title="Services")
        assert _is_login_step(step) is False

    def test_strip_login_steps_removes_login_events(self):
        events = [
            self._make_step(url="https://app.example.com/login", inner_text="email"),
            self._make_step(url="https://app.example.com/login", inner_text="password"),
            self._make_step(url="https://app.example.com/dashboard", title="Dashboard"),
            self._make_step(url="https://app.example.com/dashboard", inner_text="Create service"),
        ]
        clean = strip_login_steps(events)
        assert len(clean) == 2
        for e in clean:
            assert "dashboard" in e["page"]["url"]

    def test_strip_login_steps_no_login_returns_original(self):
        events = [
            self._make_step(url="https://dashboard.render.com/services", title="Services"),
            self._make_step(url="https://dashboard.render.com/services", inner_text="New service"),
        ]
        assert strip_login_steps(events) == events

    def test_strip_login_steps_empty_returns_empty(self):
        assert strip_login_steps([]) == []

    def test_strip_all_results_in_original_returned(self):
        events = [
            self._make_step(url="https://app.example.com/login", inner_text="password"),
        ]
        result = strip_login_steps(events)
        assert result == events


# ─────────────────────────────────────────────────
# plugin.json structure (integration-level)
# ─────────────────────────────────────────────────

class TestPluginConfigStructure:
    """Validates the structure that build_plugin would write to plugin.json."""

    def _make_config(
        self,
        name="Test Plugin",
        version="0.2.0",
        skills=None,
        protected_url="https://app.example.com/dashboard",
    ) -> dict:
        skills = skills or [{"slug": "do-thing", "path": "skills/do-thing"}]
        return {
            "slug": "test_plugin",
            "name": name,
            "version": version,
            "target_url": "https://app.example.com",
            "protected_url": protected_url,
            "skills": skills,
            "compatibility": {"conxa_runtime": ">=1.0.0"},
        }

    def test_required_fields_present(self):
        cfg = self._make_config()
        for field in ("slug", "name", "version", "target_url", "protected_url", "skills"):
            assert field in cfg, f"Missing field: {field}"

    def test_skills_are_objects_not_strings(self):
        cfg = self._make_config()
        for skill in cfg["skills"]:
            assert isinstance(skill, dict)
            assert "slug" in skill
            assert "path" in skill

    def test_version_semver_format(self):
        cfg = self._make_config(version="1.2.3")
        assert re.match(r"^\d+\.\d+\.\d+$", cfg["version"])


# ─────────────────────────────────────────────────
# saved Human Edit skill → plugin files
# ─────────────────────────────────────────────────

class TestSavedSkillJsonBuild:
    def test_preserves_human_edit_placeholders_and_removes_recorded_literal(self, tmp_path):
        saved_skill = {
            "meta": {"id": "skill_123", "title": "Delete Database"},
            "inputs": [{"id": "service_name", "label": "Service Name", "type": "text"}],
            "skills": [
                {
                    "name": "recorded",
                    "steps": [
                        {
                            "action": {"action": "navigate", "url": "https://dashboard.render.com/"},
                            "url_state": {
                                "before": {"url_pattern": "^https://dashboard\\.render\\.com/$"},
                                "after": {"url_pattern": "^https://dashboard\\.render\\.com/$"},
                            },
                        },
                        {
                            "action": "type",
                            "target": {"primary_selector": 'input[placeholder="Search"]'},
                            "value": "{{service_name}}",
                        },
                        {
                            "action": "click",
                            "target": {"primary_selector": "text={{service_name}}"},
                        },
                        {
                            "action": "type",
                            "target": {"primary_selector": 'input[name="sudoCommand"]'},
                            "value": "sudo delete database {{service_name}}",
                        },
                    ],
                }
            ],
        }

        _build_workflow_from_saved_skill(
            bundle_root=tmp_path,
            workflow_slug="delete_database",
            saved_skill=saved_skill,
        )

        skill_dir = tmp_path / "skills" / "delete_database"
        execution_raw = (skill_dir / "execution.json").read_text(encoding="utf-8")
        assert "{{service_name}}" in execution_raw
        assert "conxa-db" not in execution_raw

        execution = json.loads(execution_raw)
        assert execution[1]["value"] == "{{service_name}}"
        assert execution[2]["selector"] == "text={{service_name}}"
        assert execution[3]["value"] == "sudo delete database {{service_name}}"

        input_json = json.loads((skill_dir / "input.json").read_text(encoding="utf-8"))
        assert input_json["inputs"][0]["name"] == "service_name"

        recovery = json.loads((skill_dir / "recovery.json").read_text(encoding="utf-8"))
        assert [step["step_id"] for step in recovery["steps"]] == [2, 3, 4]
        assert recovery["steps"][1]["selector_context"]["primary"] == "text={{service_name}}"
        assert recovery["steps"][2]["selector_context"]["primary"] == 'input[name="sudoCommand"]'

    def test_saved_skill_recovery_repairs_hardcoded_search_result_click(self, tmp_path):
        saved_skill = {
            "meta": {"id": "skill_123", "title": "Delete Database"},
            "inputs": [{"id": "database_name", "label": "Database Name", "type": "text"}],
            "skills": [
                {
                    "steps": [
                        {
                            "action": {"action": "navigate", "url": "https://dashboard.render.com/"},
                        },
                        {
                            "action": "type",
                            "target": {"primary_selector": 'input[type="text"]'},
                            "value": "{{database_name}}",
                        },
                        {
                            "action": "click",
                            "intent": "click_conxa_db",
                            "target": {"primary_selector": 'text="conxa-db"'},
                            "recovery": {
                                "anchors": [
                                    {"element": "conxa-db", "relation": "target"},
                                ]
                            },
                        },
                        {
                            "action": "type",
                            "target": {"primary_selector": 'input[name="sudoCommand"]'},
                            "value": "sudo delete database {{database_name}}",
                        },
                        {
                            "action": "click",
                            "target": {"primary_selector": 'text="Delete Database"'},
                        },
                    ],
                }
            ],
        }

        _build_workflow_from_saved_skill(
            bundle_root=tmp_path,
            workflow_slug="delete_database",
            saved_skill=saved_skill,
        )

        skill_dir = tmp_path / "skills" / "delete_database"
        execution_raw = (skill_dir / "execution.json").read_text(encoding="utf-8")
        recovery_raw = (skill_dir / "recovery.json").read_text(encoding="utf-8")

        assert "{{database_name}}" in execution_raw
        assert "{{database_name}}" in recovery_raw
        assert "conxa-db" not in execution_raw
        assert "conxa-db" not in recovery_raw
        assert "recovery_metadata" not in recovery_raw
        assert "generated_by" not in recovery_raw
        assert '"mode"' not in recovery_raw
        assert "visual_metadata" not in recovery_raw

        execution = json.loads(execution_raw)
        assert execution[2]["selector"] == 'text="{{database_name}}"'
        assert execution[4]["selector"] == 'text="Delete Database"'

        recovery = json.loads(recovery_raw)
        search_result_entry = next(step for step in recovery["steps"] if step["step_id"] == 3)
        assert search_result_entry["target"]["text"] == "{{database_name}}"
        assert search_result_entry["intent"] == "click_database_name"
        assert search_result_entry["selector_context"]["primary"] == 'text="{{database_name}}"'

    def test_saved_skill_recovery_is_built_from_saved_human_edit_fields(self, tmp_path):
        saved_skill = {
            "meta": {"id": "skill_123", "title": "Delete Database"},
            "inputs": [{"id": "database_name", "label": "Database Name", "type": "text"}],
            "skills": [
                {
                    "steps": [
                        {
                            "action": "click",
                            "intent": "open_database_from_saved_json",
                            "target": {
                                "primary_selector": 'text="{{database_name}}"',
                                "fallback_selectors": ['[role="link"][name="{{database_name}}"]'],
                                "role": "link",
                            },
                            "recovery": {
                                "anchors": [
                                    {"element": "{{database_name}}", "relation": "target"},
                                    {"element": "Databases", "relation": "near"},
                                ],
                                "strategies": ["semantic match", "visual match"],
                            },
                        },
                    ],
                }
            ],
        }

        _build_workflow_from_saved_skill(
            bundle_root=tmp_path,
            workflow_slug="delete_database",
            saved_skill=saved_skill,
        )

        recovery = json.loads((tmp_path / "skills" / "delete_database" / "recovery.json").read_text(encoding="utf-8"))
        assert recovery["steps"] == [
            {
                "step_id": 1,
                "intent": "open_database_from_saved_json",
                "target": {"text": "{{database_name}}", "role": "link"},
                "anchors": [
                    {"text": "{{database_name}}", "priority": 2},
                ],
                "fallback": {"text_variants": ["{{database_name}}"], "role": "link"},
                "selector_context": {
                    "primary": 'text="{{database_name}}"',
                    "alternatives": ['[role="link"][name="{{database_name}}"]'],
                },
            }
        ]

    def test_saved_skill_recovery_writes_visual_refs_from_saved_step_screenshots(self, tmp_path, monkeypatch):
        import app.services.plugin_builder as plugin_builder

        data_dir = tmp_path / "data"
        image_dir = data_dir / "sessions" / "sess_visual" / "images"
        image_dir.mkdir(parents=True)
        source_image = image_dir / "click.jpg"
        Image.new("RGB", (120, 80), "white").save(source_image)
        monkeypatch.setattr(plugin_builder, "resolve_skill_asset", lambda rel: data_dir / rel)

        saved_skill = {
            "meta": {
                "id": "skill_123",
                "title": "Delete Database",
                "source_session_id": "sess_visual",
            },
            "inputs": [],
            "skills": [
                {
                    "steps": [
                        {
                            "action": "click",
                            "target": {"primary_selector": 'text="Delete Database"'},
                            "signals": {
                                "visual": {
                                    "full_screenshot": "images/click.jpg",
                                    "bbox": {"x": 10, "y": 12, "w": 40, "h": 20},
                                    "viewport": "120x80",
                                }
                            },
                        },
                    ],
                }
            ],
        }

        _build_workflow_from_saved_skill(
            bundle_root=tmp_path,
            workflow_slug="delete_database",
            saved_skill=saved_skill,
        )

        skill_dir = tmp_path / "skills" / "delete_database"
        visual_path = skill_dir / "visuals" / "Image_1.jpg"
        assert visual_path.is_file()
        assert visual_path.read_bytes() != source_image.read_bytes()

        recovery = json.loads((skill_dir / "recovery.json").read_text(encoding="utf-8"))
        assert recovery["steps"][0]["visual_ref"] == "visuals/Image_1.jpg"

    def test_saved_skill_url_state_keeps_only_runtime_patterns(self, tmp_path):
        saved_skill = {
            "meta": {"id": "skill_123", "title": "Delete Database"},
            "inputs": [],
            "skills": [
                {
                    "steps": [
                        {
                            "action": "click",
                            "target": {"primary_selector": 'text="Delete Database"'},
                            "url_state": {
                                "before": {
                                    "url": "https://dashboard.render.com/d/dpg-123",
                                    "url_pattern": "^https://dashboard\\.render\\.com/d/[^/]+$",
                                    "title_includes": "conxa-db ・ Database ・ Render Dashboard",
                                },
                                "after": {
                                    "url": "https://dashboard.render.com/",
                                    "url_pattern": "^https://dashboard\\.render\\.com/$",
                                    "title_includes": "conxa-db ・ Database ・ Render Dashboard",
                                },
                                "edited_by_user": True,
                            },
                        },
                    ],
                }
            ],
        }

        _build_workflow_from_saved_skill(
            bundle_root=tmp_path,
            workflow_slug="delete_database",
            saved_skill=saved_skill,
        )

        execution_raw = (tmp_path / "skills" / "delete_database" / "execution.json").read_text(encoding="utf-8")
        assert "title_includes" not in execution_raw
        assert "edited_by_user" not in execution_raw
        assert '"url":' not in execution_raw

        execution = json.loads(execution_raw)
        assert execution[0]["url_state"] == {
            "before": {"url_pattern": "^https://dashboard\\.render\\.com/d/[^/]+$"},
            "after": {"url_pattern": "^https://dashboard\\.render\\.com/$"},
        }

    def test_normalizes_human_edit_input_id_to_runtime_name(self):
        inputs = _normalize_saved_skill_inputs(
            [{"id": "service_name", "label": "Service Name", "type": "text"}]
        )

        assert inputs == [
            {
                "name": "service_name",
                "type": "string",
                "description": "Service Name",
            }
        ]

    def test_build_plugin_prefers_saved_skill_over_original_recording(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        import app.services.plugin_builder as plugin_builder

        plugin = SimpleNamespace(
            id="plugin123456",
            name="Render",
            target_url="https://dashboard.render.com",
            protected_url="https://dashboard.render.com/",
            protected_url_marker_text="",
            auth=None,
            workflows=[
                SimpleNamespace(
                    id="wf1",
                    slug="delete_database",
                    name="Delete Database",
                    session_id="workflow-session",
                    skill_id="skill_saved",
                )
            ],
        )
        saved_skill = {
            "meta": {"id": "skill_saved", "title": "Delete Database"},
            "inputs": [{"id": "service_name", "label": "Service Name", "type": "text"}],
            "skills": [
                {
                    "steps": [
                        {"action": {"action": "navigate", "url": "https://dashboard.render.com/"}},
                        {
                            "action": "type",
                            "target": {"primary_selector": 'input[placeholder="Search"]'},
                            "value": "{{service_name}}",
                        },
                    ]
                }
            ],
        }
        sessions_read: list[str] = []

        def fake_read_session_events(session_id):
            sessions_read.append(session_id)
            return []

        monkeypatch.setattr(plugin_builder, "get_plugin", lambda _plugin_id: plugin)
        monkeypatch.setattr(plugin_builder, "read_skill", lambda skill_id: saved_skill if skill_id == "skill_saved" else None)
        monkeypatch.setattr(plugin_builder, "read_session_events", fake_read_session_events)
        monkeypatch.setattr(plugin_builder, "_bundle_root", lambda _bundle_slug: tmp_path)
        monkeypatch.setattr(plugin_builder, "set_build", lambda *args, **kwargs: None)

        build_plugin("plugin123456")

        execution_raw = (tmp_path / "skills" / "delete_database" / "execution.json").read_text(encoding="utf-8")
        assert "{{service_name}}" in execution_raw
        assert "conxa-db" not in execution_raw
        assert sessions_read == []  # saved skill used — no session events needed

        # Data-only artifact: marketplace shim and runtime/ never ship.
        assert not (tmp_path / ".claude-plugin").exists()
        assert not (tmp_path / "runtime").exists()

        # v2 manifest fields written by build_plugin
        manifest = json.loads((tmp_path / "plugin.json").read_text(encoding="utf-8"))
        assert manifest["package_format"] == 2
        assert manifest["id"]  # falls back to bundle slug when package_id unset
        assert manifest["visibility"] == "private"
        assert manifest["tags"] == []
        assert manifest["auth_requirements"] == {"kind": "cookie", "manual_login": True}
        assert manifest["runtime_min_version"] == "1.0.0"

        # Per-plugin Claude.md gets the new npx install snippet.
        claude_md = (tmp_path / "Claude.md").read_text(encoding="utf-8")
        assert "npx -y conxa install" in claude_md
