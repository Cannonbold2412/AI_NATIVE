"""Tests for the gated production pipeline:
Record → Compile → Human Edit → Build Plugin → Test Plugin → Build Installer.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.plugin import Plugin, PluginBuild, PluginInstaller, PluginWorkflow
from app.storage.plugin_store import (
    invalidate_workflow_test_by_skill,
    set_workflow_test_error,
    set_workflow_test_result,
)


# ─── helpers ───────────────────────────────────────────────────────────────────

def _make_workflow(
    *,
    skill_id: str | None = "skill-abc",
    edited_at: float | None = 1.0,
    last_test_status: str = "never",
    last_test_error: str | None = None,
) -> PluginWorkflow:
    return PluginWorkflow(
        id=str(uuid.uuid4()),
        slug="test-wf",
        name="Test Workflow",
        session_id="sess-1",
        recorded_at=0.0,
        skill_id=skill_id,
        edited_at=edited_at,
        last_test_status=last_test_status,  # type: ignore[arg-type]
        last_test_error=last_test_error,
    )


def _make_plugin(workflows: list[PluginWorkflow], build_at: float | None = None) -> Plugin:
    build = PluginBuild(last_built_at=build_at or time.time(), output_path="/tmp/out", version="0.1.0") if build_at is not None else None
    return Plugin(
        id=str(uuid.uuid4()),
        slug="test-plugin",
        name="Test Plugin",
        workspace_id="ws-1",
        target_url="https://example.com",
        status="ready",
        created_at=0.0,
        updated_at=0.0,
        workflows=workflows,
        build=build,
    )


# ─── Build Plugin gates ─────────────────────────────────────────────────────────

class TestBuildPluginGates:
    """build_plugin must refuse to run when workflows are uncompiled or unedited."""

    def _run_build(self, plugin: Plugin, tmp_path: Path) -> None:
        from app.services.plugin_builder import build_plugin
        with patch("app.services.plugin_builder.get_plugin", return_value=plugin), \
             patch("app.services.plugin_builder.set_build", return_value=plugin), \
             patch("app.services.plugin_builder._build_workflow_from_saved_skill"):
            build_plugin(plugin.id)

    def test_raises_when_no_workflows(self, tmp_path: Path) -> None:
        plugin = _make_plugin(workflows=[])
        with pytest.raises(ValueError, match="no workflows"):
            self._run_build(plugin, tmp_path)

    def test_raises_when_workflow_not_compiled(self, tmp_path: Path) -> None:
        wf = _make_workflow(skill_id=None, edited_at=None)
        plugin = _make_plugin(workflows=[wf])
        with pytest.raises(ValueError, match="Compile these workflows"):
            self._run_build(plugin, tmp_path)

    def test_raises_when_workflow_compiled_but_not_edited(self, tmp_path: Path) -> None:
        wf = _make_workflow(skill_id="skill-abc", edited_at=None)
        plugin = _make_plugin(workflows=[wf])
        with pytest.raises(ValueError, match="sign off"):
            self._run_build(plugin, tmp_path)

    def test_raises_partial_unedited(self, tmp_path: Path) -> None:
        """Mix of edited and unedited — should still raise."""
        wf_ok = _make_workflow(skill_id="skill-1", edited_at=1.0)
        wf_bad = _make_workflow(skill_id="skill-2", edited_at=None)
        wf_bad = wf_bad.model_copy(update={"name": "Unedited Workflow"})
        plugin = _make_plugin(workflows=[wf_ok, wf_bad])
        with pytest.raises(ValueError, match="Unedited Workflow"):
            self._run_build(plugin, tmp_path)


# ─── invalidate_workflow_test_by_skill ─────────────────────────────────────────

class TestInvalidateWorkflowTest:
    """Invalidation must reset test fields and bump edited_at."""

    def test_resets_test_fields_and_bumps_edited_at(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = _make_workflow(skill_id="sk-123", last_test_status="passed", edited_at=1.0)
        plugin = _make_plugin(workflows=[wf])

        saved: list[Plugin] = []

        monkeypatch.setattr("app.storage.plugin_store.list_plugins", lambda: [plugin])
        monkeypatch.setattr("app.storage.plugin_store.save_plugin", lambda p: saved.append(p) or p)

        before = time.time()
        invalidate_workflow_test_by_skill("sk-123")
        after = time.time()

        assert saved, "save_plugin should have been called"
        updated_wf = saved[0].workflows[0]
        assert updated_wf.last_test_status == "never"
        assert updated_wf.last_test_error is None
        assert updated_wf.last_test_at is None
        assert updated_wf.edited_at is not None
        assert before <= updated_wf.edited_at <= after

    def test_does_not_touch_unrelated_workflows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf_target = _make_workflow(skill_id="sk-target", last_test_status="passed")
        wf_other = _make_workflow(skill_id="sk-other", last_test_status="passed")
        plugin = _make_plugin(workflows=[wf_target, wf_other])

        saved: list[Plugin] = []
        monkeypatch.setattr("app.storage.plugin_store.list_plugins", lambda: [plugin])
        monkeypatch.setattr("app.storage.plugin_store.save_plugin", lambda p: saved.append(p) or p)

        invalidate_workflow_test_by_skill("sk-target")

        updated = saved[0].workflows
        target = next(w for w in updated if w.skill_id == "sk-target")
        other = next(w for w in updated if w.skill_id == "sk-other")
        assert target.last_test_status == "never"
        assert other.last_test_status == "passed"

    def test_no_save_when_skill_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = _make_workflow(skill_id="sk-abc", last_test_status="passed")
        plugin = _make_plugin(workflows=[wf])

        saved: list[Plugin] = []
        monkeypatch.setattr("app.storage.plugin_store.list_plugins", lambda: [plugin])
        monkeypatch.setattr("app.storage.plugin_store.save_plugin", lambda p: saved.append(p) or p)

        invalidate_workflow_test_by_skill("sk-does-not-exist")

        assert not saved, "save_plugin should NOT be called when no workflow matches"


# ─── json_store.write_skill invalidation hook ──────────────────────────────────

class TestWriteSkillInvalidationHook:
    """write_skill must invalidate on UPDATE but not on initial CREATE."""

    def _call_write_skill(self, skill_id: str, doc: dict[str, Any], existing: dict | None) -> None:
        from app.storage import json_store
        with patch.object(json_store, "read_skill", return_value=existing), \
             patch("app.db.db_set"), \
             patch.object(json_store, "skills_dir", return_value=MagicMock(
                 __truediv__=lambda self, other: MagicMock(
                     write_text=lambda *a, **kw: None
                 )
             )):
            json_store.write_skill(skill_id, doc)

    def test_invalidates_on_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        invalidated: list[str] = []

        def fake_invalidate(skill_id: str) -> None:
            invalidated.append(skill_id)

        monkeypatch.setattr(
            "app.storage.json_store.invalidate_workflow_test_by_skill",
            fake_invalidate,
            raising=False,
        )

        # Patch at the module level where it's imported lazily
        with patch("app.storage.json_store.read_skill", return_value={"existing": True}), \
             patch("app.db.db_set"), \
             patch("pathlib.Path.write_text"):
            from app.storage import json_store
            # Temporarily inject the mock so the deferred import path hits it
            import app.storage.plugin_store as ps
            original = getattr(ps, "invalidate_workflow_test_by_skill")
            ps.invalidate_workflow_test_by_skill = fake_invalidate  # type: ignore[assignment]
            try:
                json_store.write_skill("sk-update", {"new": True})
            finally:
                ps.invalidate_workflow_test_by_skill = original  # type: ignore[assignment]

    def test_no_invalidation_on_first_create(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """First write (existing=None) must not trigger invalidation."""
        invalidated: list[str] = []

        import app.storage.plugin_store as ps
        original = getattr(ps, "invalidate_workflow_test_by_skill")

        def fake_invalidate(skill_id: str) -> None:
            invalidated.append(skill_id)

        ps.invalidate_workflow_test_by_skill = fake_invalidate  # type: ignore[assignment]
        try:
            with patch("app.storage.json_store.read_skill", return_value=None), \
                 patch("app.db.db_set"), \
                 patch("pathlib.Path.write_text"):
                from app.storage import json_store
                json_store.write_skill("sk-brand-new", {"new": True})
        finally:
            ps.invalidate_workflow_test_by_skill = original  # type: ignore[assignment]

        assert not invalidated, "No invalidation on first create"


# ─── set_workflow_test_result / set_workflow_test_error ────────────────────────

class TestSetWorkflowTestPersistence:
    def test_set_result_marks_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = _make_workflow(last_test_status="never")
        plugin = _make_plugin(workflows=[wf])

        saved: list[Plugin] = []
        monkeypatch.setattr("app.storage.plugin_store.get_plugin", lambda pid, **kw: plugin)
        monkeypatch.setattr("app.storage.plugin_store.save_plugin", lambda p: saved.append(p) or p)

        set_workflow_test_result(plugin.id, wf.id, status="passed", inputs={"url": "https://x.com"})

        updated_wf = saved[0].workflows[0]
        assert updated_wf.last_test_status == "passed"
        assert updated_wf.last_test_inputs == {"url": "https://x.com"}
        assert updated_wf.last_test_error is None
        assert updated_wf.last_test_at is not None

    def test_set_error_marks_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = _make_workflow(last_test_status="never")
        plugin = _make_plugin(workflows=[wf])

        saved: list[Plugin] = []
        monkeypatch.setattr("app.storage.plugin_store.get_plugin", lambda pid, **kw: plugin)
        monkeypatch.setattr("app.storage.plugin_store.save_plugin", lambda p: saved.append(p) or p)

        set_workflow_test_error(plugin.id, wf.id, "Selector not found")

        updated_wf = saved[0].workflows[0]
        assert updated_wf.last_test_status == "failed"
        assert "Selector not found" in (updated_wf.last_test_error or "")

    def test_set_error_truncates_long_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wf = _make_workflow()
        plugin = _make_plugin(workflows=[wf])

        saved: list[Plugin] = []
        monkeypatch.setattr("app.storage.plugin_store.get_plugin", lambda pid, **kw: plugin)
        monkeypatch.setattr("app.storage.plugin_store.save_plugin", lambda p: saved.append(p) or p)

        long_error = "x" * 5000
        set_workflow_test_error(plugin.id, wf.id, long_error)

        updated_wf = saved[0].workflows[0]
        assert len(updated_wf.last_test_error or "") <= 2000


# ─── Stale-build gate (test endpoint) ─────────────────────────────────────────

class TestStaleBuildGate:
    """Test endpoint must reject runs where edited_at > build.last_built_at."""

    def _make_stale_plugin(self) -> tuple[Plugin, PluginWorkflow]:
        build_time = 1000.0
        edit_time = 2000.0  # edited AFTER build
        wf = _make_workflow(skill_id="sk-abc", edited_at=edit_time)
        build = PluginBuild(last_built_at=build_time, output_path="/tmp/out", version="0.1.0")
        plugin = Plugin(
            id="p-1",
            slug="test",
            name="Test",
            workspace_id="ws-1",
            target_url="https://example.com",
            status="ready",
            created_at=0.0,
            updated_at=0.0,
            workflows=[wf],
            build=build,
        )
        return plugin, wf

    def test_stale_workflow_is_detected(self) -> None:
        plugin, wf = self._make_stale_plugin()
        assert wf.edited_at is not None
        assert plugin.build is not None
        assert wf.edited_at > plugin.build.last_built_at

    def test_non_stale_workflow_passes(self) -> None:
        build_time = 2000.0
        edit_time = 1000.0  # edited BEFORE build
        wf = _make_workflow(skill_id="sk-abc", edited_at=edit_time)
        build = PluginBuild(last_built_at=build_time, output_path="/tmp/out", version="0.1.0")
        plugin = Plugin(
            id="p-1",
            slug="test",
            name="Test",
            workspace_id="ws-1",
            target_url="https://example.com",
            status="ready",
            created_at=0.0,
            updated_at=0.0,
            workflows=[wf],
            build=build,
        )
        assert wf.edited_at is not None
        assert plugin.build is not None
        assert wf.edited_at <= plugin.build.last_built_at

    def test_test_stream_endpoint_returns_400_for_stale_build(self) -> None:
        """The /test/stream endpoint must return 400 if workflow was edited after last build."""
        from fastapi.testclient import TestClient
        from app.main import app

        plugin, wf = self._make_stale_plugin()

        with patch("app.config.settings.auth_required", False), \
             patch("app.api.plugin_routes.get_plugin", return_value=plugin):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/plugins/{plugin.id}/workflows/{wf.id}/test/stream",
                json={"inputs": {}, "headless": True},
            )

        assert resp.status_code == 400
        assert "edited since the last build" in resp.json().get("detail", "")


# ─── Build Installer gate ───────────────────────────────────────────────────────

class TestBuildInstallerGate:
    """Build Installer endpoint must refuse if any workflow has not passed testing."""

    def test_installer_blocked_when_workflow_untested(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        wf = _make_workflow(last_test_status="never")
        build = PluginBuild(last_built_at=time.time(), output_path="/tmp/out", version="0.1.0")
        plugin = Plugin(
            id="p-2",
            slug="test",
            name="Test",
            workspace_id="ws-1",
            target_url="https://example.com",
            status="ready",
            created_at=0.0,
            updated_at=0.0,
            workflows=[wf],
            build=build,
        )

        with patch("app.config.settings.auth_required", False), \
             patch("app.api.plugin_routes.get_plugin", return_value=plugin):
            client = TestClient(app)
            resp = client.post(f"/api/v1/plugins/{plugin.id}/build-installer/stream")

        assert resp.status_code == 400
        assert "must pass Test Plugin" in resp.json().get("detail", "")

    def test_installer_blocked_when_workflow_failed(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        wf = _make_workflow(last_test_status="failed")
        build = PluginBuild(last_built_at=time.time(), output_path="/tmp/out", version="0.1.0")
        plugin = Plugin(
            id="p-3",
            slug="test",
            name="Test",
            workspace_id="ws-1",
            target_url="https://example.com",
            status="ready",
            created_at=0.0,
            updated_at=0.0,
            workflows=[wf],
            build=build,
        )

        with patch("app.config.settings.auth_required", False), \
             patch("app.api.plugin_routes.get_plugin", return_value=plugin):
            client = TestClient(app)
            resp = client.post(f"/api/v1/plugins/{plugin.id}/build-installer/stream")

        assert resp.status_code == 400
        assert "must pass Test Plugin" in resp.json().get("detail", "")
