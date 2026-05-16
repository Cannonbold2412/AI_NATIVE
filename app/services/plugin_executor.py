"""Remote skill execution — runs a built plugin's server.js in CLI mode."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from app.models.plugin import Plugin


async def execute_skill(
    plugin: Plugin,
    skill_slug: str,
    inputs: dict,
    headless: bool = True,
    timeout_s: int = 300,
) -> dict:
    if plugin.build is None:
        raise ValueError("Plugin not built yet.")

    bundle_root = Path(plugin.build.output_path)
    server_js = bundle_root / "server.js"
    if not server_js.is_file():
        raise ValueError("server.js not found in plugin output. Rebuild the plugin.")

    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js not found on this machine.")

    cmd = [node, str(server_js), "--run-skill", skill_slug, "--inputs", json.dumps(inputs)]
    if not headless:
        cmd.append("--no-headless")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(bundle_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Skill execution timed out after {timeout_s}s.")

    raw = stdout.decode().strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    err = stderr.decode().strip()
    raise RuntimeError(err or "Execution produced no output.")
