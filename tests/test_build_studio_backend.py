"""Phase 2: Build Studio stdio backend dispatcher + input sanitization."""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_PY_DIR = os.path.join(os.path.dirname(__file__), "..", "conxa-builder", "python")
sys.path.insert(0, os.path.abspath(_PY_DIR))


@pytest.fixture()
def backend():
    spec = importlib.util.spec_from_file_location(
        "cbackend", os.path.join(_PY_DIR, "backend.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out: list[dict] = []
    mod._write = lambda obj: out.append(obj)  # capture protocol output
    b = mod.Backend()
    return b, out


def _last(out):
    return out[-1]


def test_ping(backend):
    b, out = backend
    b.dispatch({"id": "1", "type": "ping", "payload": {}})
    assert _last(out)["type"] == "result"
    assert _last(out)["result"]["ok"] is True


def test_unknown_command(backend):
    b, out = backend
    b.dispatch({"id": "2", "type": "frobnicate", "payload": {}})
    assert _last(out)["type"] == "error"
    assert _last(out)["code"] == "unknown_command"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "a\\b", "x\x00y", ""])
def test_path_traversal_rejected(backend, bad):
    b, out = backend
    b.dispatch({"id": "3", "type": "stop_recording", "payload": {"session_id": bad}})
    assert _last(out)["type"] == "error"
    assert _last(out)["code"] == "invalid_input"


def test_missing_plugin_reported(backend):
    b, out = backend
    b.dispatch({"id": "4", "type": "list_workflows", "payload": {"plugin_id": "ghost"}})
    assert _last(out)["type"] == "error"
    assert _last(out)["code"] == "plugin_not_found"


def test_validation_module():
    from services.validation import InvalidInput, safe_identifier

    assert safe_identifier("skill_abc-123", "x") == "skill_abc-123"
    for bad in ["../etc", "a/b", "a\\b", "x\x00y", "  "]:
        with pytest.raises(InvalidInput):
            safe_identifier(bad, "x")


def test_proxy_router_injection_swaps_singleton(backend, monkeypatch):
    b, _out = backend
    monkeypatch.setenv("CONXA_CLERK_DOMAIN", "https://clerk.example.com")
    monkeypatch.setenv("CONXA_CLERK_CLIENT_ID", "client_x")

    b._install_proxy_router()
    import app.llm.router as router_mod
    from services.llm_proxy_client import LLMProxyClient

    assert isinstance(router_mod.get_router(), LLMProxyClient)
