"""Locate the installed Conxa shared runtime and stage skill-pack data into it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_runtime_dir() -> Path | None:
    """Find the Conxa shared runtime directory containing server.js.

    Priority:
      1. $CONXA_DIR env var (explicit override — trusted as-is)
      2. Installed location (C:\\Program Files\\Conxa on Windows, ~/.conxa on Mac/Linux)
      3. Repo-local ./runtime/ (dev fallback — only if server.js + package.json exist)

    Returns None if no valid runtime is found.
    """
    # 1. Explicit env override
    env_dir = os.environ.get("CONXA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir)
        if (p / "server.js").is_file():
            return p

    # 2. Installed location
    if sys.platform == "win32":
        installed = Path(r"C:\Program Files\Conxa")
    else:
        installed = Path.home() / ".conxa"
    if (installed / "server.js").is_file():
        return installed

    # 3. Repo-local dev fallback
    repo_root = Path(__file__).resolve().parent.parent.parent
    dev = repo_root / "runtime"
    if (dev / "server.js").is_file() and (dev / "package.json").is_file():
        return dev

    return None


def resolve_conxa_data_dir() -> Path:
    """Resolve CONXA_DATA_DIR (user-writable; mirrors runtime/server.js logic)."""
    env_dir = os.environ.get("CONXA_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "Conxa"
    return Path.home() / ".conxa"


def sync_skill_pack(company: str, source_dir: Path, runtime_dir: Path) -> None:
    """Copy source_dir → <runtime_dir>/skill-packs/<company>/, then bust the manifest cache.

    The runtime caches skill index in CONXA_DATA_DIR/cache/manifests.json for fast startup.
    Deleting that file forces a fresh filesystem scan so the newly synced skill is visible.

    No-op if source_dir doesn't exist.
    """
    if not source_dir.is_dir():
        return

    dest = runtime_dir / "skill-packs" / company
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(source_dir), str(dest), dirs_exist_ok=True)

    # Bust the skill manifest cache so the spawned runtime rescans from disk
    cache_file = resolve_conxa_data_dir() / "cache" / "manifests.json"
    if cache_file.is_file():
        try:
            cache_file.unlink()
        except OSError:
            pass


def ensure_chromium_installed(
    browsers_dir: Path,
    runtime_dir: Path,
    log_sink=None,
) -> None:
    """Install Playwright Chromium into browsers_dir if not already present.

    browsers_dir is where server.js will look (CONXA_DIR/chromium).
    Runs `npx playwright install chromium` inside runtime_dir with the
    correct PLAYWRIGHT_BROWSERS_PATH override.  No-op if already installed.
    """
    import shutil as _shutil

    # Consider it installed if there is at least one chromium-* subdirectory
    if browsers_dir.is_dir() and any(
        d.is_dir() and d.name.startswith("chromium-")
        for d in browsers_dir.iterdir()
    ):
        return

    node = _shutil.which("node")
    npx = _shutil.which("npx")
    if not npx or not node:
        raise RuntimeError("Node.js / npx not found. Install Node.js to continue.")

    if log_sink:
        log_sink("Installing Playwright Chromium for the test runtime (one-time setup)…")

    browsers_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir)}

    result = subprocess.run(
        [npx, "playwright", "install", "chromium"],
        cwd=str(runtime_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Playwright install failed:\n{result.stderr or result.stdout}"
        )
