"""Verify that plugin reads are scoped to workspace_id."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from conxa_core.models.plugin import Plugin
from conxa_core.storage import plugin_store


@pytest.fixture()
def tmp_plugins_dir(tmp_path: Path):
    with patch.object(plugin_store, "_plugins_dir", return_value=tmp_path):
        yield tmp_path


def _make_plugin(plugins_dir: Path, plugin_id: str, workspace_id: str) -> None:
    import json, time
    data = {
        "id": plugin_id,
        "slug": f"plugin-{plugin_id[:8]}",
        "name": "Test Plugin",
        "workspace_id": workspace_id,
        "target_url": "https://example.com",
        "protected_url": "https://example.com/app",
        "status": "needs_auth",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    (plugins_dir / f"{plugin_id}.json").write_text(json.dumps(data), encoding="utf-8")


def test_list_plugins_scoped(tmp_plugins_dir):
    _make_plugin(tmp_plugins_dir, "aaa-aaa-aaa-aaa1", "org_A")
    _make_plugin(tmp_plugins_dir, "bbb-bbb-bbb-bbb2", "org_B")

    plugins_a = plugin_store.list_plugins(workspace_id="org_A")
    plugins_b = plugin_store.list_plugins(workspace_id="org_B")

    assert len(plugins_a) == 1
    assert plugins_a[0].workspace_id == "org_A"
    assert len(plugins_b) == 1
    assert plugins_b[0].workspace_id == "org_B"


def test_get_plugin_cross_tenant_returns_none(tmp_plugins_dir):
    _make_plugin(tmp_plugins_dir, "aaa-aaa-aaa-aaa1", "org_A")

    result = plugin_store.get_plugin("aaa-aaa-aaa-aaa1", workspace_id="org_B")
    assert result is None


def test_get_plugin_correct_tenant(tmp_plugins_dir):
    _make_plugin(tmp_plugins_dir, "aaa-aaa-aaa-aaa1", "org_A")

    result = plugin_store.get_plugin("aaa-aaa-aaa-aaa1", workspace_id="org_A")
    assert result is not None
    assert result.id == "aaa-aaa-aaa-aaa1"


def test_list_plugins_no_filter_returns_all(tmp_plugins_dir):
    _make_plugin(tmp_plugins_dir, "aaa-aaa-aaa-aaa1", "org_A")
    _make_plugin(tmp_plugins_dir, "bbb-bbb-bbb-bbb2", "org_B")

    all_plugins = plugin_store.list_plugins()
    assert len(all_plugins) == 2
