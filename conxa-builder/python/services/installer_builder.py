"""Build Studio wrapper over app.services.installer_builder.

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
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    # Point the shared builder at the bootstrapped NSIS if not already on PATH.
    if not os.environ.get("MAKENSIS_PATH"):
        base = os.environ.get("SKILL_DATA_DIR") or os.path.expanduser("~/.conxa")
        cached = Path(base) / "deps" / "nsis" / "makensis.exe"
        if cached.is_file():
            os.environ["MAKENSIS_PATH"] = str(cached)

    from app.services.installer_builder import build_installer as _build

    return _build(plugin_id, company_slug=company_slug, realtime_sink=realtime_sink)
