"""Playwright-backed recording session (Phase 1 — capture only, no execution)."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any

from playwright.sync_api import sync_playwright

from app.config import settings
from app.metrics.store import metrics
from app.models.events import RecordedEvent
from app.policy.bundle import get_policy_bundle
from app.policy.timing import resolve_event_timing
from app.recorder.visual import save_action_images


def _parse_url_state(raw: Any) -> dict[str, Any] | None:
    """Convert the bridge's url_state payload into the UrlStatePair dict structure."""
    if not raw or not isinstance(raw, dict):
        return None
    before = raw.get("before") or {}
    after = raw.get("after") or {}
    return {
        "before": {"url": str(before.get("url") or ""), "title": str(before.get("title") or "")},
        "after":  {"url": str(after.get("url") or ""), "title": str(after.get("title") or "")},
    }


_LOGIN_URL_PATTERNS = ("login", "signin", "sign-in", "auth", "sso", "oauth", "session/new", "account/login")


def classify_login_flow(events: list[RecordedEvent]) -> str:
    """Return 'login' if the event list looks like an auth recording, else 'workflow'.

    Heuristic: a login flow contains at least one password-type input interaction.
    URL patterns (e.g. /login) are a supporting signal but not required.
    """
    has_password_input = False
    has_login_url = False

    for event in events:
        # Check for password-type input
        input_type = str(event.semantic.input_type or "").lower()
        target_name = str(event.target.name or "").lower()
        if input_type == "password" or "password" in target_name:
            has_password_input = True

        # Check URL for login patterns
        url = str(event.page.url or "").lower()
        if any(marker in url for marker in _LOGIN_URL_PATTERNS):
            has_login_url = True

        if has_password_input:
            break

    if has_password_input:
        return "login"
    if has_login_url:
        return "login"
    return "workflow"


def format_startup_error(exc: Exception) -> str:
    """Normalize Playwright launch failures into concise user-facing text."""
    message = str(exc).strip() or exc.__class__.__name__
    if "Executable doesn't exist" in message:
        return (
            "Playwright browser binaries are missing. "
            "Run `.venv\\Scripts\\playwright install chromium` and restart the API server."
        )
    return message


def _load_bridge_script() -> str:
    here = Path(__file__).resolve().parent / "bridge.js"
    bridge = here.read_text(encoding="utf-8")
    profile = json.dumps(get_policy_bundle().data.get("capture_profile") or {})
    return f"window.__SKILL_CAPTURE_PROFILE__ = {profile};\n" + bridge


def _typing_target_key(event: RecordedEvent) -> tuple[str, str, str, str]:
    selectors = event.selectors
    semantic = event.semantic
    return (
        str(selectors.css or ""),
        str(selectors.xpath or ""),
        str(semantic.input_type or ""),
        str(event.page.url or ""),
    )


