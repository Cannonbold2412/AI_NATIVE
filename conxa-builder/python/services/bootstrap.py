"""First-run dependency bootstrap for Build Studio.

The installer ships only the irreducible app (Electron + PyInstaller backend).
Everything large or license-encumbered is fetched on first launch into
``%LOCALAPPDATA%\\Conxa\\deps\\`` and SHA-256 verified:

- NSIS (makensis.exe)  -> deps\\nsis\\       (download per cloud manifest)
- Chromium             -> playwright-managed  (playwright install chromium)
- runtime-win.exe      -> deps\\runtime\\{ver} (GitHub Releases via manifest)

Each ``ensure_*`` is idempotent. Progress is reported through ``on_event`` so
the Electron setup screen can render it. Failures surface the exact URL so IT
teams on proxied networks can whitelist or pre-seed manually.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

EventSink = Callable[[dict[str, Any]], None]


def _deps_dir() -> Path:
    base = os.environ.get("SKILL_DATA_DIR") or os.path.expanduser("~/.conxa")
    d = Path(base) / "deps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _emit(on_event: EventSink | None, **kw: Any) -> None:
    if on_event:
        on_event({"phase": "bootstrap", **kw})


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, on_event: EventSink | None, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _emit(on_event, dep=label, status="downloading", url=url)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("content-length") or 0)
            read = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                read += len(chunk)
                if total:
                    _emit(on_event, dep=label, status="downloading", pct=round(100 * read / total))
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        _emit(on_event, dep=label, status="error", url=url,
              message=f"Download failed. If on a corporate network, allow: {url}")
        raise


def _find_nsis_in_dir(nsis_dir: Path) -> Path | None:
    """Return a makensis.exe that has makensisw.exe alongside it, or None.

    On Windows, makensis.exe (2 KB stub) delegates to makensisw.exe in the same
    directory. A standalone makensis.exe without its companion fails with
    'Unable to start child process, error 0x2'.
    """
    for p in nsis_dir.rglob("makensis.exe"):
        if (p.parent / "makensisw.exe").is_file():
            return p
    return None


def ensure_nsis(manifest: dict[str, Any], on_event: EventSink | None = None) -> Path:
    """Ensure makensis.exe is present; return its path. Sets MAKENSIS_PATH."""
    nsis_dir = _deps_dir() / "nsis"

    ready = _find_nsis_in_dir(nsis_dir)
    if ready:
        os.environ["MAKENSIS_PATH"] = str(ready)
        _emit(on_event, dep="nsis", status="ready")
        return ready

    spec = manifest.get("nsis") or {}
    url, sha = spec.get("url"), spec.get("sha256")
    if not url:
        raise RuntimeError("deps manifest missing nsis.url")
    archive = nsis_dir / "nsis.zip"
    _download(url, archive, on_event, "nsis")
    if sha and _sha256(archive) != sha:
        archive.unlink(missing_ok=True)
        raise RuntimeError("nsis checksum mismatch")
    with zipfile.ZipFile(archive) as z:
        z.extractall(nsis_dir)
    archive.unlink(missing_ok=True)
    ready = _find_nsis_in_dir(nsis_dir)
    if not ready:
        raise RuntimeError("makensis.exe not found in NSIS archive")
    os.environ["MAKENSIS_PATH"] = str(ready)
    _emit(on_event, dep="nsis", status="ready")
    return ready


def ensure_chromium(on_event: EventSink | None = None) -> None:
    """Ensure the Playwright Chromium build is available.

    Dev mode: uses Playwright's default managed location (AppData/Local/ms-playwright).
    Packaged (frozen) mode: installs into ~/.conxa/deps/chromium so the app is self-contained.
    """
    if getattr(sys, "frozen", False):
        # Packaged build: redirect to a managed path under ~/.conxa/deps/
        browsers_path = _deps_dir() / "chromium"
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
        if any(browsers_path.glob("chromium-*")):
            _emit(on_event, dep="chromium", status="ready")
            return
        _emit(on_event, dep="chromium", status="installing")
        driver_dir = Path(sys._MEIPASS) / "playwright" / "driver"  # type: ignore[attr-defined]
        node_exe = driver_dir / ("node.exe" if sys.platform == "win32" else "node")
        driver_js = driver_dir / "package" / "cli.js"
        proc = subprocess.run(
            [str(node_exe), str(driver_js), "install", "chromium"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            _emit(on_event, dep="chromium", status="error", message=proc.stderr[-500:])
            raise RuntimeError(f"playwright install chromium failed: {proc.stderr[-300:]}")
    else:
        # Dev mode: use Playwright's default location; install only if missing (fast no-op if present).
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            _emit(on_event, dep="chromium", status="error", message=proc.stderr[-500:])
            raise RuntimeError(f"playwright install chromium failed: {proc.stderr[-300:]}")
    _emit(on_event, dep="chromium", status="ready")


def ensure_runtime(manifest: dict[str, Any], on_event: EventSink | None = None) -> Path:
    """Ensure runtime-win.exe + keytar.node are cached. Returns the runtime dir."""
    spec = manifest.get("runtime") or {}
    version = spec.get("version") or "v0.0.0"
    runtime_dir = _deps_dir() / "runtime" / version
    exe = runtime_dir / "runtime-win.exe"
    if exe.is_file():
        _emit(on_event, dep="runtime", status="ready", version=version)
        return runtime_dir

    # The manifest uses win_url/win_sha256 (platform-specific keys).
    url = spec.get("win_url") or spec.get("url")
    sha = spec.get("win_sha256") or spec.get("sha256")
    if not url:
        raise RuntimeError("deps manifest missing runtime.win_url")
    _download(url, exe, on_event, "runtime")
    if sha and _sha256(exe) != sha:
        exe.unlink(missing_ok=True)
        raise RuntimeError("runtime checksum mismatch")
    keytar_url = spec.get("keytar_url")
    if keytar_url:
        _download(keytar_url, runtime_dir / "keytar.node", on_event, "runtime")
    os.environ["CONXA_RUNTIME_LOCAL_DIR"] = str(runtime_dir)
    _emit(on_event, dep="runtime", status="ready", version=version)
    return runtime_dir


def check_status() -> dict[str, Any]:
    """Fast, offline check of which deps are already present. No downloads."""
    deps = _deps_dir()

    nsis_ready = _find_nsis_in_dir(deps / "nsis") is not None

    chromium_dir = deps / "chromium"
    chromium_ready = chromium_dir.is_dir() and any(
        d.is_dir() and d.name.startswith("chromium-") for d in chromium_dir.iterdir()
    ) if chromium_dir.is_dir() else False

    runtime_dir = deps / "runtime"
    runtime_ready = False
    if runtime_dir.is_dir():
        for ver_dir in runtime_dir.iterdir():
            if (ver_dir / "runtime-win.exe").is_file():
                runtime_ready = True
                break

    all_ready = nsis_ready and chromium_ready and runtime_ready
    return {
        "nsis": nsis_ready,
        "chromium": chromium_ready,
        "runtime": runtime_ready,
        "all_ready": all_ready,
    }


def fetch_manifest(cloud_api: str) -> dict[str, Any]:
    """Fetch the deps manifest so versions bump without reshipping Studio."""
    import json

    url = f"{cloud_api.rstrip('/')}/api/v1/updates/deps-manifest"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_all(cloud_api: str, on_event: EventSink | None = None) -> dict[str, Any]:
    """Run every ensure_* step. Returns a summary the UI can display."""
    manifest = fetch_manifest(cloud_api)
    ensure_chromium(on_event)
    ensure_nsis(manifest, on_event)
    ensure_runtime(manifest, on_event)
    _emit(on_event, status="complete")
    return {"ok": True, "manifest_version": manifest.get("version")}
