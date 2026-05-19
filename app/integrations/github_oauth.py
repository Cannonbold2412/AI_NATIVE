"""GitHub OAuth App integration.

Environment variables (no SKILL_ prefix — these are integration-specific):
  GITHUB_OAUTH_CLIENT_ID       — GitHub OAuth App client ID
  GITHUB_OAUTH_CLIENT_SECRET   — GitHub OAuth App client secret
  GITHUB_OAUTH_REDIRECT_URI    — defaults to http://localhost:8000/api/v1/integrations/github/callback
  GITHUB_OAUTH_FRONTEND_ORIGIN — origin passed to postMessage (defaults to http://localhost:3000)

Token storage: data/integrations/github/<workspace_id>.json
Tokens are stored base64-encoded. For production deployments, replace with
proper KMS / secrets manager encryption.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.db import db_get, db_set, db_delete


# ─────────────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────────────


def _client_id() -> str:
    return settings.github_oauth_client_id


def _client_secret() -> str:
    return settings.github_oauth_client_secret


def _redirect_uri() -> str:
    return settings.github_oauth_redirect_uri


def _frontend_origin() -> str:
    return settings.github_oauth_frontend_origin


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────


def _integrations_dir() -> Path:
    p = settings.data_dir / "integrations" / "github"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _token_path(workspace_id: str) -> Path:
    return _integrations_dir() / f"{workspace_id}.json"


# In-memory store for OAuth states (keyed by state token → workspace_id + expiry).
# A simple dict is fine for single-process local dev.
_pending_states: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


class GithubStatus(TypedDict):
    connected: bool
    login: str | None
    scopes: list[str] | None


def _read_token_data(workspace_id: str) -> dict | None:
    data = db_get("github_tokens", workspace_id)
    if data is not None:
        return data
    path = _token_path(workspace_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_status(workspace_id: str) -> GithubStatus:
    data = _read_token_data(workspace_id)
    if not data:
        return {"connected": False, "login": None, "scopes": None}
    return {"connected": True, "login": data.get("login"), "scopes": data.get("scopes", [])}


def get_token(workspace_id: str) -> str | None:
    data = _read_token_data(workspace_id)
    if not data:
        return None
    try:
        encoded = data.get("token_b64", "")
        if not encoded:
            return None
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return None


def start_oauth(workspace_id: str) -> str:
    """Return GitHub authorize URL. Side-effects: records pending state."""
    state = secrets.token_urlsafe(32)
    _pending_states[state] = {
        "workspace_id": workspace_id,
        "created_at": time.time(),
    }
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "scope": "repo read:user",
        "state": state,
    }
    qs = urlencode(params)
    return f"https://github.com/login/oauth/authorize?{qs}"


def handle_callback(code: str, state: str) -> dict:
    """Exchange code for token. Validates state, stores token, returns {login}."""
    pending = _pending_states.pop(state, None)
    if pending is None:
        raise ValueError("Invalid or expired OAuth state")
    if time.time() - pending["created_at"] > 600:
        raise ValueError("OAuth state expired")

    workspace_id: str = pending["workspace_id"]

    # Exchange code → token
    resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "code": code,
            "redirect_uri": _redirect_uri(),
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    token_data = resp.json()
    token = token_data.get("access_token", "")
    if not token:
        raise ValueError(f"GitHub did not return a token: {token_data.get('error_description', token_data)}")

    scope_str: str = token_data.get("scope", "")
    scopes = [s.strip() for s in scope_str.split(",") if s.strip()]

    # Fetch user login
    user_resp = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {token}", "Accept": "application/json"},
        timeout=10,
    )
    user_resp.raise_for_status()
    login: str = user_resp.json().get("login", "")

    # Persist
    token_data = {
        "workspace_id": workspace_id,
        "token_b64": base64.b64encode(token.encode()).decode(),
        "login": login,
        "scopes": scopes,
        "connected_at": time.time(),
    }
    db_set("github_tokens", workspace_id, token_data)
    try:
        path = _token_path(workspace_id)
        path.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    except OSError:
        pass

    return {"login": login, "scopes": scopes}


def revoke(workspace_id: str) -> None:
    """Remove local token record. Token revocation on GitHub is left to the user."""
    db_delete("github_tokens", workspace_id)
    path = _token_path(workspace_id)
    if path.is_file():
        path.unlink()