@dataclass
class RecordingSession:
    """
    Owns one browser context + page, drains in-page events into structured JSON.

    Threading: Playwright calls `expose_binding` from the driver thread; we forward
    payloads into an asyncio.Queue via call_soon_threadsafe for a single consumer.
    """

    session_id: str
    start_url: str = "about:blank"
    data_root: Path = field(default_factory=lambda: settings.data_dir)
    storage_state_path: str = ""  # if set, browser context is restored from this Playwright storage_state file
    storage_state_autosave_path: str = ""  # if set, periodically persist context storage_state while open
    _playwright: Any = None
    _browser: Any = None
    _context: Any = None
    _page: Any = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop_requested: threading.Event = field(default_factory=threading.Event)
    _startup_done: threading.Event = field(default_factory=threading.Event)
    _startup_error: str = ""
    _seq: int = 0
    _materialized: list[RecordedEvent] = field(default_factory=list)
    _pending_payloads: SimpleQueue = field(default_factory=SimpleQueue)
    _last_enqueue_at: float = 0.0
    _last_storage_state_save_at: float = 0.0
    binding_errors: list[str] = field(default_factory=list)
    browser_open: bool = False
    ended_by_user: bool = False
    wait_for_url: str = ""
    reached_wait_url: bool = False
    auth_mode: bool = False  # skip bridge/events — only capture storage state

    def _url_matches_wait_target(self, url: str) -> bool:
        if not self.wait_for_url or not url:
            return False
        # Exclude start URL and any query-param/fragment/sub-path variant of it
        # (e.g. login pages that append ?returnUrl=... before auth completes)
        start_base = self.start_url.split("?")[0].split("#")[0]
        if url.startswith(start_base):
            return False
        import re as _re
        prefix = _re.split(r"\{\{", self.wait_for_url, maxsplit=1)[0]
        return bool(prefix) and url.startswith(prefix)

    def _shutdown_playwright_sync(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._page = None

    def _autosave_storage_state_sync(self, *, force: bool = False) -> None:
        if not self.storage_state_autosave_path or self._context is None:
            return
        now = time.monotonic()
        if not force and now - self._last_storage_state_save_at < 2.0:
            return
        try:
            path = Path(self.storage_state_autosave_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(path))
            self._last_storage_state_save_at = now
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"storage_state_autosave_error: {exc!s}")

    async def start(self) -> None:
        self._stop_requested.clear()
        self._startup_done.clear()
        self._startup_error = ""
        self.browser_open = False
        self.ended_by_user = False
        self._thread = threading.Thread(target=self._run_sync_recorder, daemon=True)
        self._thread.start()

        while not self._startup_done.is_set():
            await asyncio.sleep(0.05)

        if self._startup_error:
            raise RuntimeError(self._startup_error)

    def _on_browser_disconnected(self) -> None:
        self.browser_open = False
        self.ended_by_user = True
        self._stop_requested.set()

    def _binding_sink_sync(self, source: Any, payload: dict[str, Any]) -> None:
        try:
            src_page = source.get("page") if isinstance(source, dict) else None
            self._pending_payloads.put((copy.deepcopy(payload), src_page))
            self._last_enqueue_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001 — recorder must never crash from page callback
            self.binding_errors.append(f"binding_error: {exc!s}")

    def _delete_visual_assets(self, session_dir: Path, event: RecordedEvent) -> None:
        visual = event.visual
        for rel in (visual.full_screenshot, visual.element_snapshot):
            if not rel:
                continue
            try:
                p = (session_dir / rel).resolve()
                p.unlink(missing_ok=True)
            except Exception:
                # Best effort cleanup; recorder should never fail due to file deletion.
                continue

    def _rewrite_events_jsonl(self, session_dir: Path) -> None:
        out = session_dir / "events.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for ev in self._materialized:
                f.write(json.dumps(ev.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _should_merge_typing(self, prev: RecordedEvent, curr: RecordedEvent) -> bool:
        if prev.action.action != "type" or curr.action.action != "type":
            return False
        return _typing_target_key(prev) == _typing_target_key(curr)

    def _consume_payload_sync(self, payload: dict[str, Any], src_page: Any | None = None) -> None:
        session_dir = self.data_root / "sessions" / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        page_for_visuals = src_page or self._page
        event = self._finalize_payload_sync(page_for_visuals, session_dir, payload)
        with self._lock:
            if self._materialized and self._should_merge_typing(self._materialized[-1], event):
                prev = self._materialized[-1]
                self._delete_visual_assets(session_dir, prev)
                self._materialized[-1] = event
            else:
                self._materialized.append(event)
        self._rewrite_events_jsonl(session_dir)
        metrics.inc("events_captured")

    def _finalize_payload_sync(self, page, session_dir: Path, payload: dict[str, Any]) -> RecordedEvent:
        self._seq += 1
        seq = self._seq
        vph = payload.get("visual_placeholder") or {}
        bbox = vph.get("bbox") or {"x": 0, "y": 0, "w": 0, "h": 0}
        full_rel, el_rel = save_action_images(
            page,
            session_dir,
            seq,
            bbox,
            jpeg_quality=settings.screenshot_jpeg_quality,
        )
        action = payload["action"]
        pol = get_policy_bundle().data
        action_name = str((action or {}).get("action") or "")
        timing = resolve_event_timing(action_name, pol)
        body = {
            "action": action,
            "target": payload["target"],
            "selectors": payload["selectors"],
            "context": payload["context"],
            "semantic": payload["semantic"],
            "anchors": payload.get("anchors") or [],
            "visual": {
                "full_screenshot": full_rel,
                "element_snapshot": el_rel,
                "bbox": bbox,
                "viewport": vph.get("viewport") or "",
                "scroll_position": vph.get("scroll_position") or "0,0",
            },
            "page": payload["page"],
            "state_change": payload.get("state_change") or {"before": "", "after": ""},
            "timing": timing,
            "extras": {"sequence": seq, "session_id": self.session_id},
            "url_state": _parse_url_state(payload.get("url_state")),
        }
        return RecordedEvent.model_validate(body)

    def _run_sync_recorder(self) -> None:
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )
            self.browser_open = True
            self._browser.on("disconnected", lambda _: self._on_browser_disconnected())
            ctx_kwargs: dict[str, Any] = {}
            if self.storage_state_path and Path(self.storage_state_path).is_file():
                ctx_kwargs["storage_state"] = self.storage_state_path
            self._context = self._browser.new_context(**ctx_kwargs)
            if not self.auth_mode:
                self._context.expose_binding("__skillReport", self._binding_sink_sync)
                self._context.add_init_script(_load_bridge_script())
            self._page = self._context.new_page()
            try:
                self._page.goto(self.start_url, wait_until="load", timeout=30000)
            except Exception as goto_err:
                self.binding_errors.append(f"navigation_error: {goto_err!s}")
            if not self.auth_mode:
                bridge_ok = self._page.evaluate("() => !!window.__SKILL_BRIDGE_V1__")
                binding_ok = self._page.evaluate("() => typeof window.__skillReport === 'function'")
                if not bridge_ok:
                    self.binding_errors.append("bridge_not_loaded_on_start_page")
                if not binding_ok:
                    self.binding_errors.append("binding_not_available_on_start_page")
            self._startup_done.set()

            while not self._stop_requested.is_set():
                # Pump the Playwright sync driver so binding callbacks are delivered
                # continuously while recording (not only around teardown calls).
                # Skip in auth_mode — no bridge callbacks to pump.
                if not self.auth_mode:
                    try:
                        if self._page and not self._page.is_closed():
                            self._page.evaluate("() => 0")
                    except Exception as exc:  # noqa: BLE001
                        self.binding_errors.append(f"pump_error: {exc!s}")
                self._autosave_storage_state_sync()
                if self.wait_for_url and not self.reached_wait_url:
                    try:
                        if self._page and not self._page.is_closed():
                            current_url = self._page.url
                            if self._url_matches_wait_target(current_url):
                                self._autosave_storage_state_sync(force=True)
                                self.reached_wait_url = True
                                self._stop_requested.set()
                    except Exception:  # noqa: BLE001
                        pass
                if not self.auth_mode:
                    try:
                        payload, src_page = self._pending_payloads.get_nowait()
                        self._consume_payload_sync(payload, src_page)
                    except Empty:
                        pass
                if not self._browser.is_connected() or self._page.is_closed():
                    self.ended_by_user = True
                    break
                time.sleep(0.2)

            if not self.auth_mode:
                # Stop waits for a short "idle queue" condition so delayed
                # Playwright binding callbacks can still be consumed.
                shutdown_start = time.monotonic()
                while True:
                    try:
                        if self._page and not self._page.is_closed():
                            self._page.evaluate("() => 0")
                    except Exception:
                        pass
                    drained = 0
                    try:
                        while True:
                            payload, src_page = self._pending_payloads.get_nowait()
                            drained += 1
                            self._consume_payload_sync(payload, src_page)
                    except Empty:
                        pass
                    elapsed = time.monotonic() - shutdown_start
                    idle_for = time.monotonic() - self._last_enqueue_at if self._last_enqueue_at else elapsed
                    if elapsed >= 5.0 and idle_for >= 1.0 and drained == 0:
                        break
                    time.sleep(0.05)
            self._autosave_storage_state_sync(force=True)
        except Exception as exc:  # noqa: BLE001
            self._startup_error = format_startup_error(exc)
            self.binding_errors.append(f"start_error: {exc!s}")
            self._startup_done.set()
        finally:
            self.browser_open = False
            self._shutdown_playwright_sync()

    async def stop(self) -> None:
        self._stop_requested.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self.browser_open = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            event_count = len(self._materialized)
        return {
            "session_id": self.session_id,
            "browser_open": self.browser_open,
            "event_count": event_count,
            "ended_by_user": self.ended_by_user,
            "binding_errors": self.binding_errors,
            "reached_wait_url": self.reached_wait_url,
        }

    def snapshot_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [e.model_dump(mode="json") for e in self._materialized]


class SessionRegistry:
    """In-memory MVP registry (swap for Redis/DB in production)."""

    def __init__(self) -> None:
        self._sessions: dict[str, RecordingSession] = {}

    def create(
        self,
        start_url: str = "about:blank",
        storage_state_path: str = "",
        storage_state_autosave_path: str = "",
        wait_for_url: str = "",
        auth_mode: bool = False,
    ) -> RecordingSession:
        sid = str(uuid.uuid4())
        sess = RecordingSession(
            session_id=sid,
            start_url=start_url,
            storage_state_path=storage_state_path,
            storage_state_autosave_path=storage_state_autosave_path,
            wait_for_url=wait_for_url,
            auth_mode=auth_mode,
        )
        self._sessions[sid] = sess
        return sess

    def get(self, session_id: str) -> RecordingSession | None:
        return self._sessions.get(session_id)

    def pop(self, session_id: str) -> RecordingSession | None:
        """Remove a session without stopping the browser (used on failed start)."""
        return self._sessions.pop(session_id, None)

    async def remove(self, session_id: str) -> bool:
        sess = self._sessions.get(session_id)
        if not sess:
            return False
        await sess.stop()
        return True


registry = SessionRegistry()
