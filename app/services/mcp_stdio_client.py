"""Minimal JSON-RPC 2.0 stdio client for the Conxa shared runtime.

Protocol: initialize → notifications/initialized → tools/call execute_skill.
Each message is one line of JSON on stdin; responses arrive on stdout (logs on stderr).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path


async def execute_skill_via_runtime(
    *,
    runtime_dir: Path,
    conxa_dir: Path,
    company: str,
    skill_slug: str,
    inputs: dict,
    headless: bool = True,
    timeout_s: int = 300,
    log_sink: Callable[[str], None] | None = None,
) -> dict:
    """Spawn node <runtime_dir>/server.js, execute one skill, return the result dict.

    Args:
        runtime_dir:  Directory containing server.js.
        conxa_dir:    Passed to the child as CONXA_DIR (determines where skill-packs/ lives).
        company:      Plugin bundle slug (= company slug in skill-packs/).
        skill_slug:   Workflow slug to execute.
        inputs:       User-provided inputs for the skill.
        headless:     False = open a visible browser.
        log_sink:     Receives runtime stderr lines for SSE log streaming.
        timeout_s:    Hard timeout in seconds.

    Raises RuntimeError on execution failure or timeout.
    """
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is not installed or not on PATH.")

    env = {**os.environ, "CONXA_DIR": str(conxa_dir)}

    proc = await asyncio.create_subprocess_exec(
        node, str(runtime_dir / "server.js"),
        env=env,
        cwd=str(runtime_dir),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=64 * 1024 * 1024,
    )

    try:
        return await asyncio.wait_for(
            _drive_mcp(
                proc,
                company=company,
                skill_slug=skill_slug,
                inputs=inputs,
                headless=headless,
                log_sink=log_sink,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Skill execution timed out after {timeout_s}s.")
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass


# ─── internal helpers ──────────────────────────────────────────────────────────

def _write(proc: asyncio.subprocess.Process, msg: dict) -> None:
    proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())


async def _read(
    proc: asyncio.subprocess.Process,
    log_sink: Callable[[str], None] | None = None,
) -> dict | None:
    try:
        line = await proc.stdout.readline()
    except ValueError as exc:
        if log_sink:
            log_sink(f"Runtime returned an oversized stdout frame: {exc}")
        return None
    except Exception as exc:
        if log_sink:
            log_sink(f"Runtime stdout read failed: {exc}")
        return None
    if not line:
        return None
    try:
        return json.loads(line.decode())
    except json.JSONDecodeError as exc:
        if log_sink:
            preview = line[:200].decode(errors="replace").strip()
            log_sink(f"Runtime returned non-JSON stdout: {preview} ({exc})")
        return None


async def _drain_stderr(
    proc: asyncio.subprocess.Process,
    log_sink: Callable[[str], None] | None,
) -> None:
    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        if log_sink:
            decoded = line.decode().rstrip()
            try:
                obj = json.loads(decoded)
                msg = str(obj.get("msg") or obj.get("message") or "")
                # Build a readable line from known extra fields
                extras = {k: v for k, v in obj.items() if k not in ("ts", "level", "msg", "message")}
                if msg == "execute_failed":
                    error = extras.get("error") or "unknown error"
                    skill = extras.get("skill") or ""
                    text = f"Execution failed{f' [{skill}]' if skill else ''}: {error}"
                elif msg == "execute_success":
                    skill = extras.get("skill") or ""
                    text = f"Execution succeeded{f' [{skill}]' if skill else ''}"
                elif msg == "skill_index_loaded":
                    count = extras.get("count")
                    text = f"Skill index loaded{f' ({count} skills)' if count is not None else ''}"
                elif extras:
                    parts = ", ".join(f"{k}={v}" for k, v in extras.items() if v)
                    text = f"{msg}: {parts}" if parts else msg
                else:
                    text = msg or decoded
            except Exception:
                text = decoded
            if text:
                log_sink(text)


async def _drive_mcp(
    proc: asyncio.subprocess.Process,
    *,
    company: str,
    skill_slug: str,
    inputs: dict,
    headless: bool,
    log_sink: Callable[[str], None] | None,
) -> dict:
    stderr_task = asyncio.create_task(_drain_stderr(proc, log_sink))

    try:
        # 1. Handshake
        _write(proc, {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "conxa-test", "version": "1.0.0"},
            },
        })
        await proc.stdin.drain()

        init_resp = await _read(proc, log_sink)
        if init_resp is None or init_resp.get("id") != 0:
            raise RuntimeError("MCP handshake failed — runtime did not respond to initialize.")
        if "error" in init_resp:
            raise RuntimeError(f"MCP initialize error: {init_resp['error']}")

        # 2. Initialized notification (no id — fire and forget)
        _write(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        await proc.stdin.drain()

        # 3. Execute the skill
        _write(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "execute_skill",
                "arguments": {
                    "skill": skill_slug,
                    "company": company,
                    "inputs": inputs,
                    "watch": not headless,
                },
            },
        })
        await proc.stdin.drain()

        # Read until we get the id=1 response (skip any unsolicited notifications)
        while True:
            resp = await _read(proc, log_sink)
            if resp is None:
                raise RuntimeError("Runtime closed the connection before returning a result.")
            if resp.get("id") == 1:
                break

        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(err.get("message", str(err)))

        result = resp.get("result", {})
        content = result.get("content") or []

        # Detect failure — runtime may set isError OR return a text block
        # starting with "Execution failed" without isError (from _buildFailureResponse).
        if result.get("isError"):
            first_text = content[0].get("text", "Execution failed") if content else "Execution failed"
            raise RuntimeError(first_text.split("\n")[0])

        if content and content[0].get("type") == "text":
            first_text = content[0].get("text", "")
            # Success always starts with "Done." (server.js line 583).
            # Any other text is a failure: auth error, selector error, etc.
            if not first_text.startswith("Done."):
                raise RuntimeError(first_text.split("\n")[0] or "Execution failed")
            try:
                return json.loads(first_text)
            except (json.JSONDecodeError, KeyError):
                return {"output": first_text}

        return {}

    finally:
        stderr_task.cancel()
        try:
            await stderr_task
        except asyncio.CancelledError:
            pass
        try:
            proc.stdin.close()
            await proc.stdin.wait_closed()
        except Exception:
            pass
