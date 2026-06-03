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
import re
import subprocess
import sys
import time
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


def chromium_dir() -> Path:
    """Managed Playwright browsers directory for frozen builds (~/.conxa/deps/chromium)."""
    return _deps_dir() / "chromium"


def configure_playwright_browsers_path() -> None:
    """Point Playwright at the managed Chromium location in frozen builds.

    ensure_chromium() sets PLAYWRIGHT_BROWSERS_PATH, but it only runs during
    first-run bootstrap. On later launches the deps are already present, so
    bootstrap is skipped and the env var is never set — the recorder process
    then falls back to Playwright's default location and fails with
    "Executable doesn't exist". Set it unconditionally at startup so every
    process that launches the browser resolves the managed build. No-op in dev,
    where Playwright's default managed location is used.
    """
    if getattr(sys, "frozen", False):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(chromium_dir())


def _emit(on_event: EventSink | None, **kw: Any) -> None:
    if on_event:
        on_event({"phase": "bootstrap", **kw})


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, on_event: EventSink | None, label: str, file_name: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    display_name = file_name or dest.name
    _emit(on_event, dep=label, status="downloading", url=url, file_name=display_name)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("content-length") or 0)
            read = 0
            started_at = time.monotonic()
            last_emit_at = 0.0

            def emit_progress(force: bool = False) -> None:
                nonlocal last_emit_at
                now = time.monotonic()
                if not force and now - last_emit_at < 0.25:
                    return
                elapsed = max(now - started_at, 0.001)
                bytes_per_sec = read / elapsed if read else None
                remaining = max(total - read, 0) if total else None
                eta_seconds = int(round(remaining / bytes_per_sec)) if remaining and bytes_per_sec else None
                fields: dict[str, Any] = {
                    "dep": label,
                    "status": "downloading",
                    "url": url,
                    "file_name": display_name,
                    "downloaded_bytes": read,
                }
                if total:
                    fields.update(
                        {
                            "total_bytes": total,
                            "remaining_bytes": remaining,
                            "pct": min(100, round(100 * read / total)),
                        }
                    )
                if bytes_per_sec:
                    fields["bytes_per_sec"] = round(bytes_per_sec)
                if eta_seconds is not None:
                    fields["eta_seconds"] = max(0, eta_seconds)
                _emit(on_event, **fields)
                last_emit_at = now

            emit_progress(force=True)
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                read += len(chunk)
                emit_progress()
            emit_progress(force=True)
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
    _download(url, archive, on_event, "nsis", file_name=archive.name)
    _emit(on_event, dep="nsis", status="verifying", file_name=archive.name)
    if sha and _sha256(archive) != sha:
        archive.unlink(missing_ok=True)
        _emit(on_event, dep="nsis", status="error", message="NSIS checksum mismatch")
        raise RuntimeError("nsis checksum mismatch")
    _emit(on_event, dep="nsis", status="extracting", file_name=archive.name)
    with zipfile.ZipFile(archive) as z:
        z.extractall(nsis_dir)
    archive.unlink(missing_ok=True)
    _emit(on_event, dep="nsis", status="verifying")
    ready = _find_nsis_in_dir(nsis_dir)
    if not ready:
        _emit(on_event, dep="nsis", status="error", message="makensis.exe not found in NSIS archive")
        raise RuntimeError("makensis.exe not found in NSIS archive")
    os.environ["MAKENSIS_PATH"] = str(ready)
    _emit(on_event, dep="nsis", status="ready")
    return ready


def _run_playwright_install(cmd: list[str], on_event: EventSink | None) -> None:
    pct_re = re.compile(r"(\d{1,3})\s*%")
    output_tail: list[str] = []
    _emit(on_event, dep="chromium", status="installing", file_name="Chromium")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        text = line.strip()
        if text:
            output_tail.append(text)
            output_tail = output_tail[-20:]
        match = pct_re.search(text)
        pct = min(100, int(match.group(1))) if match else None
        _emit(
            on_event,
            dep="chromium",
            status="installing",
            file_name="Chromium",
            pct=pct,
            message=text[-240:] if text else None,
        )
    code = proc.wait()
    if code != 0:
        message = "\n".join(output_tail)[-500:] or f"playwright install chromium exited with code {code}"
        _emit(on_event, dep="chromium", status="error", message=message)
        raise RuntimeError(f"playwright install chromium failed: {message[-300:]}")


def ensure_chromium(on_event: EventSink | None = None) -> None:
    """Ensure the Playwright Chromium build is available.

    Dev mode: uses Playwright's default managed location (AppData/Local/ms-playwright).
    Packaged (frozen) mode: installs into ~/.conxa/deps/chromium so the app is self-contained.
    """
    if getattr(sys, "frozen", False):
        # Packaged build: redirect to a managed path under ~/.conxa/deps/
        browsers_path = chromium_dir()
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
        if any(browsers_path.glob("chromium-*")):
            _emit(on_event, dep="chromium", status="ready")
            return
        _emit(on_event, dep="chromium", status="installing")
        driver_dir = Path(sys._MEIPASS) / "playwright" / "driver"  # type: ignore[attr-defined]
        node_exe = driver_dir / ("node.exe" if sys.platform == "win32" else "node")
        driver_js = driver_dir / "package" / "cli.js"
        _run_playwright_install([str(node_exe), str(driver_js), "install", "chromium"], on_event)
    else:
        # Dev mode: use Playwright's default location; install only if missing (fast no-op if present).
        _run_playwright_install([sys.executable, "-m", "playwright", "install", "chromium"], on_event)
    _emit(on_event, dep="chromium", status="ready")


def ensure_runtime(manifest: dict[str, Any], on_event: EventSink | None = None) -> Path:
    """Ensure runtime-win.exe + keytar.node are cached. Returns the runtime dir."""
    spec = manifest.get("runtime") or {}
    version = spec.get("version") or "v0.0.0"
    runtime_dir = _deps_dir() / "runtime" / version
    exe = runtime_dir / "runtime-win.exe"
    keytar_url = spec.get("keytar_url")
    keytar = runtime_dir / "keytar.node"
    if exe.is_file() and (not keytar_url or keytar.is_file()):
        os.environ["CONXA_RUNTIME_LOCAL_DIR"] = str(runtime_dir)
        _emit(on_event, dep="runtime", status="ready", version=version)
        return runtime_dir

    # The manifest uses win_url/win_sha256 (platform-specific keys).
    url = spec.get("win_url") or spec.get("url")
    sha = spec.get("win_sha256") or spec.get("sha256")
    if not url:
        raise RuntimeError("deps manifest missing runtime.win_url")
    if not exe.is_file():
        _download(url, exe, on_event, "runtime", file_name=exe.name)
        _emit(on_event, dep="runtime", status="verifying", file_name=exe.name)
        if sha and _sha256(exe) != sha:
            exe.unlink(missing_ok=True)
            _emit(on_event, dep="runtime", status="error", message="Runtime checksum mismatch")
            raise RuntimeError("runtime checksum mismatch")
    if keytar_url and not keytar.is_file():
        _download(keytar_url, keytar, on_event, "runtime", file_name=keytar.name)
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
