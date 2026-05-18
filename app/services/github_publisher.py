"""Publish a built plugin bundle to GitHub.

Given a plugin with an existing build output, this module:
 1. Computes the next semver version.
 2. Creates a GitHub repo (first-time) or clones the existing one.
 3. Copies the bundle into a tempdir, commits, tags, and pushes.
 4. Updates the Plugin record with repo / version / commit metadata.

All git operations happen in a TemporaryDirectory — the build output on disk
is never modified by git.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from app.integrations.github_oauth import get_token
from app.storage.plugin_store import get_plugin, update_publish_metadata

# Per-plugin lock to prevent concurrent publishes of the same plugin.
_publish_locks: dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()


def _get_lock(plugin_id: str) -> threading.Lock:
    with _locks_mutex:
        if plugin_id not in _publish_locks:
            _publish_locks[plugin_id] = threading.Lock()
        return _publish_locks[plugin_id]


# ─────────────────────────────────────────────────────────────────────────────
# Semver helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_version(v: str) -> tuple[int, int, int]:
    """Parse 'major.minor.patch' → (major, minor, patch). Tolerates leading 'v'."""
    clean = v.lstrip("v")
    parts = clean.split(".")
    try:
        return int(parts[0]), int(parts[1] if len(parts) > 1 else 0), int(parts[2] if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        return 0, 1, 0


def bump_version(
    current: str,
    bump: Literal["patch", "minor", "major"] | None = "patch",
    manual: str | None = None,
) -> str:
    if manual:
        return manual.lstrip("v")
    major, minor, patch = _parse_version(current)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def next_versions(current: str) -> dict[str, str]:
    return {
        "patch": bump_version(current, "patch"),
        "minor": bump_version(current, "minor"),
        "major": bump_version(current, "major"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Git helpers
# ─────────────────────────────────────────────────────────────────────────────


def _run_git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        detail = stderr or stdout or "(no output)"
        raise RuntimeError(f"git {args[0]} failed (exit {e.returncode}): {detail}") from None


def _tag_exists_on_remote(remote_url: str, tag: str, token: str) -> bool:
    """Check if a tag already exists on the remote without cloning."""
    result = _run_git(
        ["ls-remote", "--tags", _inject_token(remote_url, token), f"refs/tags/{tag}"],
        cwd=str(Path(tempfile.gettempdir())),
        check=False,
    )
    return tag in result.stdout


def _inject_token(url: str, token: str) -> str:
    """Inject OAuth token into a github.com HTTPS URL."""
    return url.replace("https://", f"https://x-access-token:{token}@", 1)


# ─────────────────────────────────────────────────────────────────────────────
# GitHub API helpers
# ─────────────────────────────────────────────────────────────────────────────


def _gh(method: str, path: str, token: str, **kwargs) -> httpx.Response:
    resp = httpx.request(
        method,
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=20,
        **kwargs,
    )
    return resp


def _create_github_repo(token: str, name: str, private: bool, description: str) -> dict:
    resp = _gh("POST", "/user/repos", token, json={
        "name": name,
        "private": private,
        "description": description,
        "auto_init": False,
    })
    if resp.status_code == 422:
        raise ValueError(f"Repo name '{name}' already exists on GitHub or is invalid.")
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PublishResult:
    repo_url: str
    version: str
    commit_sha: str
    install_snippet: str


class VersionAlreadyPublished(Exception):
    pass


class NoBuildError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Main publish function
# ─────────────────────────────────────────────────────────────────────────────


def publish(
    plugin_id: str,
    workspace_id: str,
    *,
    version_bump: Literal["patch", "minor", "major"] | None = "patch",
    manual_version: str | None = None,
    changelog: str = "",
    create_repo: bool = False,
    repo_name: str | None = None,
    repo_url: str | None = None,
    private: bool = True,
) -> PublishResult:
    lock = _get_lock(plugin_id)
    if not lock.acquire(blocking=False):
        raise RuntimeError("A publish is already in progress for this plugin.")
    try:
        return _publish_locked(
            plugin_id,
            workspace_id,
            version_bump=version_bump,
            manual_version=manual_version,
            changelog=changelog,
            create_repo=create_repo,
            repo_name=repo_name,
            repo_url=repo_url,
            private=private,
        )
    finally:
        lock.release()


def _validate_public_artifact(repo_dir: Path) -> None:
    """Raise ValueError if the staging dir contains files that must never be published."""
    auth_json = repo_dir / "auth" / "auth.json"
    if auth_json.exists():
        raise ValueError("Public artifact contains auth/auth.json — credentials must not be published.")
    node_modules = list(repo_dir.rglob("node_modules"))
    if node_modules:
        raise ValueError(f"Public artifact contains node_modules/ at {node_modules[0].relative_to(repo_dir)}")
    runtime_dir = repo_dir / "runtime"
    if runtime_dir.exists():
        raise ValueError("Public artifact contains runtime/ — Conxa runtime internals must not be published.")
    # Shared-runtime migration: published plugins are data-only. The Claude Code
    # marketplace shim (.claude-plugin/) and bootstrap.js are gone — installs go
    # through `npx -y conxa install <plugin_id>`.
    claude_plugin_dir = repo_dir / ".claude-plugin"
    if claude_plugin_dir.exists():
        raise ValueError("Public artifact contains .claude-plugin/ — marketplace shim is no longer supported.")
    bootstrap_js = repo_dir / "bootstrap.js"
    if bootstrap_js.exists():
        raise ValueError("Public artifact contains bootstrap.js — marketplace shim is no longer supported.")


def _publish_locked(
    plugin_id: str,
    workspace_id: str,
    *,
    version_bump,
    manual_version,
    changelog,
    create_repo,
    repo_name,
    repo_url,
    private,
) -> PublishResult:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"Plugin '{plugin_id}' not found.")
    if plugin.build is None:
        raise NoBuildError("Plugin has not been built yet. Build it first.")

    token = get_token(workspace_id)
    if not token:
        raise PermissionError("GitHub is not connected. Connect GitHub on the Publish page first.")

    bundle_path = Path(plugin.build.output_path)
    if not bundle_path.is_dir():
        raise FileNotFoundError(f"Build output not found at {bundle_path}. Rebuild the plugin.")

    # Determine version
    current_version = plugin.last_published_version or plugin.build.version or "0.0.0"
    new_version = bump_version(current_version, version_bump, manual_version)

    repo_url = repo_url or plugin.repository_url

    with tempfile.TemporaryDirectory() as tmpdir:
        # ── 1. Create repo if needed ──────────────────────────────────────────
        if create_repo or not repo_url:
            name = repo_name or plugin.slug
            repo_data = _create_github_repo(token, name, private, f"{plugin.name} — Conxa MCP plugin")
            repo_url = repo_data["clone_url"]
            html_url = repo_data["html_url"]
        else:
            # Derive html_url from clone_url (remove .git suffix and token)
            html_url = repo_url.rstrip("/")
            if html_url.endswith(".git"):
                html_url = html_url[:-4]
            if "x-access-token:" in html_url:
                html_url = "https://github.com/" + html_url.split("github.com/", 1)[-1]

        # ── 2. Check tag uniqueness before doing any git work ─────────────────
        tag = f"v{new_version}"
        if _tag_exists_on_remote(repo_url, tag, token):
            raise VersionAlreadyPublished(
                f"Version {tag} is already published to GitHub. Bump the version and try again."
            )

        # ── 3. Init / clone working tree ──────────────────────────────────────
        authed_url = _inject_token(repo_url, token)
        git_config = ["-c", "user.name=Conxa", "-c", "user.email=build@conxa.ai"]

        # Try to clone existing history; fall back to fresh init for brand-new repos.
        clone_result = _run_git(
            git_config + ["clone", "--depth", "1", authed_url, "."],
            cwd=tmpdir,
            check=False,
        )
        if clone_result.returncode != 0:
            # Repo is empty or brand-new — init fresh
            _run_git(["init", "-b", "main"], cwd=tmpdir)
            _run_git(["remote", "add", "origin", authed_url], cwd=tmpdir)

        # ── 4. Copy bundle over working tree ──────────────────────────────────
        for item in bundle_path.iterdir():
            dst = Path(tmpdir) / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

        # ── 5. Update plugin.json with new version + repo URL ────────────────
        description = f"Conxa plugin for {plugin.name}"
        config_file = Path(tmpdir) / "plugin.json"
        if config_file.is_file():
            try:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                cfg["version"] = new_version
                description = str(cfg.get("description") or description)
                if "metadata" not in cfg:
                    cfg["metadata"] = {}
                cfg["metadata"]["repository"] = html_url
                config_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except (json.JSONDecodeError, OSError):
                pass

        # ── 6. Write / append CHANGELOG.md ────────────────────────────────────
        changelog_file = Path(tmpdir) / "CHANGELOG.md"
        entry_lines = [
            f"## v{new_version} — {time.strftime('%Y-%m-%d')}",
            "",
            changelog.strip() if changelog.strip() else "No release notes provided.",
            "",
        ]
        existing = changelog_file.read_text(encoding="utf-8") if changelog_file.is_file() else ""
        changelog_file.write_text("\n".join(entry_lines) + "\n" + existing, encoding="utf-8")

        # ── 7. Strip-test: verify repo contains no runtime/credential files ─────
        _validate_public_artifact(Path(tmpdir))

        # ── 8. Commit + tag + push ─────────────────────────────────────────────
        _run_git([*git_config, "add", "."], cwd=tmpdir)
        commit_msg = f"v{new_version}: {(changelog.strip() or 'release').splitlines()[0][:72]}"
        _run_git([*git_config, "commit", "--allow-empty", "-m", commit_msg], cwd=tmpdir)
        _run_git([*git_config, "tag", tag], cwd=tmpdir)
        _run_git([*git_config, "push", "--force-with-lease", "origin", "HEAD:main", "--tags"], cwd=tmpdir)

        # ── 8. Grab commit SHA ─────────────────────────────────────────────────
        sha_result = _run_git(["rev-parse", "HEAD"], cwd=tmpdir, check=False)
        commit_sha = sha_result.stdout.strip()[:40]

    # ── 9. Persist to plugin record ───────────────────────────────────────────
    update_publish_metadata(
        plugin_id,
        repository_url=repo_url,
        repository_private=private,
        last_published_version=new_version,
        last_commit_sha=commit_sha,
    )

    # Install id must be `owner/repo` — that's what the git resolver in the
    # conxa CLI accepts. Derive it from the GitHub URL we just pushed to so
    # the snippet works regardless of plugin slug / package_id.
    install_id = html_url.rstrip("/").split("github.com/", 1)[-1]
    install_snippet = f"npx -y @kiran_nandi_123/conxa install {install_id}"

    return PublishResult(
        repo_url=html_url,
        version=new_version,
        commit_sha=commit_sha,
        install_snippet=install_snippet,
    )
