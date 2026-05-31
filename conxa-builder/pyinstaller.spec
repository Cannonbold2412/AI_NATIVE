# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Conxa Build Studio Python backend.
#
# Output: dist/backend/  (--onedir, NOT --onefile — faster startup)
# Bundled into the Electron app by electron-builder as an extraFile.
#
# The app/ directory is imported verbatim as a library. db.py filesystem
# fallback activates automatically when SKILL_DATABASE_URL is unset.

import sys
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# Repo root is one level up from this spec file (conxa-builder/pyinstaller.spec).
REPO_ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is injected by PyInstaller)
BACKEND_DIR = REPO_ROOT / "conxa-builder" / "python"
# Make conxa_compile importable in the spec-execution context so that
# collect_submodules() below can find all submodules. pathex only affects
# the Analysis module graph, not the process sys.path used by collect_* calls.
sys.path.insert(0, str(BACKEND_DIR))

block_cipher = None

# Collect the local compile pipeline (conxa_compile, lives in BACKEND_DIR) and the
# installed shared foundation (conxa_core, installed as a dependency). Data files
# carry bridge.js, policy JSON, and the plugin/installer templates — without these
# the frozen backend builds but fails at runtime.
_core_data = collect_data_files(
    "conxa_core", includes=["**/*.json", "storage/**"]
)


def _fs_collect(src_root: Path, dest_prefix: str, patterns):
    """Glob for data files directly on the filesystem.

    collect_data_files() requires the package to be pip-installed (dist-info);
    conxa_compile is not, so we glob the source tree directly instead.
    """
    result = []
    for pat in patterns:
        for f in src_root.rglob(pat):
            dest = str(Path(dest_prefix) / f.relative_to(src_root).parent)
            result.append((str(f), dest))
    return result


_compile_data = _fs_collect(
    BACKEND_DIR / "conxa_compile",
    "conxa_compile",
    ["*.js", "*.json", "*.tmpl", "*.gitignore"],
)
# Playwright ships a self-contained Node driver used to download browsers at runtime.
# collect_all bundles the driver binary + CLI scripts so ensure_chromium() works when frozen.
_playwright_datas, _playwright_binaries, _ = collect_all("playwright")

a = Analysis(
    [str(BACKEND_DIR / "backend.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=_playwright_binaries,
    datas=_core_data + _compile_data + _playwright_datas,
    hiddenimports=(
        collect_submodules("conxa_core")
        + collect_submodules("conxa_compile")
        + [
            # Services layer used by backend.py.
            "services.auth_service",
            "services.bootstrap",
            "services.installer_builder",
            "services.llm_proxy_client",
            "services.metadata_reporter",
            "services.validation",
            # Python stdlib extras sometimes missed by the hook.
            "email.mime.multipart",
            "email.mime.text",
            "xml.etree.ElementTree",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Don't pull in the full Next.js / React toolchain accidentally.
        "frontend",
        # Test-only deps.
        "pytest",
        "hypothesis",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # --onedir: binaries go into the collect step
    name="backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,            # backend communicates via stdio; needs a console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="backend",
)
