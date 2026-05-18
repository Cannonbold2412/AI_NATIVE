"""Build a signed Windows NSIS installer for a compiled skill pack.

The installer bundles:
- runtime.exe + keytar.node (fetched from Conxa CDN or a local build)
- skill-packs/{company}/ directory
- NSIS install script that registers the Conxa MCP server in Claude Desktop

Usage:
    from app.services.installer_builder import build_installer
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
from pathlib import Path
from typing import Any, Callable

from app.config import settings

RUNTIME_CDN_URL   = os.getenv("CONXA_RUNTIME_CDN_URL", "https://cdn.conxa.io/runtime")
RUNTIME_VERSION   = os.getenv("CONXA_RUNTIME_VERSION", "1.0.0")
SIGNTOOL_PATH     = os.getenv("CONXA_SIGNTOOL_PATH", "signtool.exe")
SIGN_CERT_SHA1    = os.getenv("CONXA_SIGN_CERT_SHA1", "")
MAKENSIS_PATH     = os.getenv("MAKENSIS_PATH", "makensis")


def build_installer(
    plugin_id: str,
    *,
    company_slug: str,
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Compile a plugin into a Windows installer EXE.

    Returns dict with keys: installer_path, filename, company, plugin_id, version.
    Raises ValueError / RuntimeError on build failure.
    """
    from app.services.plugin_builder import build_plugin
    from app.storage.plugin_store import get_plugin, set_installer

    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise ValueError(f"Plugin {plugin_id!r} not found.")

    def _log(msg: str, **extra: Any) -> None:
        if realtime_sink:
            realtime_sink({"kind": "installer_build", "message": msg, **extra})

    # ── 1. Build skill pack ────────────────────────────────────────────────────
    _log("Building skill pack…")
    build_result = build_plugin(plugin_id, version=RUNTIME_VERSION, realtime_sink=realtime_sink)
    skill_pack_dir = settings.data_dir / "skill-packs" / company_slug
    _log("Skill pack built", skills=build_result.get("skills", []))

    if not skill_pack_dir.is_dir():
        raise RuntimeError(
            f"skill-packs/{company_slug}/ directory not found after build. "
            "Check that the plugin has at least one workflow."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # ── 2. Fetch or copy runtime binary ───────────────────────────────────
        _log(f"Fetching runtime v{RUNTIME_VERSION}…")
        runtime_dir = tmp / "runtime"
        runtime_dir.mkdir()
        _stage_runtime_binary(runtime_dir)
        _log("Runtime staged")

        # ── 3. Stage skill pack ───────────────────────────────────────────────
        staged_packs = tmp / "skill-packs" / company_slug
        shutil.copytree(skill_pack_dir, staged_packs)
        _log("Skill packs staged")

        # ── 4. Render NSIS script ─────────────────────────────────────────────
        company_name = plugin.name
        pack_json_path = staged_packs / "pack.json"
        version = RUNTIME_VERSION
        if pack_json_path.is_file():
            try:
                pack = json.loads(pack_json_path.read_text(encoding="utf-8"))
                version = pack.get("skill_pack_version", RUNTIME_VERSION)
            except Exception:
                pass

        nsi_path = _render_nsis_script(tmp, company_slug, company_name, version)
        _log("NSIS script rendered")

        # ── 5. Compile installer ──────────────────────────────────────────────
        safe_name = company_name.replace(" ", "")
        installer_name = f"{safe_name}-Claude-Setup.exe"
        installer_path = tmp / installer_name

        makensis = shutil.which(MAKENSIS_PATH) or MAKENSIS_PATH
        if not shutil.which(makensis):
            raise RuntimeError(
                f"makensis not found at {makensis!r}. "
                "Install NSIS (https://nsis.sourceforge.io/) to build installers."
            )

        _log("Running makensis…")
        result = subprocess.run(
            [makensis, "/V2", f"/DOUTPUT_PATH={installer_path}", str(nsi_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"makensis failed (exit {result.returncode}):\n{result.stderr[-2000:]}")
        _log("NSIS compilation complete")

        # ── 6. Code sign (CI only) ────────────────────────────────────────────
        if SIGN_CERT_SHA1 and shutil.which(SIGNTOOL_PATH):
            _log("Code signing…")
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
                _log("Installer signed")
        else:
            _log("Code signing skipped (no EV cert configured)", warning=True)

        # ── 7. Persist installer ──────────────────────────────────────────────
        out_dir = settings.data_dir / "installers"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / installer_name
        shutil.copy2(installer_path, dest)
        _log("Installer saved", path=str(dest))

    # Persist installer record
    try:
        set_installer(
            plugin_id,
            installer_path=str(dest),
            filename=installer_name,
            version=version,
            runtime_version=RUNTIME_VERSION,
        )
    except Exception:
        pass

    return {
        "installer_path": str(dest),
        "filename":       installer_name,
        "company":        company_slug,
        "plugin_id":      plugin_id,
        "version":        version,
        "runtime_version": RUNTIME_VERSION,
    }


def _stage_runtime_binary(dest: Path) -> None:
    """Stage runtime.exe + keytar.node into dest/.

    Tries the local repo build first (dev), then the CDN.
    """
    repo_root   = Path(__file__).parent.parent.parent
    local_exe   = repo_root / "runtime" / "dist" / "runtime-win.exe"
    local_node  = repo_root / "runtime" / "node_modules" / "keytar" / "build" / "Release" / "keytar.node"

    if local_exe.is_file():
        shutil.copy2(local_exe, dest / "runtime.exe")
    else:
        _download_file(f"{RUNTIME_CDN_URL}/{RUNTIME_VERSION}/runtime-win.exe", dest / "runtime.exe")

    if local_node.is_file():
        shutil.copy2(local_node, dest / "keytar.node")
    else:
        try:
            _download_file(f"{RUNTIME_CDN_URL}/{RUNTIME_VERSION}/keytar.node", dest / "keytar.node")
        except Exception:
            (dest / "keytar.node").write_bytes(b"")  # placeholder; CI pipeline provides real file

    # version.json
    (dest / "version.json").write_text(
        json.dumps({"runtime_version": RUNTIME_VERSION}), encoding="utf-8"
    )


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)


def _render_nsis_script(tmp: Path, company_slug: str, company_name: str, version: str) -> Path:
    template_path = Path(__file__).parent.parent / "storage" / "installer_templates" / "setup.nsi.tmpl"
    if not template_path.is_file():
        raise FileNotFoundError(f"NSIS template not found: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    rendered = (
        template
        .replace("{{COMPANY_SLUG}}", company_slug)
        .replace("{{COMPANY_NAME}}", company_name)
        .replace("{{VERSION}}", version)
        .replace("{{RUNTIME_VERSION}}", RUNTIME_VERSION)
        .replace("{{STAGING_DIR}}", str(tmp))
    )
    nsi_path = tmp / "setup.nsi"
    nsi_path.write_text(rendered, encoding="utf-8")
    return nsi_path
