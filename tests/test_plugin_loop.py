"""Tests for the execution loop runner (no real browser needed)."""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.plugin_test.common import Bundle, dump_json, load_json
from scripts.plugin_test.loop_runner import run as loop_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_bundle(tmp_path: Path) -> Bundle:
    """Minimal valid bundle with one skill and a package.json."""
    skill_dir = tmp_path / "skills" / "test_skill"
    skill_dir.mkdir(parents=True)

    execution = [
        {"type": "navigate", "url": "https://example.com"},
        {"type": "click", "selector": "text=Sign in"},
        {"type": "fill", "selector": "input[name='email']", "value": "{{user_email}}"},
    ]
    recovery_data = {
        "steps": [
            {
                "step_id": 2,
                "target": {"text": "Sign in", "role": "button"},
                "selector_context": {
                    "primary": "text=Sign in",
                    "alternatives": ["[data-testid='signin-btn']"],
                },
                "anchors": [{"text": "Login", "priority": 1}],
                "fallback": {"text_variants": ["Sign in", "Log in"]},
            }
        ]
    }
    dump_json(skill_dir / "execution.json", execution)
    dump_json(skill_dir / "recovery.json", recovery_data)
    dump_json(skill_dir / "input.json", {"inputs": [{"name": "user_email", "type": "string"}]})
    (skill_dir / "manifest.json").write_text("{}", encoding="utf-8")

    (tmp_path / "execution").mkdir()
    (tmp_path / "execution" / "executor.js").write_text("// stub", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"test"}', encoding="utf-8")
    # Pre-create node_modules/playwright to skip npm install
    (tmp_path / "node_modules" / "playwright").mkdir(parents=True)

    inputs_file = tmp_path / "inputs.json"
    dump_json(inputs_file, {"user_email": "test@example.com"})

    return Bundle(name="test-plugin", root=tmp_path), inputs_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_result(skill: str, steps: list[dict]) -> dict:
    ok = sum(1 for s in steps if s["status"] == "ok")
    recovered = sum(1 for s in steps if s["status"] == "recovered")
    failed = sum(1 for s in steps if s["status"] == "failed")
    return {
        "skill": skill,
        "passed": failed == 0,
        "steps": steps,
        "summary": {"total": len(steps), "ok": ok, "recovered": recovered, "failed": failed},
    }


def _write_fake_result(result_path: Path, result: dict) -> MagicMock:
    """Return a side_effect function that writes result_path when called."""
    def side_effect(*args, **kwargs):
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        proc = MagicMock()
        proc.returncode = 0 if result["passed"] else 1
        proc.stdout = b""
        proc.stderr = b""
        return proc
    return side_effect


# ---------------------------------------------------------------------------
# Sandbox guard
# ---------------------------------------------------------------------------

def test_sandbox_guard_refuses_without_env(tmp_bundle):
    bundle, inputs_file = tmp_bundle
    env_without = {k: v for k, v in os.environ.items() if k != "CONXA_SANDBOX_ACK"}
    with patch.dict(os.environ, env_without, clear=True):
        result = loop_run(bundle, inputs_path=inputs_file)
    assert not result.passed
    assert "CONXA_SANDBOX_ACK" in result.details[0]


# ---------------------------------------------------------------------------
# All steps pass → loop exits after 1 iteration
# ---------------------------------------------------------------------------

def test_loop_exits_on_first_pass(tmp_bundle, monkeypatch):
    bundle, inputs_file = tmp_bundle
    monkeypatch.setenv("CONXA_SANDBOX_ACK", "1")

    steps = [
        {"step": 1, "type": "navigate", "selector": "", "status": "ok", "latency_ms": 100},
        {"step": 2, "type": "click", "selector": "text=Sign in", "status": "ok", "latency_ms": 200},
        {"step": 3, "type": "fill", "selector": "input[name='email']", "status": "ok", "latency_ms": 150},
    ]
    fake = _fake_result("test_skill", steps)
    result_path = bundle.root / "EXECUTION_RESULT.json"

    with patch("subprocess.run", side_effect=_write_fake_result(result_path, fake)):
        result = loop_run(bundle, inputs_path=inputs_file, max_iters=5)

    assert result.passed
    assert result.extras["iterations"] == 1
    assert result.score == 10


# ---------------------------------------------------------------------------
# Recovered selector gets promoted in execution.json
# ---------------------------------------------------------------------------

