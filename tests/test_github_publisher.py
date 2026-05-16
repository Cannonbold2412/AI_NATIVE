"""Unit tests for github_publisher — semver, version collision, metadata update."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.github_publisher import (  # noqa: E402
    NoBuildError,
    VersionAlreadyPublished,
    bump_version,
    next_versions,
)


# ─────────────────────────────────────────────────────────────────────────────
# Semver helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "current,bump,expected",
    [
        ("1.2.3", "patch", "1.2.4"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
        ("0.0.0", "patch", "0.0.1"),
        ("v1.0.0", "patch", "1.0.1"),  # leading v stripped
    ],
)
def test_bump_version(current, bump, expected):
    assert bump_version(current, bump) == expected


def test_manual_version_overrides_bump():
    assert bump_version("1.0.0", "patch", manual="3.0.0") == "3.0.0"


def test_manual_version_strips_v():
    assert bump_version("1.0.0", "patch", manual="v2.0.0") == "2.0.0"


def test_next_versions_shape():
    nv = next_versions("1.2.3")
    assert nv == {"patch": "1.2.4", "minor": "1.3.0", "major": "2.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
# publish() guards
# ─────────────────────────────────────────────────────────────────────────────


def test_publish_raises_on_missing_plugin():
    from app.services.github_publisher import publish

    with patch("app.services.github_publisher.get_plugin", return_value=None):
        with pytest.raises(ValueError, match="not found"):
            publish("nonexistent", "local")


def test_publish_raises_no_build_error():
    from app.services.github_publisher import publish
    from app.models.plugin import Plugin

    plugin = Plugin(
        id="p1",
        slug="test-plugin",
        name="Test",
        target_url="https://example.com",
        protected_url="https://example.com/dashboard",
        build=None,
    )
    with patch("app.services.github_publisher.get_plugin", return_value=plugin):
        with pytest.raises(NoBuildError):
            publish("p1", "local")


def test_publish_raises_permission_error_when_no_token():
    from app.services.github_publisher import publish
    from app.models.plugin import Plugin, PluginBuild
    import time

    plugin = Plugin(
        id="p1",
        slug="test-plugin",
        name="Test",
        target_url="https://example.com",
        protected_url="https://example.com/dashboard",
        build=PluginBuild(
            last_built_at=time.time(),
            output_path="/some/path",
            version="0.1.0",
        ),
    )
    with patch("app.services.github_publisher.get_plugin", return_value=plugin):
        with patch("app.services.github_publisher.get_token", return_value=None):
            with pytest.raises(PermissionError):
                publish("p1", "local")


def test_publish_raises_version_already_published():
    """If the version tag already exists on the remote, VersionAlreadyPublished is raised."""
    from app.services.github_publisher import publish
    from app.models.plugin import Plugin, PluginBuild
    import time

    tmpdir = tempfile.mkdtemp()
    try:
        # Minimal fake bundle directory
        Path(tmpdir).joinpath("plugin.json").write_text(
            json.dumps({"version": "0.1.0", "metadata": {}}), encoding="utf-8"
        )

        plugin = Plugin(
            id="p1",
            slug="test-plugin",
            name="Test",
            target_url="https://example.com",
            protected_url="https://example.com/dashboard",
            build=PluginBuild(
                last_built_at=time.time(),
                output_path=tmpdir,
                version="0.1.0",
            ),
            repository_url="https://github.com/user/test-plugin.git",
            last_published_version="0.1.0",
        )

        with patch("app.services.github_publisher.get_plugin", return_value=plugin):
            with patch("app.services.github_publisher.get_token", return_value="fake-token"):
                with patch("app.services.github_publisher._tag_exists_on_remote", return_value=True):
                    with pytest.raises(VersionAlreadyPublished, match="v0.1.1"):
                        publish("p1", "local", version_bump="patch")
    finally:
        shutil.rmtree(tmpdir)


def test_auth_json_not_in_bundle():
    """Bundle's .gitignore template must exclude auth/auth.json to prevent credential leaks."""
    from pathlib import Path
    gitignore_tmpl = Path(__file__).parent.parent / "app" / "storage" / "plugin_templates" / "plugin" / ".gitignore"
    gitignore_content = gitignore_tmpl.read_text(encoding="utf-8")
    assert "auth/auth.json" in gitignore_content
