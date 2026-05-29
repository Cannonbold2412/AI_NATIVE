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

# Repo root is one level up from this spec file (conxa-builder/pyinstaller.spec).
REPO_ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is injected by PyInstaller)
BACKEND_DIR = REPO_ROOT / "conxa-builder" / "python"
CLOUD_BACKEND_DIR = REPO_ROOT / "conxa-cloud" / "backend"
APP_DIR = CLOUD_BACKEND_DIR / "app"

block_cipher = None

a = Analysis(
    [str(BACKEND_DIR / "backend.py")],
    pathex=[str(CLOUD_BACKEND_DIR), str(BACKEND_DIR)],
    binaries=[],
    datas=[
        # Include the entire app/ package so it can be imported at runtime.
        (str(APP_DIR), "app"),
        # Include Playwright browser binaries path hints (Playwright manages
        # its own download into deps/ at first run via bootstrap.py — we do
        # NOT bundle Chromium here, keeping the installer small).
    ],
    hiddenimports=[
        # FastAPI / Pydantic / SQLAlchemy are imported lazily inside app/.
        "app.config",
        "app.db",
        "app.compiler.build",
        "app.compiler.llm_selector_generator_v2",
        "app.pipeline.run",
        "app.recorder.session",
        "app.services.plugin_builder",
        "app.services.installer_builder",
        "app.storage.snapshots",
        "app.llm.router",
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
    ],
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
