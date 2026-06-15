"""Dependency bootstrap and update manager for Build Studio.

The installer ships only the irreducible app (Electron + PyInstaller backend).
All other dependencies are managed independently from the app version:

- NSIS (makensis.exe)  -> deps/nsis/{version}/   (versioned, cloud manifest)
- Chromium             -> playwright-managed       (playwright install chromium)
- runtime-win.exe      -> deps/runtime/{version}/  (versioned, cloud manifest)

On every startup, ``ensure_all()`` fetches the cloud manifest (cached 24 h),
compares each dep version against ``deps/installed.json``, and downloads only
what changed. Progress is reported through ``on_event`` so the Electron setup
screen can render it. Failures surface the exact URL so IT teams on proxied
networks can whitelist or pre-seed manually.

Updating a dep (e.g. runtime v1.0.1) requires only a cloud env-var change —
no new Build Studio release needed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

EventSink = Callable[[dict[str, Any]], None]


def _deps_dir() -> Path:
    base = os.environ.get("SKILL_DATA_DIR") or os.path.expanduser("~/.conxa-build-studio")
    d = Path(base) / "deps"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Installed-versions ledger ─────────────────────────────────────────────────

def _installed_path() -> Path:
    return _deps_dir() / "installed.json"


def _manifest_cache_path() -> Path:
    return _deps_dir() / "manifest-cache.json"


def load_installed() -> dict[str, Any]:
    """Return the installed-versions ledger, or {} if it doesn't exist yet."""
    p = _installed_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_installed(data: dict[str, Any]) -> None:
    """Atomically write the installed-versions ledger."""
    p = _installed_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


# ── Manifest TTL cache ────────────────────────────────────────────────────────

def load_manifest_cache(cloud_api: str, *, force: bool = False) -> dict[str, Any]:
    """Return the deps manifest, using a local 24 h cache to avoid repeated fetches.

    Pass ``force=True`` to bypass the cache and always hit the cloud.
    """
    ttl = int(os.environ.get("CONXA_DEPS_MANIFEST_TTL_SECONDS", 86400))
    cache_path = _manifest_cache_path()

    if not force and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("_cached_at", 0)) < ttl:
                return cached
        except Exception:
            pass

    manifest = fetch_manifest(cloud_api)
    manifest["_cached_at"] = time.time()
    tmp = cache_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_path)
    return manifest


# ── Update detection ──────────────────────────────────────────────────────────

