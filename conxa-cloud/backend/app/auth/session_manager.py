"""Auth session lifecycle manager.

Decouples authentication from automation assets:
- Session state lives in auth/auth.json (outside plugin files, not in git)
- validate_session() navigates to protected_url and checks we're still authed
- is_session_expired() is a lightweight check without full navigation
- Sessions are plugin-scoped: each plugin has its own auth state

Auth state format (Playwright storageState):
  {cookies: [...], origins: [...]}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page

from app.config import settings

_CONXA_HOME = Path.home() / ".conxa"


def auth_json_path(plugin_slug: str) -> Path:
    return _CONXA_HOME / "plugins" / plugin_slug / "auth" / "auth.json"


def has_saved_session(plugin_slug: str) -> bool:
    return auth_json_path(plugin_slug).exists()


def load_session_state(plugin_slug: str) -> dict[str, Any] | None:
    p = auth_json_path(plugin_slug)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def save_session_state(plugin_slug: str, state: dict[str, Any]) -> None:
    p = auth_json_path(plugin_slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def clear_session(plugin_slug: str) -> None:
    p = auth_json_path(plugin_slug)
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass


async def validate_session(
    context: BrowserContext,
    plugin_slug: str,
    protected_url: str,
    *,
    login_url_fragment: str = "login",
    timeout_ms: int = 10_000,
) -> dict[str, Any]:
    """Check if the current browser context is authenticated.

    Navigates to protected_url and verifies we are NOT redirected to a login page.
    Returns {authenticated: bool, page_url: str, reason: str}.
    """
    if not protected_url:
        return {"authenticated": True, "page_url": "", "reason": "no_protected_url_configured"}

    page: Page = await context.new_page()
    try:
        await page.goto(protected_url, wait_until="domcontentloaded", timeout=timeout_ms)
        final_url = page.url
        # If we ended up on a login page, session has expired
        if login_url_fragment and login_url_fragment.lower() in final_url.lower():
            return {
                "authenticated": False,
                "page_url": final_url,
                "reason": f"redirected_to_login ({final_url})",
            }
        return {"authenticated": True, "page_url": final_url, "reason": "ok"}
    except Exception as exc:
        return {"authenticated": False, "page_url": "", "reason": str(exc)}
    finally:
        await page.close()


async def save_context_state(context: BrowserContext, plugin_slug: str) -> None:
    """Capture and persist the browser storage state after a successful execution."""
    state = await context.storage_state()
    save_session_state(plugin_slug, state)
