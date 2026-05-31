"""Locate the installed Conxa shared runtime and stage skill-pack data into it."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


class RuntimeToolError(RuntimeError):
    """Raised when the local MCP runtime cannot complete a tool call."""


def _is_runtime_dir(path: Path) -> bool:
    return (path / "server.js").is_file() and (path / "package.json").is_file()


def _dev_runtime_candidates(source_file: Path) -> list[Path]:
    """Return repo-local runtime candidates for both standalone and monorepo layouts."""
    resolved = source_file.resolve()
    candidates: list[Path] = []
    seen: set[Path] = set()

    for parent in resolved.parents:
        candidate = parent / "runtime"
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    return candidates


def resolve_runtime_dir() -> Path | None:
    """Find the Conxa shared runtime directory containing server.js.

    Priority:
      1. $CONXA_DIR env var (explicit override — trusted as-is)
      2. Installed location (C:\\Program Files\\Conxa on Windows, ~/.conxa on Mac/Linux)
      3. Repo-local runtime/ (dev fallback; supports nested builder checkout)

    Returns None if no valid runtime is found.
    """
    # 1. Explicit env override
    env_dir = os.environ.get("CONXA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir)
        if (p / "server.js").is_file():
            return p

    # 2. Installed location
    if sys.platform == "win32":
        installed = Path(r"C:\Program Files\Conxa")
    else:
        installed = Path.home() / ".conxa"
    if (installed / "server.js").is_file():
        return installed

    # 3. Repo-local dev fallback
    for dev in _dev_runtime_candidates(Path(__file__)):
        if _is_runtime_dir(dev):
            return dev

    return None


def resolve_conxa_data_dir() -> Path:
    """Resolve CONXA_DATA_DIR (user-writable; mirrors runtime/server.js logic)."""
    env_dir = os.environ.get("CONXA_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "Conxa"
    return Path.home() / ".conxa"


def sync_skill_pack(
    company: str,
    source_dir: Path,
    runtime_dir: Path,
    *,
    data_dir: Path | None = None,
) -> None:
    """Copy source_dir → <runtime_dir>/skill-packs/<company>/, then bust the manifest cache.

    The runtime caches skill index in CONXA_DATA_DIR/cache/manifests.json for fast startup.
    Deleting that file forces a fresh filesystem scan so the newly synced skill is visible.

    No-op if source_dir doesn't exist.
    """
    if not source_dir.is_dir():
        return

    dest = runtime_dir / "skill-packs" / company
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(source_dir), str(dest), dirs_exist_ok=True)

    # Bust the skill manifest cache so the spawned runtime rescans from disk
    cache_file = (data_dir or resolve_conxa_data_dir()) / "cache" / "manifests.json"
    if cache_file.is_file():
        try:
            cache_file.unlink()
        except OSError:
            pass


def ensure_chromium_installed(
    browsers_dir: Path,
    runtime_dir: Path,
    log_sink=None,
) -> None:
    """Install Playwright Chromium into browsers_dir if not already present.

    browsers_dir is where server.js will look (CONXA_DIR/chromium).
    Runs `npx playwright install chromium` inside runtime_dir with the
    correct PLAYWRIGHT_BROWSERS_PATH override.  No-op if already installed.
    """
    import shutil as _shutil

    # Consider it installed if there is at least one chromium-* subdirectory
    if browsers_dir.is_dir() and any(
        d.is_dir() and d.name.startswith("chromium-")
        for d in browsers_dir.iterdir()
    ):
        return

    node = _shutil.which("node")
    npx = _shutil.which("npx")
    if not npx or not node:
        raise RuntimeError("Node.js / npx not found. Install Node.js to continue.")

    if log_sink:
        log_sink("Installing Playwright Chromium for the test runtime (one-time setup)…")

    browsers_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir)}

    result = subprocess.run(
        [npx, "playwright", "install", "chromium"],
        cwd=str(runtime_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Playwright install failed:\n{result.stderr or result.stdout}"
        )


def call_runtime_tool(
    runtime_dir: Path,
    tool_name: str,
    arguments: dict,
    *,
    env: dict[str, str] | None = None,
    timeout_s: int = 900,
) -> dict:
    """Call a tool on the local MCP stdio runtime and return its JSON-RPC result."""
    node = shutil.which("node")
    if not node:
        raise RuntimeToolError("Node.js not found. Install Node.js to test workflows.")

    server_js = runtime_dir / "server.js"
    if not server_js.is_file():
        raise RuntimeToolError(f"Runtime server.js not found at {server_js}")

    proc_env = {
        **os.environ,
        **(env or {}),
        "CONXA_DIR": str(runtime_dir),
        "CONXA_SKIP_SELF_UPDATE": os.environ.get("CONXA_SKIP_SELF_UPDATE", "1"),
    }

    proc = subprocess.Popen(
        [node, "server.js"],
        cwd=str(runtime_dir),
        env=proc_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_q: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []

    def _read_stdout() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout_q.put(line)
        finally:
            stdout_q.put(None)

    def _read_stderr() -> None:
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                line = line.strip()
                if line:
                    stderr_lines.append(line)
                    del stderr_lines[:-20]
        except Exception:
            pass

    threading.Thread(target=_read_stdout, daemon=True).start()
    threading.Thread(target=_read_stderr, daemon=True).start()

    next_id = 1

    def _send(method: str, params: dict) -> int:
        nonlocal next_id
        req_id = next_id
        next_id += 1
        if proc.stdin is None:
            raise RuntimeToolError("Runtime stdin is not available.")
        proc.stdin.write(
            json_dumps(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": method,
                    "params": params,
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        return req_id

    def _wait_response(req_id: int, deadline: float) -> dict:
        while time.monotonic() < deadline:
            try:
                line = stdout_q.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                message = json_loads(line)
            except ValueError:
                continue
            if message.get("id") == req_id:
                if "error" in message:
                    err = message.get("error") or {}
                    raise RuntimeToolError(str(err.get("message") or err))
                return message
        tail = "\n".join(stderr_lines[-5:])
        suffix = f"\nRuntime log tail:\n{tail}" if tail else ""
        raise RuntimeToolError(f"Runtime tool call timed out or exited before responding.{suffix}")

    try:
        deadline = time.monotonic() + timeout_s
        init_id = _send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "conxa-build-studio", "version": "1.0.0"},
            },
        )
        _wait_response(init_id, deadline)

        call_id = _send(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        response = _wait_response(call_id, deadline)
        return dict(response.get("result") or {})
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def json_dumps(value: dict) -> str:
    import json

    return json.dumps(value, ensure_ascii=True)


def json_loads(value: str) -> dict:
    import json

    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}