def test_autofix_promotes_recovered_selector(tmp_bundle, monkeypatch):
    bundle, inputs_file = tmp_bundle
    monkeypatch.setenv("CONXA_SANDBOX_ACK", "1")
    skill_dir = bundle.root / "skills" / "test_skill"

    steps_iter1 = [
        {"step": 1, "type": "navigate", "selector": "", "status": "ok", "latency_ms": 100},
        {"step": 2, "type": "click", "selector": "text=Sign in", "status": "recovered",
         "recovered_via": "[data-testid='signin-btn']", "latency_ms": 300},
        {"step": 3, "type": "fill", "selector": "input[name='email']", "status": "ok", "latency_ms": 150},
    ]
    steps_iter2 = [
        {"step": 1, "type": "navigate", "selector": "", "status": "ok", "latency_ms": 100},
        {"step": 2, "type": "click", "selector": "[data-testid='signin-btn']", "status": "ok", "latency_ms": 200},
        {"step": 3, "type": "fill", "selector": "input[name='email']", "status": "ok", "latency_ms": 150},
    ]
    fake1 = _fake_result("test_skill", steps_iter1)
    fake2 = _fake_result("test_skill", steps_iter2)

    call_count = 0
    result_path = bundle.root / "EXECUTION_RESULT.json"

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        data = fake1 if call_count == 1 else fake2
        result_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        proc = MagicMock()
        proc.returncode = 0 if data["passed"] else 1
        proc.stdout = b""
        proc.stderr = b""
        return proc

    with patch("subprocess.run", side_effect=side_effect):
        result = loop_run(bundle, inputs_path=inputs_file, max_iters=5, autofix=True)

    # After iteration 1 the promoted selector should be in execution.json
    execution = load_json(skill_dir / "execution.json")
    assert execution[1]["selector"] == "[data-testid='signin-btn']"

    # Old primary should appear in recovery alternatives
    recovery = load_json(skill_dir / "recovery.json")
    rec_step = next(e for e in recovery["steps"] if e["step_id"] == 2)
    assert "text=Sign in" in rec_step["selector_context"]["alternatives"]

    assert result.passed
    # Loop exits after iteration 1 because the run passed (recovered = still passed)
    assert result.extras["iterations"] == 1


# ---------------------------------------------------------------------------
# No autofix — files unchanged after a recovered iteration
# ---------------------------------------------------------------------------

def test_no_autofix_leaves_files_unchanged(tmp_bundle, monkeypatch):
    bundle, inputs_file = tmp_bundle
    monkeypatch.setenv("CONXA_SANDBOX_ACK", "1")
    skill_dir = bundle.root / "skills" / "test_skill"

    original_execution = load_json(skill_dir / "execution.json")

    steps = [
        {"step": 1, "type": "navigate", "selector": "", "status": "ok", "latency_ms": 100},
        {"step": 2, "type": "click", "selector": "text=Sign in", "status": "recovered",
         "recovered_via": "[data-testid='signin-btn']", "latency_ms": 300},
        {"step": 3, "type": "fill", "selector": "input[name='email']", "status": "ok", "latency_ms": 150},
    ]
    fake = _fake_result("test_skill", steps)
    # Make it look like it never passes so loop runs max iters
    fake["passed"] = False
    result_path = bundle.root / "EXECUTION_RESULT.json"

    with patch("subprocess.run", side_effect=_write_fake_result(result_path, fake)):
        loop_run(bundle, inputs_path=inputs_file, max_iters=2, autofix=False)

    assert load_json(skill_dir / "execution.json") == original_execution


# ---------------------------------------------------------------------------
# Loop stops at max_iters
# ---------------------------------------------------------------------------

def test_loop_stops_at_max_iters(tmp_bundle, monkeypatch):
    bundle, inputs_file = tmp_bundle
    monkeypatch.setenv("CONXA_SANDBOX_ACK", "1")

    steps = [
        {"step": 1, "type": "navigate", "selector": "", "status": "ok", "latency_ms": 100},
        {"step": 2, "type": "click", "selector": "text=Sign in", "status": "failed",
         "error": "Timeout waiting for selector", "latency_ms": 5000},
    ]
    fake = _fake_result("test_skill", steps)
    result_path = bundle.root / "EXECUTION_RESULT.json"

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result_path.write_text(json.dumps(fake, indent=2), encoding="utf-8")
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = b""
        proc.stderr = b""
        return proc

    with patch("subprocess.run", side_effect=side_effect):
        result = loop_run(bundle, inputs_path=inputs_file, max_iters=3)

    assert call_count == 3
    assert not result.passed
    assert result.extras["iterations"] == 3


# ---------------------------------------------------------------------------
# EXECUTION_LOOP.md is written with iteration table
# ---------------------------------------------------------------------------

def test_report_written(tmp_bundle, monkeypatch):
    bundle, inputs_file = tmp_bundle
    monkeypatch.setenv("CONXA_SANDBOX_ACK", "1")

    steps = [
        {"step": 1, "type": "navigate", "selector": "", "status": "ok", "latency_ms": 80},
        {"step": 2, "type": "click", "selector": "text=Sign in", "status": "ok", "latency_ms": 120},
        {"step": 3, "type": "fill", "selector": "input[name='email']", "status": "ok", "latency_ms": 90},
    ]
    fake = _fake_result("test_skill", steps)
    result_path = bundle.root / "EXECUTION_RESULT.json"

    with patch("subprocess.run", side_effect=_write_fake_result(result_path, fake)):
        loop_run(bundle, inputs_path=inputs_file, max_iters=1)

    report_path = bundle.root / "EXECUTION_LOOP.md"
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Iteration 1" in content
    assert "PASS" in content
