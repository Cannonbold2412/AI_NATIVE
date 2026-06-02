"""Build a signed Windows NSIS installer for a compiled skill pack.

The installer bundles:
- runtime.exe + keytar.node (fetched from Conxa CDN or a local build)
- skill-packs/{company}/ directory
- NSIS install script that registers the Conxa MCP server in Claude Desktop

Usage:
    from conxa_compile.installer_builder import build_installer
    result = build_installer(plugin_id, company_slug="acme")
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from conxa_core.config import settings

_GITHUB_REPO      = os.getenv("CONXA_GITHUB_REPO", "Cannonbold2412/AI_NATIVE")
RUNTIME_CDN_URL   = os.getenv("CONXA_RUNTIME_CDN_URL", f"https://github.com/{_GITHUB_REPO}/releases/download")
RUNTIME_VERSION   = os.getenv("CONXA_RUNTIME_VERSION", "v1.0.0")
SIGNTOOL_PATH     = os.getenv("CONXA_SIGNTOOL_PATH", "signtool.exe")
SIGN_CERT_SHA1    = os.getenv("CONXA_SIGN_CERT_SHA1", "")
MAKENSIS_PATH     = os.getenv("MAKENSIS_PATH", "makensis")

# System NSIS paths — checked last so the bootstrap-managed copy always wins.
_NSIS_WINDOWS_PATHS = [
    r"C:\Program Files (x86)\NSIS\makensis.exe",
    r"C:\Program Files\NSIS\makensis.exe",
]


def _find_makensis() -> str | None:
    """Return the makensis executable path, or None if not found.

    Priority:
      1. MAKENSIS_PATH env var (set by bootstrap.ensure_nsis to the managed copy)
      2. bootstrap cache location (~/.conxa/deps/nsis/makensis.exe)
      3. System PATH
      4. Well-known Windows install locations (last resort)
    """
    # 1. Explicit env var — bootstrap.ensure_nsis sets this to the managed copy.
    # Validate that makensisw.exe is beside it; the top-level copy may be a stub without it.
    env_val = os.getenv("MAKENSIS_PATH", "")
    if env_val and os.path.isfile(env_val):
        if (Path(env_val).parent / "makensisw.exe").is_file():
            return env_val

    # 2. Bootstrap cache location (in case env var was not propagated).
    # makensis.exe on Windows is a stub that needs makensisw.exe in the same dir,
    # so search for a copy that has its companion rather than using the top-level stub.
    base = os.environ.get("SKILL_DATA_DIR") or os.path.expanduser("~/.conxa")
    nsis_dir = Path(base) / "deps" / "nsis"
    if nsis_dir.is_dir():
        for p in nsis_dir.rglob("makensis.exe"):
            if (p.parent / "makensisw.exe").is_file():
                return str(p)

    # 3. System PATH (e.g. CI where choco installs NSIS globally).
    on_path = shutil.which("makensis")
    if on_path:
        return on_path

    # 4. Well-known Windows installation directories.
    for path in _NSIS_WINDOWS_PATHS:
        if os.path.isfile(path):
            return path

    return None


def _stage_logo_icon(src: Path, tmp: Path, log: Callable[[str], None]) -> Path:
    """Convert src image to ICO and place it in tmp/icon.ico."""
    from PIL import Image

    dest = tmp / "icon.ico"
    if src.suffix.lower() == ".ico":
        shutil.copy2(src, dest)
    else:
        img = Image.open(src).convert("RGBA")
        img.save(dest, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    log(f"Logo staged as icon: {dest}")
    return dest


def build_installer(
    plugin_id: str,
    *,
    company_slug: str,
    logo_path: str | None = None,
    version: str | None = None,
    release_notes: str = "",
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Package an already-built plugin into a Windows installer EXE.

    Returns dict with keys: installer_path, filename, company, plugin_id, version.
    Raises ValueError / RuntimeError on build failure.
    """
    from conxa_core.storage.plugin_store import get_plugin, set_installer

    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"Plugin {plugin_id!r} not found.")

    def _log(msg: str, **extra: Any) -> None:
        if realtime_sink:
            realtime_sink({"kind": "installer_build", "message": msg, **extra})

    # ── 0. Locate makensis early so we fail fast before any build work ────────
    makensis = _find_makensis()
    if not makensis:
        checked = ", ".join([MAKENSIS_PATH] + _NSIS_WINDOWS_PATHS)
        raise RuntimeError(
            f"makensis not found. Checked: {checked}.\n"
            "Install NSIS from https://nsis.sourceforge.io/ then restart the server, "
            "or set the MAKENSIS_PATH environment variable to its full path."
        )
    _log(f"Found makensis at: {makensis}")

    # ── 1. Use the existing built skill pack ───────────────────────────────────
    if plugin.build is None:
        raise RuntimeError(
            "Plugin must be built before building the installer. "
            "Run Build Plugin, then Test Plugin, then Build Installer."
        )

    skill_pack_dir = settings.data_dir / "skill-packs" / company_slug
    if not skill_pack_dir.is_dir():
        raise RuntimeError(
            f"Built skill pack not found: skill-packs/{company_slug}. "
            "Run Build Plugin before building the installer."
        )
    pack_json_path = skill_pack_dir / "pack.json"
    if not pack_json_path.is_file():
        raise RuntimeError(
            f"Built skill pack is missing pack.json: skill-packs/{company_slug}/pack.json. "
            "Run Build Plugin before building the installer."
        )
    try:
        pack = json.loads(pack_json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Built skill pack has invalid pack.json: {exc}") from exc

    # The installer must carry a sync_token so the runtime can pull updates without
    # any user-facing Conxa login. publish_skill_pack() writes this token after a
    # successful publish. If it is absent the installer would silently fail to sync.
    if not pack.get("sync_token"):
        raise RuntimeError(
            "pack.json is missing sync_token. "
            "Publish the skill pack to Conxa Cloud before building the installer — "
            "the sync token is minted at publish time and embedded into the installer."
        )

    skills = [str(skill) for skill in pack.get("skills", []) if skill]
    installer_version = str(version or pack.get("skill_pack_version") or plugin.build.version or RUNTIME_VERSION)
    _log(f"Using existing skill pack ({len(skills)} skill(s): {', '.join(skills) if skills else 'none'})")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        _log(f"Working directory: {tmp}")

        # ── 2. Fetch or copy runtime binary ───────────────────────────────────
        _log(f"Fetching runtime {RUNTIME_VERSION}…")
        runtime_dir = tmp / "runtime"
        runtime_dir.mkdir()
        _stage_runtime_binary(runtime_dir, _log)
        _log("Runtime staged")

        # ── 2b. Build .mcpb Desktop Extension ────────────────────────────────
        _log("Building conxa.mcpb…")
        _build_mcpb(tmp, RUNTIME_VERSION, _log)

        # ── 3. Stage skill pack ───────────────────────────────────────────────
        staged_packs = tmp / "skill-packs" / company_slug
        _log(f"Staging skill pack from {skill_pack_dir}…")
        shutil.copytree(skill_pack_dir, staged_packs)
        staged_files = list(staged_packs.rglob("*"))
        _log(f"Skill packs staged ({len(staged_files)} file(s))")

        # ── 3b. Stage logo icon ───────────────────────────────────────────────
        staged_icon: Path | None = None
        if logo_path:
            try:
                staged_icon = _stage_logo_icon(Path(logo_path), tmp, _log)
            except Exception as exc:
                _log(f"Warning: could not process logo ({exc}); proceeding without custom icon.")

        # ── 4. Render NSIS script ─────────────────────────────────────────────
        company_name = plugin.name
        _log(f"Rendering NSIS script (company={company_slug!r}, version={installer_version})…")
        nsi_path = _render_nsis_script(tmp, company_slug, company_name, installer_version, icon_path=staged_icon)
        _log(f"NSIS script written to {nsi_path}")

        # ── 5. Compile installer ──────────────────────────────────────────────
        safe_name = company_name.replace(" ", "")
        installer_name = f"{safe_name}-Claude-Setup.exe"
        installer_path = tmp / installer_name

        _log(f"Running makensis → {installer_name}…")
        result = subprocess.run(
            [makensis, "/V2", f"/DOUTPUT_PATH={installer_path}", str(nsi_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                _log(f"[makensis] {line}")
        if result.returncode != 0:
            stderr_tail = result.stderr[-2000:] if result.stderr else "(no stderr)"
            raise RuntimeError(f"makensis failed (exit {result.returncode}):\n{stderr_tail}")
        _log("NSIS compilation complete")

        # ── 6. Code sign (CI only) ────────────────────────────────────────────
        if SIGN_CERT_SHA1 and shutil.which(SIGNTOOL_PATH):
            _log("Code signing installer…")
            sign_result = subprocess.run([
                SIGNTOOL_PATH, "sign",
                "/sha1", SIGN_CERT_SHA1,
                "/fd",   "SHA256",
                "/tr",   "http://timestamp.digicert.com",
                "/td",   "SHA256",
                str(installer_path),
            ], check=False, capture_output=True, text=True)
            if sign_result.returncode != 0:
                _log(f"Code signing failed (non-fatal): {sign_result.stderr[-500:]}", warning=True)
            else:
                _log("Installer signed successfully")
        else:
            _log("Code signing skipped (no EV cert configured)")

        # ── 7. Persist installer ──────────────────────────────────────────────
        out_dir = settings.data_dir / "installers"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / installer_name
        _log(f"Copying installer to {dest}…")
        shutil.copy2(installer_path, dest)
        size_kb = dest.stat().st_size // 1024
        _log(f"Installer saved ({size_kb} KB): {dest}")

    # Persist installer record
    try:
        set_installer(
            plugin_id,
            installer_path=str(dest),
            filename=installer_name,
            version=installer_version,
            runtime_version=RUNTIME_VERSION,
            release_notes=release_notes,
        )
    except Exception:
        pass

    return {
        "installer_path": str(dest),
        "filename":       installer_name,
        "company":        company_slug,
        "plugin_id":      plugin_id,
        "version":        installer_version,
        "runtime_version": RUNTIME_VERSION,
        "release_notes":   release_notes,
    }


def _build_mcpb(dest: Path, runtime_version: str, log: Callable[[str], None] | None = None) -> Path:
    """Generate conxa.mcpb (a zip containing manifest.json) and place it in dest/.

    The manifest uses the MCPB Desktop Extension spec:
      https://github.com/anthropics/mcpb/blob/main/MANIFEST.md

    Strategy (pointer model, preferred):
      mcp_config.command points at the externally-installed runtime.exe via the
      ${HOME} template variable, which Claude Desktop expands to the user's home dir.
      env.CONXA_DIR tells runtime.exe where to find Chromium + skill packs.

    If Claude Desktop does not support external command paths (Step 1 from the plan):
      swap entry_point to a bundled runtime.exe copy inside the zip and update command
      to the relative path "runtime/runtime.exe". The CONXA_DIR env var continues to
      work in either case — it is the key that decouples the extension from the data.
    """
    def _info(msg: str) -> None:
        if log:
            log(msg)

    # Windows path separator in the manifest uses backslashes inside ${HOME}/… template.
    # Claude Desktop on Windows expands ${HOME} to the user's home directory.
    manifest = {
        "schema_version": "v1",
        "name": "Conxa",
        "version": runtime_version,
        "description": "Run your company's Conxa automation skills inside Claude Desktop.",
        "author": "Conxa",
        "server": {
            "type": "binary",
            # Pointer model: command is the shared self-updating runtime installed by the .exe.
            # Claude Desktop expands ${HOME} to the current user's home directory.
            "mcp_config": {
                "command": "${HOME}\\AppData\\Local\\Conxa\\runtime\\runtime.exe",
                "args": [],
                "env": {
                    # CONXA_DIR tells runtime.exe where its Chromium + skill packs live.
                    # This is the same value the NSIS installer unpacks files into.
                    "CONXA_DIR": "${HOME}\\AppData\\Local\\Conxa",
                },
                "platform_overrides": {
                    "darwin": {
                        "command": "${HOME}/.conxa/runtime/runtime",
                        "env": {
                            "CONXA_DIR": "${HOME}/.conxa",
                        },
                    },
                },
            },
        },
        "compatibility": {
            "claude_desktop": ">=0.1.0",
            "platforms": ["win32", "darwin"],
        },
    }

    mcpb_path = dest / "conxa.mcpb"
    with zipfile.ZipFile(mcpb_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    _info(f"conxa.mcpb built ({mcpb_path.stat().st_size // 1024} KB): {mcpb_path}")
    return mcpb_path


def _stage_runtime_binary(dest: Path, log: Callable[[str], None] | None = None) -> None:
    """Stage runtime.exe + keytar.node into dest/.

    Tries the local repo build first (dev), then the CDN.
    """
    def _info(msg: str) -> None:
        if log:
            log(msg)

    builder_root = Path(__file__).parent.parent.parent
    repo_root = builder_root.parent
    runtime_roots = [builder_root / "runtime", repo_root / "runtime"]
    local_exe = next(
        (root / "dist" / "runtime-win.exe" for root in runtime_roots if (root / "dist" / "runtime-win.exe").is_file()),
        runtime_roots[0] / "dist" / "runtime-win.exe",
    )
    local_node = next(
        (
            root / "node_modules" / "keytar" / "build" / "Release" / "keytar.node"
            for root in runtime_roots
            if (root / "node_modules" / "keytar" / "build" / "Release" / "keytar.node").is_file()
        ),
        runtime_roots[0] / "node_modules" / "keytar" / "build" / "Release" / "keytar.node",
    )

    if local_exe.is_file():
        _info(f"Copying local runtime.exe from {local_exe}")
        shutil.copy2(local_exe, dest / "runtime.exe")
    else:
        url = f"{RUNTIME_CDN_URL}/{RUNTIME_VERSION}/runtime-win.exe"
        _info(f"Downloading runtime.exe from {url}")
        _download_file(url, dest / "runtime.exe")
    _info(f"runtime.exe staged ({(dest / 'runtime.exe').stat().st_size // 1024} KB)")

    if local_node.is_file():
        _info(f"Copying local keytar.node from {local_node}")
        shutil.copy2(local_node, dest / "keytar.node")
    else:
        url = f"{RUNTIME_CDN_URL}/{RUNTIME_VERSION}/keytar.node"
        try:
            _info(f"Downloading keytar.node from {url}")
            _download_file(url, dest / "keytar.node")
        except Exception:
            _info("keytar.node not available — using placeholder (CI pipeline provides real file)")
            (dest / "keytar.node").write_bytes(b"")

    # version.json
    (dest / "version.json").write_text(
        json.dumps({"runtime_version": RUNTIME_VERSION}), encoding="utf-8"
    )
    _info("version.json written")


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)


def _render_nsis_script(
    tmp: Path,
    company_slug: str,
    company_name: str,
    version: str,
    icon_path: Path | None = None,
) -> Path:
    import conxa_core.storage as _storage

    template_path = Path(_storage.__file__).parent / "installer_templates" / "setup.nsi.tmpl"
    if not template_path.is_file():
        raise FileNotFoundError(f"NSIS template not found: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    icon_directive = f'Icon "{icon_path}"' if icon_path else ""
    rendered = (
        template
        .replace("{{COMPANY_SLUG}}", company_slug)
        .replace("{{COMPANY_NAME}}", company_name)
        .replace("{{VERSION}}", version)
        .replace("{{RUNTIME_VERSION}}", RUNTIME_VERSION)
        .replace("{{STAGING_DIR}}", str(tmp))
        .replace("{{ICON_DIRECTIVE}}", icon_directive)
    )
    nsi_path = tmp / "setup.nsi"
    nsi_path.write_text(rendered, encoding="utf-8")
    return nsi_path
