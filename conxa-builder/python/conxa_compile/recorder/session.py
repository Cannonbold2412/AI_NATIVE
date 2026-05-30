"""Playwright-backed recording session (Phase 1 — capture only, no execution)."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

if os.environ.get("SKILL_ENVIRONMENT") == "production" or os.environ.get("RENDER"):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

from playwright.sync_api import sync_playwright

from conxa_core.config import settings
from conxa_core.metrics.store import metrics
from conxa_core.models.events import RecordedEvent
from conxa_compile.policy.bundle import get_policy_bundle
from conxa_compile.policy.timing import resolve_event_timing
from conxa_compile.recorder.visual import save_action_images
from conxa_core.storage import snapshots as snapshot_store


_URL_DYNAMIC_SEG = re.compile(r"^(?:[0-9]+|[0-9a-f]{8,}|[A-Za-z0-9_-]{16,})$")
_URL_VOLATILE_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ts", "_", "t", "ref",
})


def _normalize_frame_url_pattern(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        host_part = re.escape(parsed.scheme + "://" + parsed.netloc)
        segments = parsed.path.split("/")
        normalized = [
            "[^/]+" if _URL_DYNAMIC_SEG.match(seg) else re.escape(seg)
            for seg in segments
        ]
        path_pattern = "/".join(normalized)
        qs = [(k, v) for k, v in parse_qsl(parsed.query) if k not in _URL_VOLATILE_PARAMS and not k.startswith("utm_")]
        query_suffix = ("\\?" + re.escape(urlencode(qs))) if qs else ""
        return f"^{host_part}{path_pattern}{query_suffix}$"
    except Exception:
        return ""


def _css_attr_selector(tag: str, attr: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'{tag}[{attr}="{escaped}"]'


def _iframe_selectors_from_attrs(attrs: dict[str, Any]) -> list[str]:
    selectors: list[str] = []
    for attr in ("id", "data-test-id", "data-selenium-test", "name", "title", "aria-label"):
        selector = _css_attr_selector("iframe", attr, attrs.get(attr))
        if selector and selector not in selectors:
            selectors.append(selector)
    return selectors


def _frame_parent(frame: Any) -> Any | None:
    parent = getattr(frame, "parent_frame", None)
    if callable(parent):
        try:
            return parent()
        except Exception:
            return None
    return parent


def _frame_url(frame: Any) -> str:
    raw = getattr(frame, "url", "")
    try:
        raw = raw() if callable(raw) else raw
    except Exception:
        return ""
    return str(raw or "")


def _frame_element_attrs_and_rect(frame: Any) -> tuple[dict[str, Any], dict[str, float]]:
    handle = frame.frame_element()
    attrs = handle.evaluate(
        """el => ({
          id: el.getAttribute("id") || "",
          "data-test-id": el.getAttribute("data-test-id") || "",
          "data-selenium-test": el.getAttribute("data-selenium-test") || "",
          name: el.getAttribute("name") || "",
          title: el.getAttribute("title") || "",
          "aria-label": el.getAttribute("aria-label") || "",
          src: el.getAttribute("src") || ""
        })"""
    )
    rect = handle.evaluate(
        """el => {
          const r = el.getBoundingClientRect();
          return { x: r.left || 0, y: r.top || 0, w: r.width || 0, h: r.height || 0 };
        }"""
    )
    return (
        attrs if isinstance(attrs, dict) else {},
        rect if isinstance(rect, dict) else {},
    )


def _frame_context_and_offset_sync(frame: Any | None) -> tuple[dict[str, Any], dict[str, float]]:
    if frame is None or _frame_parent(frame) is None:
        return {}, {"x": 0.0, "y": 0.0}

    frames: list[Any] = []
    cur = frame
    while cur is not None and _frame_parent(cur) is not None:
        frames.append(cur)
        cur = _frame_parent(cur)
    frames.reverse()

    chain: list[dict[str, Any]] = []
    offset = {"x": 0.0, "y": 0.0}
    for item in frames:
        try:
            attrs, rect = _frame_element_attrs_and_rect(item)
        except Exception:
            continue
        selectors = _iframe_selectors_from_attrs(attrs)
        if not selectors:
            continue
        frame_url = _frame_url(item)
        spec = {
            "selector": selectors[0],
            "fallback_selectors": selectors[1:],
            "url": frame_url or str(attrs.get("src") or ""),
            "url_pattern": _normalize_frame_url_pattern(frame_url),
        }
        chain.append(spec)
        try:
            offset["x"] += float(rect.get("x") or 0)
            offset["y"] += float(rect.get("y") or 0)
        except (TypeError, ValueError):
            pass

    return ({"chain": chain} if chain else {}), offset


def _viewport_string_from_page(page: Any) -> str:
    try:
        size = getattr(page, "viewport_size", None)
        size = size() if callable(size) else size
        if isinstance(size, dict):
            width = int(size.get("width") or 0)
            height = int(size.get("height") or 0)
            if width > 0 and height > 0:
                return f"{width}x{height}"
    except Exception:
        pass
    try:
        return str(page.evaluate("() => `${Math.round(window.innerWidth)}x${Math.round(window.innerHeight)}`") or "")
    except Exception:
        return ""


_LOGIN_URL_PATTERNS = ("login", "signin", "sign-in", "auth", "sso", "oauth", "session/new", "account/login")


def is_blank_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    return not value or value in {"about:blank", "chrome://newtab/"}


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
            "Run `python -m playwright install chromium` and restart the API server."
        )
    return message


def _load_bridge_script(*, capture_hover: bool = False) -> str:
    here = Path(__file__).resolve().parent / "bridge.js"
    bridge = here.read_text(encoding="utf-8")
    profile = json.dumps(get_policy_bundle().data.get("capture_profile") or {})
    options = json.dumps({"capture_hover": bool(capture_hover)})
    return (
        f"window.__SKILL_CAPTURE_PROFILE__ = {profile};\n"
        f"window.__SKILL_CAPTURE_OPTIONS__ = {options};\n"
        "window.__SKILL_TRACE__ = true;\n"
        + bridge
    )


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
    # Video recording is MANDATORY for non-auth sessions; no flag to disable.
    # auth_mode sessions are exempt (no video, no bridge, no events — see auth_mode field).
    _video_session_start: float = 0.0  # monotonic time when recording started; events.timestamp_ms is relative to this
    _video_session_start_wall_ms: int = 0  # wall-clock ms-since-epoch at video start (for ISO timestamp → relative ms conversion)
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
    _bridge_script: str = ""
    _bridge_install_error_keys: set[str] = field(default_factory=set)
    _frame_diag_seen: set[str] = field(default_factory=set)
    _traces: list[dict] = field(default_factory=list)
    _frame_snapshots: list[dict] = field(default_factory=list)
    _pump_tick: int = 0
    binding_errors: list[str] = field(default_factory=list)
    browser_open: bool = False
    ended_by_user: bool = False
    wait_for_url: str = ""
    reached_wait_url: bool = False
    auth_mode: bool = False  # skip bridge/events — only capture storage state
    capture_hover: bool = False
    current_url: str = ""
    # Phase 2: dedup state for DOM snapshots. Maps short bridge signature -> snapshot_ref.
    _snapshot_refs_by_sig: dict[str, str] = field(default_factory=dict)
    _last_snapshot_hash: str = ""
    _last_snapshot_ref: str = ""
    # A11y capture: one-strike degradation if slow (> 500ms).
    _last_a11y_capture_time: float = 0.0
    _a11y_skip_count: int = 0

    def _remember_current_url(self, url: str) -> None:
        value = str(url or "").strip()
        if not value or is_blank_url(value):
            return
        self.current_url = value

    def _remember_page_url_sync(self, page: Any | None) -> None:
        if page is None:
            return
        try:
            if page.is_closed():
                return
            self._remember_current_url(page.url)
        except Exception:  # noqa: BLE001
            pass

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
        self._finalize_video_recording_sync()

    def _finalize_video_recording_sync(self) -> None:
        """Rename Playwright's auto-generated .webm to recording.webm + extract frames.

        Auth-mode sessions are exempt (they don't record video). For non-auth
        sessions, missing video or frame-extraction failure raises — silent
        degradation is no longer allowed.
        """
        if self.auth_mode:
            return
        session_dir = self.data_root / "sessions" / self.session_id
        if not session_dir.is_dir():
            raise RuntimeError(f"session_dir missing at finalize: {session_dir}")

        target = session_dir / "recording.webm"
        webm_files = sorted(
            (p for p in session_dir.iterdir() if p.suffix == ".webm" and p.name != "recording.webm"),
            key=lambda p: p.stat().st_mtime,
        )
        if webm_files:
            latest = webm_files[-1]
            latest.replace(target)
        elif not target.is_file():
            raise RuntimeError(
                f"recording.webm not produced by Playwright in {session_dir}. "
                "Check that the browser context was launched with record_video_dir and the "
                "session closed cleanly via context.close()."
            )

        events_path = session_dir / "events.jsonl"
        if not events_path.is_file():
            with self._lock:
                event_count = len(self._materialized)
            if event_count == 0:
                self.binding_errors.append("video_frame_extraction_skipped:no_events")
                return
            raise FileNotFoundError(f"events.jsonl not found in {session_dir}")

        from conxa_compile.recorder.frame_extractor import extract_frames_for_session
        # Raises on missing ffmpeg, missing video, missing events, or per-frame failure.
        extract_frames_for_session(session_dir)

    def _compute_event_timestamp_ms(self, action: dict[str, Any]) -> int | None:
        """Convert ISO 8601 action.timestamp to ms offset from video start (None on parse error)."""
        ts_iso = str((action or {}).get("timestamp") or "")
        if not ts_iso:
            return None
        try:
            from datetime import datetime, timezone
            # Bridge.js produces e.g. "2025-02-15T14:32:10.123Z" — replace Z with +00:00 for fromisoformat
            iso_clean = ts_iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            wall_ms = int(dt.timestamp() * 1000)
            offset = wall_ms - self._video_session_start_wall_ms
            return max(0, offset)
        except (ValueError, TypeError):
            return None

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

    def _open_pages_sync(self) -> list[Any]:
        if self._context is None:
            return []
        try:
            return [page for page in self._context.pages if not page.is_closed()]
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"page_list_error: {exc!s}")
            return []

    def _active_page_sync(self) -> Any | None:
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    self._remember_page_url_sync(self._page)
                    return self._page
            except Exception:  # noqa: BLE001
                pass
        pages = self._open_pages_sync()
        if pages:
            self._page = pages[-1]
            self._remember_page_url_sync(self._page)
            return self._page
        return None

    def _remember_bridge_install_error(self, message: str) -> None:
        key = str(message or "").strip()[:240]
        if not key or key in self._bridge_install_error_keys:
            return
        self._bridge_install_error_keys.add(key)
        self.binding_errors.append(f"bridge_frame_install_error: {key}")

    def _ensure_bridge_installed_sync(self, page: Any) -> None:
        if self.auth_mode or not self._bridge_script or page is None:
            return
        try:
            if page.is_closed():
                return
        except Exception:  # noqa: BLE001
            return
        frames = []
        try:
            frames = list(getattr(page, "frames", []) or [])
        except Exception as exc:  # noqa: BLE001
            self._remember_bridge_install_error(str(exc))
            return
        for frame in frames:
            self._ensure_bridge_installed_in_frame_sync(frame)

    def _ensure_bridge_installed_in_frame_sync(self, frame: Any) -> None:
        if self.auth_mode or not self._bridge_script or frame is None:
            return
        try:
            # Check both window flag AND document flag. The window flag persists across
            # document.open() (HubSpot micro-frontend pattern) but the document flag does not.
            # If window says installed but document flag is gone, reset window so we re-inject.
            needs_install = frame.evaluate("""
                () => {
                    const hasWin = !!window.__SKILL_BRIDGE_V1__;
                    const hasDoc = !!(document && document.__SKILL_BRIDGE_DOC_V1__);
                    if (hasWin && !hasDoc) { window.__SKILL_BRIDGE_V1__ = false; }
                    return !(hasWin && hasDoc);
                }
            """)
            if needs_install:
                frame.evaluate(self._bridge_script)
            # Emit one diagnostic per unique frame URL so failures are visible.
            frame_url = _frame_url(frame)
            if frame_url and frame_url not in self._frame_diag_seen:
                self._frame_diag_seen.add(frame_url)
                try:
                    bridge_ok = frame.evaluate("() => !!window.__SKILL_BRIDGE_V1__")
                    binding_ok = frame.evaluate("() => typeof window.__skillReport === 'function'")
                    if not bridge_ok:
                        self.binding_errors.append(f"frame_bridge_missing:{frame_url}")
                    if not binding_ok:
                        self.binding_errors.append(f"frame_binding_missing:{frame_url}")
                except Exception:  # noqa: BLE001
                    self.binding_errors.append(f"frame_diag_error:{frame_url}")
        except Exception as exc:  # noqa: BLE001
            self._remember_bridge_install_error(str(exc))

    def _on_frame_ready(self, frame: Any) -> None:
        self._ensure_bridge_installed_in_frame_sync(frame)

    def _consume_payload_safe_sync(self, payload: dict[str, Any], src_page: Any | None = None) -> None:
        try:
            self._consume_payload_sync(payload, src_page)
        except Exception as exc:  # noqa: BLE001
            raw_action = payload.get("action") if isinstance(payload, dict) else {}
            action = str((raw_action or {}).get("action") or "")
            suffix = f":{action}" if action else ""
            self.binding_errors.append(f"event_capture_error{suffix}: {exc!s}")

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
            payload_copy = copy.deepcopy(payload)
            # Trace payloads go to the diagnostics list, not the event queue.
            if payload_copy.get("_trace"):
                if len(self._traces) < 5000:
                    self._traces.append(payload_copy)
                return
            src_page = source.get("page") if isinstance(source, dict) else None
            src_frame = source.get("frame") if isinstance(source, dict) else None
            frame_context, frame_offset = _frame_context_and_offset_sync(src_frame)
            if frame_context:
                payload_copy["frame"] = frame_context
                payload_copy["_frame_offset"] = frame_offset
            self._pending_payloads.put((payload_copy, src_page))
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

    def _write_diagnostics_sync(self, session_dir: Path) -> None:
        """Write binding_errors, traces, and a frame tree snapshot to recorder_diag.json."""
        frame_tree: list[dict] = []
        try:
            page = self._active_page_sync()
            if page is not None and not page.is_closed():
                for fr in list(getattr(page, "frames", []) or []):
                    entry: dict = {"url": _frame_url(fr)}
                    parent = _frame_parent(fr)
                    entry["parent_url"] = _frame_url(parent) if parent else None
                    try:
                        info = fr.evaluate(
                            "() => ({ bridge: !!window.__SKILL_BRIDGE_V1__, binding: typeof window.__skillReport === 'function', isTop: window === window.top })"
                        )
                        entry.update(info if isinstance(info, dict) else {})
                    except Exception:
                        entry["eval_error"] = True
                    if parent is not None:
                        try:
                            attrs, rect = _frame_element_attrs_and_rect(fr)
                            entry["iframe_attrs"] = {
                                k: attrs.get(k) for k in ("id", "data-test-id", "data-selenium-test", "name", "sandbox", "src")
                            }
                            entry["iframe_rect"] = rect
                        except Exception:
                            pass
                    frame_tree.append(entry)
        except Exception:  # noqa: BLE001
            pass
        out = session_dir / "recorder_diag.json"
        diag = {
            "binding_errors": self.binding_errors,
            "traces": self._traces,
            "frame_tree": frame_tree,
            "frame_snapshots": self._frame_snapshots,
        }
        try:
            out.write_text(json.dumps(diag, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _rewrite_events_jsonl(self, session_dir: Path) -> None:
        out = session_dir / "events.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for ev in self._materialized:
                f.write(json.dumps(ev.model_dump(mode="json"), ensure_ascii=False) + "\n")
        self._write_diagnostics_sync(session_dir)

    def _should_merge_typing(self, prev: RecordedEvent, curr: RecordedEvent) -> bool:
        if prev.action.action != "type" or curr.action.action != "type":
            return False
        return _typing_target_key(prev) == _typing_target_key(curr)

    def _consume_payload_sync(self, payload: dict[str, Any], src_page: Any | None = None) -> None:
        session_dir = self.data_root / "sessions" / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        page_for_visuals = src_page or self._active_page_sync()
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

    def _capture_a11y_async(self, page: Any) -> dict[str, Any] | None:
        """Capture a11y tree in a thread with 2s timeout. Returns tree dict or None on failure/timeout."""
        if not settings.snapshot_capture_a11y:
            return None
        result = {"tree": None, "elapsed": 0.0}
        def _capture():
            start = time.time()
            try:
                result["tree"] = page.accessibility.snapshot()
                result["elapsed"] = time.time() - start
            except Exception:
                result["elapsed"] = time.time() - start
        thread = threading.Thread(target=_capture, daemon=True)
        thread.start()
        thread.join(timeout=2.0)
        if thread.is_alive():
            return None
        tree = result.get("tree")
        elapsed = result.get("elapsed", 0.0)
        self._last_a11y_capture_time = elapsed
        if elapsed > 0.5:
            self._a11y_skip_count = 3
        return tree if isinstance(tree, dict) else None

    def _capture_dom_snapshot_sync(self, page: Any, dom_sig_short: str) -> dict[str, Any]:
        """Capture (and dedupe) the full DOM + a11y tree for the current page.

        Returns dict with keys: ref, dom_hash, dom_path, a11y_path. Empty on failure.
        Skips capture if the short bridge signature matches the previous one (dedup).
        """
        if not settings.snapshot_dedup_enabled:
            return {}
        if page is None:
            return {}
        try:
            if page.is_closed():
                return {}
        except Exception:  # noqa: BLE001
            return {}

        # Dedup fast path: same short signature as last action → reuse ref.
        if dom_sig_short and dom_sig_short == getattr(self, "_last_dom_sig_short", ""):
            return {
                "ref": self._last_snapshot_ref,
                "dom_hash": self._last_snapshot_hash,
                "dom_path": snapshot_store.relative_blob_path(self.session_id, self._last_snapshot_hash, "html.gz") if self._last_snapshot_hash else None,
                "a11y_path": snapshot_store.relative_blob_path(self.session_id, self._last_snapshot_hash, "a11y.json") if self._last_snapshot_hash else None,
            }

        # Capture full HTML.
        try:
            html = page.content()
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"dom_snapshot_error: {exc!s}")
            return {}

        h, _ = snapshot_store.save_dom_snapshot(self.session_id, html or "")

        # Capture a11y tree (best-effort, may be unavailable on some pages).
        a11y_path_str: str | None = None
        if settings.snapshot_capture_a11y and self._a11y_skip_count == 0:
            tree = self._capture_a11y_async(page)
            if tree is not None:
                try:
                    if snapshot_store.save_a11y_snapshot(self.session_id, tree, h):
                        a11y_path_str = snapshot_store.relative_blob_path(self.session_id, h, "a11y.json")
                except Exception as exc:  # noqa: BLE001
                    self.binding_errors.append(f"a11y_snapshot_error: {exc!s}")
        if self._a11y_skip_count > 0:
            self._a11y_skip_count -= 1

        # Assign ref (UUID) per unique hash so events can join back to a snapshot.
        if h == self._last_snapshot_hash and self._last_snapshot_ref:
            ref = self._last_snapshot_ref
        else:
            ref = snapshot_store.new_snapshot_ref()
        self._last_snapshot_hash = h
        self._last_snapshot_ref = ref
        if dom_sig_short:
            self._last_dom_sig_short = dom_sig_short  # type: ignore[attr-defined]

        return {
            "ref": ref,
            "dom_hash": h,
            "dom_path": snapshot_store.relative_blob_path(self.session_id, h, "html.gz"),
            "a11y_path": a11y_path_str,
        }

    def _finalize_payload_sync(self, page, session_dir: Path, payload: dict[str, Any]) -> RecordedEvent:
        self._seq += 1
        seq = self._seq
        vph = dict(payload.get("visual_placeholder") or {})
        bbox = dict(vph.get("bbox") or {"x": 0, "y": 0, "w": 0, "h": 0})
        frame_offset = payload.get("_frame_offset") if isinstance(payload.get("_frame_offset"), dict) else {}
        if frame_offset:
            try:
                bbox["x"] = int(round(float(bbox.get("x") or 0) + float(frame_offset.get("x") or 0)))
                bbox["y"] = int(round(float(bbox.get("y") or 0) + float(frame_offset.get("y") or 0)))
                if page is not None and not page.is_closed():
                    viewport = _viewport_string_from_page(page)
                    if viewport:
                        vph["viewport"] = viewport
            except (TypeError, ValueError):
                pass
        action = payload["action"]
        action_name = str((action or {}).get("action") or "")
        full_rel: str | None = None
        el_rel: str | None = None
        try:
            if page is not None and not page.is_closed():
                full_rel, el_rel = save_action_images(
                    page,
                    session_dir,
                    seq,
                    bbox,
                    jpeg_quality=settings.screenshot_jpeg_quality,
                )
            else:
                self.binding_errors.append(f"visual_capture_skipped:{action_name}: page_closed")
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"visual_capture_error:{action_name}: {exc!s}")
        pol = get_policy_bundle().data
        timing = resolve_event_timing(action_name, pol)

        # Phase 2: capture full DOM + a11y snapshot (deduped by hash).
        dom_sig_short = str(payload.get("dom_signature_short") or "")
        snapshot_info: dict[str, Any] = {}
        try:
            snapshot_info = self._capture_dom_snapshot_sync(page, dom_sig_short)
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"snapshot_capture_error:{action_name}: {exc!s}")

        timestamp_ms: int | None = None
        if not self.auth_mode:
            if not self._video_session_start_wall_ms:
                raise RuntimeError(
                    "video session start time not initialized; non-auth sessions must record video"
                )
            timestamp_ms = self._compute_event_timestamp_ms(action)
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
                "timestamp_ms": timestamp_ms,
                "frames": {},
            },
            "page": payload["page"],
            "state_change": payload.get("state_change") or {"before": "", "after": ""},
            "timing": timing,
            "extras": {"sequence": seq, "session_id": self.session_id},
            "frame": payload.get("frame") if isinstance(payload.get("frame"), dict) else {},
            # Phase 2 signals.
            "ancestors": payload.get("ancestors") or [],
            "surrounding_text": str(payload.get("surrounding_text") or ""),
            "snapshot": {
                "ref": str(snapshot_info.get("ref") or ""),
                "dom_hash": str(snapshot_info.get("dom_hash") or ""),
                "dom_path": snapshot_info.get("dom_path"),
                "a11y_path": snapshot_info.get("a11y_path"),
            },
        }
        return RecordedEvent.model_validate(body)

    def _make_synthetic_payload(self, kind: str, value_str: str) -> dict[str, Any]:
        """Build a minimal bridge-compatible payload dict for Playwright-side events."""
        page_url = ""
        try:
            page = self._active_page_sync()
            if page is not None and not page.is_closed():
                page_url = page.url
        except Exception:  # noqa: BLE001
            pass
        return {
            "action": {
                "action": kind,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "value": value_str,
            },
            "target": {"tag": "", "id": None, "classes": [], "inner_text": "", "role": None, "aria_label": None, "name": None},
            "selectors": {"css": "", "xpath": "", "text_based": "", "aria": ""},
            "context": {"parent": "", "siblings": [], "index_in_parent": 0, "form_context": None},
            "semantic": {"normalized_text": "", "role": "", "input_type": None, "intent_hint": ""},
            "anchors": [],
            "visual_placeholder": {"bbox": {"x": 0, "y": 0, "w": 0, "h": 0}, "viewport": "", "scroll_position": "0,0"},
            "page": {"url": page_url, "title": ""},
            "state_change": {"before": "", "after": ""},
            # Phase 2 defaults (synthetic events have no bridge signals).
            "ancestors": [],
            "surrounding_text": "",
            "dom_signature_short": "",
        }

    def _enqueue_synthetic(self, kind: str, value_str: str) -> None:
        try:
            payload = self._make_synthetic_payload(kind, value_str)
            self._pending_payloads.put((payload, None))
            self._last_enqueue_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"synthetic_event_error:{kind}: {exc!s}")

    def _on_download(self, download: Any) -> None:
        try:
            value = json.dumps({"url": download.url, "suggested_filename": download.suggested_filename})
            self._enqueue_synthetic("download_observed", value)
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"download_event_error: {exc!s}")

    def _on_dialog(self, dialog: Any) -> None:
        try:
            value = json.dumps({"type": dialog.type, "message": dialog.message})
            try:
                dialog.accept()
            except Exception:  # noqa: BLE001
                pass
            self._enqueue_synthetic("dialog_accept", value)
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"dialog_event_error: {exc!s}")

    def _on_popup(self, popup: Any) -> None:
        try:
            url = ""
            try:
                url = popup.url
                self._remember_current_url(url)
            except Exception:  # noqa: BLE001
                pass
            self._enqueue_synthetic("popup", json.dumps({"url": url}))
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"popup_event_error: {exc!s}")

    def _on_file_chooser(self, _fc: Any) -> None:
        try:
            self._enqueue_synthetic("file_chooser_opened", "")
        except Exception as exc:  # noqa: BLE001
            self.binding_errors.append(f"file_chooser_event_error: {exc!s}")

    def _on_page_navigated(self, page: Any, frame: Any) -> None:
        try:
            parent = getattr(frame, "parent_frame", None)
            parent = parent() if callable(parent) else parent
            if parent is not None:
                return
        except Exception:  # noqa: BLE001
            return
        self._page = page
        self._remember_page_url_sync(page)

    def _attach_page_listeners(self, page: Any) -> None:
        page.on("download", self._on_download)
        page.on("dialog", self._on_dialog)
        page.on("popup", self._on_popup)
        page.on("filechooser", self._on_file_chooser)
        page.on("framenavigated", lambda frame: self._on_page_navigated(page, frame))
        if not self.auth_mode:
            page.on("frameattached", self._on_frame_ready)
            page.on("framenavigated", self._on_frame_ready)

    def _on_context_page(self, page: Any) -> None:
        self._page = page
        self._attach_page_listeners(page)

    def _run_sync_recorder(self) -> None:
        try:
            import sys as _sys
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )
            self.browser_open = True
            # Allow Chromium to steal the foreground on Windows despite focus-lock
            if _sys.platform == "win32":
                try:
                    import ctypes
                    ctypes.windll.user32.AllowSetForegroundWindow(-1)
                except Exception:
                    pass
            self._browser.on("disconnected", lambda _: self._on_browser_disconnected())
            ctx_kwargs: dict[str, Any] = {}
            if self.storage_state_path and Path(self.storage_state_path).is_file():
                ctx_kwargs["storage_state"] = self.storage_state_path
            if not self.auth_mode:
                # Video recording is mandatory for non-auth sessions.
                session_dir = self.data_root / "sessions" / self.session_id
                session_dir.mkdir(parents=True, exist_ok=True)
                ctx_kwargs["record_video_dir"] = str(session_dir)
                ctx_kwargs["record_video_size"] = {"width": 1280, "height": 720}
            self._context = self._browser.new_context(**ctx_kwargs)
            if not self.auth_mode:
                import time as _time
                self._video_session_start = _time.monotonic()
                self._video_session_start_wall_ms = int(_time.time() * 1000)
            if not self.auth_mode:
                self._bridge_script = _load_bridge_script(capture_hover=self.capture_hover)
                self._context.expose_binding("__skillReport", self._binding_sink_sync)
                self._context.add_init_script(self._bridge_script)
                self._context.on("page", self._on_context_page)
            self._page = self._context.new_page()
            try:
                self._page.goto(self.start_url, wait_until="load", timeout=30000)
                self._remember_page_url_sync(self._page)
            except Exception as goto_err:
                self.binding_errors.append(f"navigation_error: {goto_err!s}")
            try:
                self._page.bring_to_front()
            except Exception:
                pass
            if not self.auth_mode:
                page = self._active_page_sync()
                if page is not None:
                    self._ensure_bridge_installed_sync(page)
                    bridge_ok = page.evaluate("() => !!window.__SKILL_BRIDGE_V1__")
                    binding_ok = page.evaluate("() => typeof window.__skillReport === 'function'")
                    if not bridge_ok:
                        self.binding_errors.append("bridge_not_loaded_on_start_page")
                    if not binding_ok:
                        self.binding_errors.append("binding_not_available_on_start_page")
                else:
                    self.binding_errors.append("start_page_closed")
            self._startup_done.set()

            while not self._stop_requested.is_set():
                # Pump the Playwright sync driver so binding callbacks are delivered
                # continuously while recording (not only around teardown calls).
                # Skip in auth_mode — no bridge callbacks to pump.
                if not self.auth_mode:
                    for page in self._open_pages_sync():
                        try:
                            self._ensure_bridge_installed_sync(page)
                            page.evaluate("() => 0")
                        except Exception as exc:  # noqa: BLE001
                            self.binding_errors.append(f"pump_error: {exc!s}")
                    # Take a lightweight frame topology snapshot every 5th tick (~1 s)
                    # so recorder_diag.json captures which iframes exist during recording,
                    # not just at session end when transient iframes may be gone.
                    self._pump_tick += 1
                    if self._pump_tick % 5 == 0 and len(self._frame_snapshots) < 300:
                        try:
                            page = self._active_page_sync()
                            if page is not None and not page.is_closed():
                                self._frame_snapshots.append({
                                    "ts": int(time.time() * 1000),
                                    "frames": [
                                        {
                                            "url": _frame_url(fr),
                                            "parent_url": _frame_url(_frame_parent(fr)) if _frame_parent(fr) else None,
                                        }
                                        for fr in list(getattr(page, "frames", []) or [])
                                    ],
                                })
                        except Exception:  # noqa: BLE001
                            pass
                self._autosave_storage_state_sync()
                for page in self._open_pages_sync():
                    self._remember_page_url_sync(page)
                if self.wait_for_url and not self.reached_wait_url:
                    try:
                        for page in self._open_pages_sync():
                            current_url = page.url
                            self._remember_current_url(current_url)
                            if self._url_matches_wait_target(current_url):
                                self._autosave_storage_state_sync(force=True)
                                self.reached_wait_url = True
                                self._stop_requested.set()
                                break
                    except Exception:  # noqa: BLE001
                        pass
                if not self.auth_mode:
                    try:
                        payload, src_page = self._pending_payloads.get_nowait()
                        self._consume_payload_safe_sync(payload, src_page)
                    except Empty:
                        pass
                if not self._browser.is_connected() or not self._open_pages_sync():
                    self.ended_by_user = True
                    break
                time.sleep(0.2)

            if not self.auth_mode:
                # Stop waits for a short "idle queue" condition so delayed
                # Playwright binding callbacks can still be consumed.
                shutdown_start = time.monotonic()
                while True:
                    for page in self._open_pages_sync():
                        try:
                            self._ensure_bridge_installed_sync(page)
                            page.evaluate("() => 0")
                        except Exception:
                            pass
                    drained = 0
                    try:
                        while True:
                            payload, src_page = self._pending_payloads.get_nowait()
                            drained += 1
                            self._consume_payload_safe_sync(payload, src_page)
                    except Empty:
                        pass
                    elapsed = time.monotonic() - shutdown_start
                    idle_for = time.monotonic() - self._last_enqueue_at if self._last_enqueue_at else elapsed
                    if elapsed >= 5.0 and idle_for >= 1.0 and drained == 0:
                        break
                    time.sleep(0.05)
                # Final diagnostics snapshot after all events are drained.
                session_dir = self.data_root / "sessions" / self.session_id
                session_dir.mkdir(parents=True, exist_ok=True)
                self._write_diagnostics_sync(session_dir)
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
            "capture_hover": self.capture_hover,
            "current_url": self.current_url,
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
        capture_hover: bool = False,
    ) -> RecordingSession:
        sid = str(uuid.uuid4())
        sess = RecordingSession(
            session_id=sid,
            start_url=start_url,
            storage_state_path=storage_state_path,
            storage_state_autosave_path=storage_state_autosave_path,
            wait_for_url=wait_for_url,
            auth_mode=auth_mode,
            capture_hover=capture_hover,
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
