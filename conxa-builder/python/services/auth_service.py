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

_CALLBACK_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Conxa — {title}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    height: 100%;
    background: #0a0c0f;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #e4e4e7;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .card {{
    width: min(420px, calc(100vw - 3rem));
    background: #0d0f12;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 2.5rem 2rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.25rem;
    box-shadow: 0 24px 48px rgba(0,0,0,0.6);
  }}
  .wordmark {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    color: #a1a1aa;
    margin-bottom: 0.25rem;
  }}
  .wordmark-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #3b82f6;
  }}
  .icon-wrap {{
    width: 56px;
    height: 56px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: {icon_bg};
  }}
  h1 {{
    font-size: 1.2rem;
    font-weight: 600;
    color: #f4f4f5;
    text-align: center;
  }}
  .subtitle {{
    font-size: 0.83rem;
    color: #71717a;
    text-align: center;
    line-height: 1.5;
  }}
  .countdown {{
    font-size: 0.75rem;
    color: #3f3f46;
    margin-top: 0.25rem;
  }}
  .divider {{
    width: 100%;
    height: 1px;
    background: rgba(255,255,255,0.06);
  }}
</style>
{auto_close_script}
</head>
<body>
<div class="card">
  <div class="wordmark">
    <span class="wordmark-dot"></span>
    Conxa
  </div>
  <div class="icon-wrap">
    {icon_svg}
  </div>
  <h1>{title}</h1>
  <p class="subtitle">{subtitle}</p>
  <div class="divider"></div>
  <p class="countdown" id="cd">{countdown_text}</p>
</div>
</body>
</html>"""

_SUCCESS_ICON = """<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M6 14.5L11.5 20L22 8" stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_ERROR_ICON = """<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8 8L20 20M20 8L8 20" stroke="#f87171" stroke-width="2.5" stroke-linecap="round"/>
</svg>"""

_AUTO_CLOSE_SCRIPT = """\
<script>
  var s = 4;
  function tick() {
    s--;
    var el = document.getElementById('cd');
    if (el) el.textContent = 'Closing in ' + s + 's…';
    if (s <= 0) { window.close(); }
    else { setTimeout(tick, 1000); }
  }
  setTimeout(tick, 1000);
</script>"""


def _build_callback_html(success: bool, message: str) -> bytes:
    if success:
        return _CALLBACK_HTML.format(
            title="Signed in successfully",
            icon_bg="rgba(74,222,128,0.1)",
            icon_svg=_SUCCESS_ICON,
            subtitle="You can close this window and return to Build Studio.",
            countdown_text="Closing in 4s…",
            auto_close_script=_AUTO_CLOSE_SCRIPT,
        ).encode()
    return _CALLBACK_HTML.format(
        title="Authentication failed",
        icon_bg="rgba(248,113,113,0.1)",
        icon_svg=_ERROR_ICON,
        subtitle=message,
        countdown_text="You can close this window.",
        auto_close_script="",
    ).encode()


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
        client_secret: str = "",
        cloud_api: str = "",
    ) -> None:
        self._clerk_domain = clerk_domain.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
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
        if not self._clerk_domain or not self._client_id:
            raise RuntimeError("auth_not_configured")
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
                # Ignore everything except the actual OAuth callback path.
                if parsed.path != "/cb":
                    self.send_response(204)
                    self.end_headers()
                    return
                params = urllib.parse.parse_qs(parsed.query)
                code = (params.get("code") or [""])[0]
                got_state = (params.get("state") or [""])[0]
                error = (params.get("error") or [""])[0]
                error_desc = (params.get("error_description") or [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                if code and got_state == state:
                    self.wfile.write(_build_callback_html(True, "Signed in to Conxa"))
                    result["code"] = code
                elif error:
                    msg = f"{error}: {error_desc}" if error_desc else error
                    result["error"] = msg
                    self.wfile.write(_build_callback_html(False, msg))
                else:
                    result["error"] = "state_mismatch"
                    self.wfile.write(_build_callback_html(False, "Login failed: state mismatch."))
                done.set()

        # Use a fixed port range so the redirect_uri can be pre-registered in Clerk.
        # Random ports can never be pre-registered; Clerk requires an exact URI match.
        _BASE_PORT = int(os.environ.get("CONXA_AUTH_PORT", "52741"))
        server = None
        for _p in range(_BASE_PORT, _BASE_PORT + 10):
            try:
                server = HTTPServer(("127.0.0.1", _p), Handler)
                break
            except OSError:
                continue
        if server is None:
            raise RuntimeError("auth_port_unavailable")
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/cb"

        authorize = (
            f"{self._clerk_domain}/oauth/authorize?"
            + urllib.parse.urlencode(
                {
                    "response_type": "code",
                    "client_id": self._client_id,
                    "redirect_uri": redirect_uri,
                    "scope": "profile email offline_access user:org:read",
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
            raise RuntimeError(result.get("error") or "login_timeout_or_cancelled")

        tokens = self._exchange_code(result["code"], verifier, redirect_uri)
        tokens["userinfo"] = self._fetch_userinfo_with_retry(tokens["access_token"])
        self._save(tokens)
        return self._claims(tokens)

    def _exchange_code(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        params: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        if self._client_secret:
            params["client_secret"] = self._client_secret
        body = urllib.parse.urlencode(params).encode()
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
        # Cloudflare sits in front of clerk.conxa.in and blocks requests with
        # Python's default user-agent. Mimic a real browser so CF passes it through.
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36",
        )
        req.add_header("Accept", "application/json, */*")
        req.add_header("Accept-Language", "en-US,en;q=0.9")
        req.add_header("Origin", self._clerk_domain)
        req.add_header("Referer", f"{self._clerk_domain}/")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = b""
            try:
                raw = exc.read()
            except Exception:
                pass
            body_text = raw.decode("utf-8", errors="replace")
            try:
                err_json = json.loads(body_text)
                clerk_error = err_json.get("error", "")
                clerk_desc = err_json.get("error_description", body_text[:300])
                raise RuntimeError(f"clerk_token_error: {clerk_error}: {clerk_desc}") from exc
            except (ValueError, AttributeError):
                snippet = body_text[:300] or "(empty body)"
                raise RuntimeError(f"clerk_token_http_{exc.code}: {snippet}") from exc
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

    def _fetch_userinfo_with_retry(self, access_token: str) -> dict[str, Any]:
        """Fetch userinfo, retrying once after a short delay.

        The freshly-issued access token sometimes isn't propagated through
        Clerk's backend by the time we immediately call /oauth/userinfo.
        A 1-second pause + one retry handles that race without user impact.
        """
        _KEEP = ("sub", "email", "name", "full_name", "org_id")
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                raw = self._fetch_userinfo(access_token)
                # Only keep the fields we need — Windows Credential Manager
                # has a 2500-byte limit; the full userinfo response exceeds it.
                return {k: raw.get(k) for k in _KEEP}
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(1)
        import sys
        print(f"[auth] userinfo fetch failed after retry: {last_exc}", file=sys.stderr)
        return {}

    def _fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        url = f"{self._clerk_domain}/oauth/userinfo"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36",
        )
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _claims(self, tokens: dict[str, Any]) -> dict[str, Any]:
        """Extract identity from cached userinfo or fall back to JWT decode."""
        userinfo = tokens.get("userinfo") or {}
        if userinfo:
            return {
                "org_id": userinfo.get("org_id"),
                "user_id": userinfo.get("sub"),
                "name": userinfo.get("name") or userinfo.get("full_name"),
                "email": userinfo.get("email"),
            }
        # Fallback: try to decode as JWT (Clerk may return JWTs on some plans)
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
