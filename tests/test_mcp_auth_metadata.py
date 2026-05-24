from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def _run_node(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["CONXA_DIR"] = str(tmp_path / "install")
    env["CONXA_DATA_DIR"] = str(tmp_path / "data")
    env["HOME"] = str(tmp_path / "home")
    env["USERPROFILE"] = str(tmp_path / "home")
    env["NODE_PATH"] = str(repo / "runtime" / "node_modules")
    return subprocess.run(
        [node, "-e", textwrap.dedent(script)],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )


def test_root_runtime_auth_metadata_helpers(tmp_path: Path) -> None:
    result = _run_node(
        """
        const assert = require("assert");
        const browser = require("./runtime/browser.js");

        assert.strictEqual(
          browser._resolveProtectedUrl("acme", { protected_url: "https://pack.example.com/app" }),
          "https://pack.example.com/app"
        );

        browser._writeAuthMeta("acme", { protected_url: "https://meta.example.com/app?team=1#leads" });
        assert.strictEqual(
          browser._resolveProtectedUrl("acme", { protected_url: "https://pack.example.com/app" }),
          "https://meta.example.com/app?team=1#leads"
        );
        assert.strictEqual(browser._rejectReasonForProtectedUrl("https://meta.example.com/app"), "");
        assert(browser._rejectReasonForProtectedUrl("about:blank").includes("No authenticated page URL"));
        assert(browser._rejectReasonForProtectedUrl("https://meta.example.com/login").includes("login/auth page"));
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_template_runtime_auth_metadata_helpers_and_install_without_protected_url(tmp_path: Path) -> None:
    result = _run_node(
        """
        const assert = require("assert");
        const fs = require("fs");
        const path = require("path");
        const browser = require("./app/storage/plugin_templates/runtime/browser.js");
        const cli = require("./app/storage/plugin_templates/runtime/cli.js");

        browser._writeAuthMeta("acme", { protected_url: "https://meta.example.com/dashboard" });
        assert.strictEqual(
          browser._resolveProtectedUrl("acme", { protected_url: "https://pack.example.com/app" }),
          "https://meta.example.com/dashboard"
        );
        assert.strictEqual(browser._rejectReasonForProtectedUrl("https://meta.example.com/dashboard"), "");
        assert(browser._rejectReasonForProtectedUrl("https://meta.example.com/oauth/callback").includes("login/auth page"));

        const pluginDir = path.join(process.env.CONXA_DATA_DIR, "plugin-src");
        fs.mkdirSync(path.join(pluginDir, "skills", "hello"), { recursive: true });
        fs.writeFileSync(path.join(pluginDir, "plugin.json"), JSON.stringify({
          slug: "no-protected",
          name: "No Protected",
          target_url: "https://example.com/login",
          skills: [{ slug: "hello", path: "skills/hello" }]
        }, null, 2));
        const entry = cli._installFromLocalDir(pluginDir);
        assert.strictEqual(entry.protected_url, "");
        assert(fs.existsSync(path.join(process.env.HOME, ".conxa", "plugins", "no-protected", "plugin.json")));
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
