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


def _runtime_exe(path: Path) -> Path | None:
    """Return the packed runtime executable in ``path``, or None.

    The customer installer stages it as ``runtime.exe``; the Studio deps bootstrap
    caches it as ``runtime-win.exe``. Either is a self-contained MCP stdio server.
    """
    names = ("runtime.exe", "runtime-win.exe") if sys.platform == "win32" else ("runtime", "runtime-mac")
    for name in names:
        exe = path / name
        if exe.is_file():
            return exe
    return None


def _is_runtime_dir(path: Path) -> bool:
    """A runnable runtime is either a packed exe or a server.js source tree."""
    if _runtime_exe(path) is not None:
        return True
    return (path / "server.js").is_file() and (path / "package.json").is_file()


def _bootstrap_runtime_dir() -> Path | None:
    """Locate the Studio deps-managed runtime (~/.conxa/deps/runtime/<version>/).

    Mirrors services.bootstrap._deps_dir(); kept inline so this module stays
    dependency-free. Returns the highest-versioned dir that holds a packed exe.
    """
    base = os.environ.get("SKILL_DATA_DIR") or os.path.expanduser("~/.conxa")
    runtime_root = Path(base) / "deps" / "runtime"
    if not runtime_root.is_dir():
        return None
    candidates = [d for d in runtime_root.iterdir() if d.is_dir() and _runtime_exe(d) is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda d: d.name)
    return candidates[-1]


def resolve_runtime_dir() -> Path | None:
    """Find a runnable Conxa runtime directory (packed exe or server.js tree).

    Priority:
      1. $CONXA_DIR env var (explicit override — trusted as-is)
      2. $CONXA_RUNTIME_LOCAL_DIR env var (selected by bootstrap)
      3. Studio deps-managed runtime (~/.conxa/deps/runtime/<version>/)

    Returns None if no valid runtime is found.
    """
    env_dir = os.environ.get("CONXA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir)
        if _is_runtime_dir(p):
            return p

    local_dir = os.environ.get("CONXA_RUNTIME_LOCAL_DIR", "").strip()
    if local_dir:
        p = Path(local_dir)
        if _is_runtime_dir(p):
            return p

    deps_runtime = _bootstrap_runtime_dir()
    if deps_runtime is not None:
        return deps_runtime

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
    """Call a tool on the local MCP stdio runtime and return its JSON-RPC result.

    Launches the packed runtime executable when present (production parity with
    how Claude Desktop spawns it); otherwise falls back to ``node server.js`` for
    a repo-local source tree (dev).
    """
    exe = _runtime_exe(runtime_dir)
    if exe is not None:
        cmd: list[str] = [str(exe)]
    else:
        node = shutil.which("node")
        if not node:
            raise RuntimeToolError("Node.js not found. Install Node.js to test workflows.")
        if not (runtime_dir / "server.js").is_file():
            raise RuntimeToolError(
                f"No runnable runtime at {runtime_dir} (neither a packed executable nor server.js)."
            )
        cmd = [node, "server.js"]

    proc_env = {
        **os.environ,
        **(env or {}),
        "CONXA_DIR": str(runtime_dir),
        "CONXA_SKIP_SELF_UPDATE": os.environ.get("CONXA_SKIP_SELF_UPDATE", "1"),
    }

    proc = subprocess.Popen(
        cmd,
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