def check_for_updates(cloud_api: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Return a list of deps that have a newer version available in the manifest.

    Each entry: {"dep": str, "installed": str|None, "available": str}
    Deps with ``managed_by`` (e.g. chromium managed by Playwright) are skipped.
    """
    manifest = load_manifest_cache(cloud_api, force=force)
    installed = load_installed()
    outdated: list[dict[str, Any]] = []
    for dep_name, dep_spec in manifest.get("deps", {}).items():
        if dep_spec.get("managed_by"):
            continue
        avail_ver = dep_spec.get("version")
        if not avail_ver:
            continue
        inst_ver = installed.get(dep_name, {}).get("version")
        version_dir = _deps_dir() / dep_name / avail_ver
        if inst_ver != avail_ver or not version_dir.is_dir():
            outdated.append({"dep": dep_name, "installed": inst_ver, "available": avail_ver})
    return outdated


# ── Generic atomic installer ──────────────────────────────────────────────────

def _configure_dep_env(dep_name: str, version_dir: Path) -> None:
    """Set the env var that downstream tools use to locate this dep."""
    if dep_name == "nsis":
        ready = _find_nsis_in_dir(version_dir)
        if ready:
            os.environ["MAKENSIS_PATH"] = str(ready)
    elif dep_name == "runtime":
        os.environ["CONXA_RUNTIME_LOCAL_DIR"] = str(version_dir)


def apply_dep_update(
    dep_name: str,
    dep_spec: dict[str, Any],
    on_event: EventSink | None = None,
) -> None:
    """Download, verify, and atomically install a new dep version.

    On success the previous version dir is kept as ``{version}.prev`` for
    one-step rollback. The installed-versions ledger is updated atomically.
    Leaves no partial state on failure — the temp dir is cleaned up.
    """
    version = dep_spec["version"]
    dep_dir = _deps_dir() / dep_name
    version_dir = dep_dir / version
    tmp_dir = dep_dir / f".tmp-{int(time.time())}"

    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)

        for file_spec in dep_spec.get("files", []):
            filename = file_spec["filename"]
            url = file_spec["url"]
            sha = file_spec.get("sha256", "")
            action = file_spec.get("action", "copy")
            dest = tmp_dir / filename

            _download(url, dest, on_event, dep_name, file_name=filename)
            _emit(on_event, dep=dep_name, status="verifying", file_name=filename)
            if sha and _sha256(dest) != sha:
                dest.unlink(missing_ok=True)
                _emit(on_event, dep=dep_name, status="error",
                      message=f"{filename} checksum mismatch")
                raise RuntimeError(f"{dep_name} {filename} checksum mismatch")

            if action == "extract_zip":
                _emit(on_event, dep=dep_name, status="extracting", file_name=filename)
                with zipfile.ZipFile(dest) as z:
                    z.extractall(tmp_dir)
                dest.unlink(missing_ok=True)

        # Keep previous version as .prev for rollback
        if version_dir.exists():
            prev_dir = dep_dir / f"{version}.prev"
            if prev_dir.exists():
                shutil.rmtree(prev_dir)
            version_dir.rename(prev_dir)

        tmp_dir.rename(version_dir)

        installed = load_installed()
        installed[dep_name] = {"version": version}
        save_installed(installed)

        _configure_dep_env(dep_name, version_dir)
        _emit(on_event, dep=dep_name, status="ready", version=version)

    except Exception:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def rollback_dep(dep_name: str) -> bool:
    """Restore the previous version of a dep from its .prev dir.

    Returns True if a rollback was available and applied, False otherwise.
    Updates installed.json so the next startup reflects the reverted version.
    """
    installed = load_installed()
    current_ver = installed.get(dep_name, {}).get("version", "")
    dep_dir = _deps_dir() / dep_name
    prev_dir = dep_dir / f"{current_ver}.prev" if current_ver else None

    if not prev_dir or not prev_dir.exists():
        # Try any .prev directory as a last resort
        prev_candidates = list(dep_dir.glob("*.prev")) if dep_dir.is_dir() else []
        if not prev_candidates:
            return False
        prev_dir = prev_candidates[0]

    prev_version = prev_dir.name.removesuffix(".prev")
    current_dir = dep_dir / current_ver if current_ver else None
    if current_dir and current_dir.exists():
        shutil.rmtree(current_dir, ignore_errors=True)
    prev_dir.rename(dep_dir / prev_version)

    installed[dep_name] = {"version": prev_version}
    save_installed(installed)
    _configure_dep_env(dep_name, dep_dir / prev_version)
    return True


def chromium_dir() -> Path:
    """Managed Playwright browsers directory for frozen builds (~/.conxa-build-studio/deps/chromium)."""
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
        encoding='utf-8',
        errors='replace',
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
    installed = load_installed()

    # NSIS: check installed version dir, fall back to legacy flat dir
    nsis_ver = installed.get("nsis", {}).get("version")
    if nsis_ver:
        nsis_ready = _find_nsis_in_dir(deps / "nsis" / nsis_ver) is not None
    else:
        nsis_ready = _find_nsis_in_dir(deps / "nsis") is not None

    chromium_dir_ = deps / "chromium"
    chromium_ready = (
        chromium_dir_.is_dir()
        and any(d.is_dir() and d.name.startswith("chromium-") for d in chromium_dir_.iterdir())
    ) if chromium_dir_.is_dir() else False

    runtime_ready = False
    runtime_dir = deps / "runtime"
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
        "versions": {
            k: v.get("version") for k, v in installed.items() if isinstance(v, dict)
        },
    }


def fetch_manifest(cloud_api: str) -> dict[str, Any]:
    """Fetch the deps manifest so versions bump without reshipping Studio."""
    import json

    url = f"{cloud_api.rstrip('/')}/api/v1/updates/deps-manifest"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_all(cloud_api: str, on_event: EventSink | None = None) -> dict[str, Any]:
    """Ensure all deps are present and up-to-date. Runs on every startup.

    Always fetches the cloud manifest fresh (cache bypassed), then for each dep:
    - If already at the correct version: set env var, emit ready.
    - If missing or outdated: download, verify, atomically install.
    Falls back gracefully when the network is unavailable.
    """
    # Chromium is managed by Playwright; always ensure it first
    ensure_chromium(on_event)

    # Fetch manifest (with TTL cache; tolerate network failures)
    try:
        manifest = load_manifest_cache(cloud_api, force=True)
    except Exception as exc:
        _emit(on_event, status="warning",
              message=f"Manifest fetch failed: {exc}. Using installed deps.")
        manifest = {}

    deps = manifest.get("deps", {})
    if deps:
        installed = load_installed()
        for dep_name, dep_spec in deps.items():
            if dep_spec.get("managed_by"):
                continue
            avail_ver = dep_spec.get("version")
            if not avail_ver:
                continue
            inst_ver = installed.get(dep_name, {}).get("version")
            version_dir = _deps_dir() / dep_name / avail_ver
            if inst_ver == avail_ver and version_dir.is_dir():
                _configure_dep_env(dep_name, version_dir)
                _emit(on_event, dep=dep_name, status="ready", version=avail_ver)
            else:
                apply_dep_update(dep_name, dep_spec, on_event=on_event)
    else:
        # Legacy fallback: cloud manifest predates v2 (no deps dict)
        ensure_nsis(manifest, on_event)
        ensure_runtime(manifest, on_event)

    _emit(on_event, status="complete")
    return {"ok": True, "manifest_version": manifest.get("manifest_version", manifest.get("version"))}
