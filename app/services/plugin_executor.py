"""Plugin skill execution via the Conxa shared runtime (MCP stdio).

Replaces the old bundle-local server.js approach. The shared runtime lives at
~/.conxa/ (Mac/Linux) or C:\\Program Files\\Conxa\\ (Windows); see conxa_runtime.py
for the resolution order.

Auth flow: the runtime always handles authentication itself. On first run it opens
a visible browser so the author logs in; the session is saved to the runtime's
sessions dir and reused on subsequent runs without re-prompting.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.config import settings
from app.models.plugin import Plugin


def _bundle_slug(plugin: Plugin) -> str:
    from app.services.plugin_builder import _plugin_bundle_slug
    return _plugin_bundle_slug(plugin.id, plugin.name)


async def execute_skill(
    plugin: Plugin,
    skill_slug: str,
    inputs: dict,
    headless: bool = False,
    timeout_s: int = 300,
    log_sink: Callable[[str], None] | None = None,
) -> dict:
    """Run a compiled workflow skill via the shared Conxa runtime.

    headless defaults to False: the author watches execution and logs in interactively
    on first run. The runtime saves the session for subsequent runs.
    Raises ValueError/RuntimeError on failure (caller surfaces to SSE error frame).
    """
    if plugin.build is None:
        raise ValueError("Plugin not built yet.")

    from app.services.conxa_runtime import resolve_runtime_dir, sync_skill_pack
    runtime_dir = resolve_runtime_dir()
    if runtime_dir is None:
        raise RuntimeError(
            "Conxa runtime not found. "
            "Install it at ~/.conxa/ (Mac/Linux) or C:\\Program Files\\Conxa\\ (Windows), "
            "or set the CONXA_DIR environment variable to its location."
        )

    company = _bundle_slug(plugin)

    # Determine effective CONXA_DIR for the spawned process.
    # Dev fallback (repo ./runtime/): skills live in settings.data_dir already — just point there.
    # Installed runtime: sync from settings.data_dir/skill-packs/ into the runtime dir first.
    repo_root = Path(__file__).resolve().parent.parent.parent
    if runtime_dir == repo_root / "runtime":
        conxa_dir = settings.data_dir
    else:
        source = settings.data_dir / "skill-packs" / company
        sync_skill_pack(company=company, source_dir=source, runtime_dir=runtime_dir)
        conxa_dir = runtime_dir

    # Ensure Playwright Chromium is installed for this runtime.
    # server.js looks for browsers at <CONXA_DIR>/chromium/ — install there if absent.
    from app.services.conxa_runtime import ensure_chromium_installed
    ensure_chromium_installed(
        browsers_dir=conxa_dir / "chromium",
        runtime_dir=runtime_dir,
        log_sink=log_sink,
    )

    from app.services.mcp_stdio_client import execute_skill_via_runtime
    return await execute_skill_via_runtime(
        runtime_dir=runtime_dir,
        conxa_dir=conxa_dir,
        company=company,
        skill_slug=skill_slug,
        inputs=inputs,
        headless=headless,
        timeout_s=timeout_s,
        log_sink=log_sink,
    )
