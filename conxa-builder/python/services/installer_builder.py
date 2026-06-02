"""Build Studio wrapper over conxa_compile.installer_builder.

The shared builder already locates makensis via the MAKENSIS_PATH env var, which
bootstrap.ensure_nsis sets to the cached deps\\nsis\\makensis.exe. This wrapper
just guarantees that wiring is in place and delegates.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


def build_installer(
    plugin_id: str,
    *,
    company_slug: str,
    logo_path: str | None = None,
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    # Point the shared builder at the bootstrapped NSIS if not already set.
    # Verify makensisw.exe is beside any candidate — the top-level copy is a stub without it.
    if not os.environ.get("MAKENSIS_PATH"):
        base = os.environ.get("SKILL_DATA_DIR") or os.path.expanduser("~/.conxa")
        nsis_dir = Path(base) / "deps" / "nsis"
        if nsis_dir.is_dir():
            for p in nsis_dir.rglob("makensis.exe"):
                if (p.parent / "makensisw.exe").is_file():
                    os.environ["MAKENSIS_PATH"] = str(p)
                    break

    from conxa_compile.installer_builder import build_installer as _build

    return _build(plugin_id, company_slug=company_slug, logo_path=logo_path, realtime_sink=realtime_sink)
