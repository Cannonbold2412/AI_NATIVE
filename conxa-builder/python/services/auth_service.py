"""Clerk OAuth (PKCE) login + token storage for Build Studio.

Flow:
1. Spin up a localhost HTTP server on an OS-assigned port.
2. Open the system browser to Clerk's authorize URL with a PKCE challenge.
3. Catch the redirect, exchange the code for access + refresh tokens.
4. Store tokens in the OS credential manager via ``keyring`` (never plaintext).

Tokens are refreshed transparently when within 60s of expiry. ``get_token``
is what the LLM proxy client calls before each request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

_KEYRING_SERVICE = "conxa-studio"
_TOKEN_KEY = "session"
_REFRESH_LEEWAY_S = 60


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class AuthService:
    def __init__(
        self,
        clerk_domain: str,
        client_id: str,
        *,
        cloud_api: str = "",
    ) -> None:
        self._clerk_domain = clerk_domain.rstrip("/")
        self._client_id = client_id
        self._cloud_api = cloud_api.rstrip("/")
        self._lock = threading.RLock()

    # -- storage -------------------------------------------------------------

    def _keyring(self):
        import keyring  # imported lazily; only present on the desktop build

        return keyring

    def _load(self) -> dict[str, Any] | None:
        raw = self._keyring().get_password(_KEYRING_SERVICE, _TOKEN_KEY)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _save(self, tokens: dict[str, Any]) -> None:
        self._keyring().set_password(_KEYRING_SERVICE, _TOKEN_KEY, json.dumps(tokens))

    def logout(self) -> None:
        try:
            self._keyring().delete_password(_KEYRING_SERVICE, _TOKEN_KEY)
        except Exception:
            pass

    # -- login ---------------------------------------------------------------

    def login(self, *, on_event=None) -> dict[str, Any]:
        """Run the interactive PKCE login. Returns ``{org_id, user_id, ...}``."""
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        result: dict[str, Any] = {}
        done = threading.Event()

        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):  # silence default logging
                pass

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                code = (params.get("code") or [""])[0]
                got_state = (params.get("state") or [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                if code and got_state == state:
                    self.wfile.write(b"<h2>Conxa: you can close this window.</h2>")
                    result["code"] = code
                else:
                    self.wfile.write(b"<h2>Conxa: login failed.</h2>")
                done.set()

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/cb"

        authorize = (
            f"{self._clerk_domain}/oauth/authorize?"
            + urllib.parse.urlencode(
                {
                    "response_type": "code",
                    "client_id": self._client_id,
                    "redirect_uri": redirect_uri,
                    "scope": "openid profile email org",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        if on_event:
            on_event({"phase": "auth", "step": "browser_open"})
        webbrowser.open(authorize)

        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        done.wait(timeout=300)
        server.shutdown()

        if not result.get("code"):
            raise RuntimeError("login_timeout_or_cancelled")

        tokens = self._exchange_code(result["code"], verifier, redirect_uri)
        self._save(tokens)
        return self._claims(tokens)

    def _exchange_code(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }
        ).encode()
        return self._token_request(body)

    def _refresh(self, refresh_token: str) -> dict[str, Any]:
        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
            }
        ).encode()
        return self._token_request(body)

    def _token_request(self, body: bytes) -> dict[str, Any]:
        url = f"{self._clerk_domain}/oauth/token"
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        now = time.time()
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "exp": now + float(data.get("expires_in", 3600)),
        }

    # -- token access --------------------------------------------------------

    def get_token(self) -> str:
        """Return a valid access token, refreshing if near expiry. Raises if logged out."""
        with self._lock:
            tokens = self._load()
            if not tokens:
                raise RuntimeError("not_authenticated")
            if time.time() >= float(tokens.get("exp", 0)) - _REFRESH_LEEWAY_S:
                refresh = tokens.get("refresh_token")
                if not refresh:
                    raise RuntimeError("session_expired")
                tokens = self._refresh(refresh)
                self._save(tokens)
            return tokens["access_token"]

    def _claims(self, tokens: dict[str, Any]) -> dict[str, Any]:
        """Decode the JWT payload (no signature check — server verifies on use)."""
        try:
            payload_b64 = tokens["access_token"].split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        except (KeyError, IndexError, ValueError):
            return {}
        return {
            "org_id": claims.get("org_id") or claims.get("orgid"),
            "user_id": claims.get("sub"),
            "name": claims.get("name") or claims.get("full_name"),
            "email": claims.get("email"),
        }

    def current_identity(self) -> dict[str, Any] | None:
        tokens = self._load()
        return self._claims(tokens) if tokens else None
