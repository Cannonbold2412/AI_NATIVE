from __future__ import annotations

import pytest

from app.recorder import session as recorder_session
from app.recorder.session import RecordingSession


def _payload(action: str = "click") -> dict:
    return {
        "action": {"action": action, "timestamp": "2026-01-01T00:00:00Z", "value": None},
        "target": {"tag": "button", "id": None, "classes": [], "inner_text": "Save", "role": "button", "aria_label": None, "name": None},
        "selectors": {"css": "button", "xpath": "/button[1]", "text_based": 'text="Save"', "aria": '[role="button"][name="Save"]'},
        "context": {"parent": "body", "siblings": [], "index_in_parent": 0, "form_context": None},
        "semantic": {"normalized_text": "save", "role": "button", "input_type": None, "intent_hint": "activate_control"},
        "anchors": [],
        "visual_placeholder": {"bbox": {"x": 1, "y": 1, "w": 20, "h": 10}, "viewport": "1280x720", "scroll_position": "0,0"},
        "page": {"url": "https://example.com", "title": "Example"},
        "state_change": {"before": "", "after": ""},
    }


def test_payload_capture_error_is_recorded_without_raising(monkeypatch) -> None:
    sess = RecordingSession(session_id="safe-capture")

    def fail_capture(*_args, **_kwargs):
        raise ValueError("bad event")

    monkeypatch.setattr(sess, "_consume_payload_sync", fail_capture)

    sess._consume_payload_safe_sync({"action": {"action": "hover"}})

    assert sess.binding_errors == ["event_capture_error:hover: bad event"]


def test_bridge_script_injects_hover_capture_option() -> None:
    script = recorder_session._load_bridge_script(capture_hover=True)

    assert 'window.__SKILL_CAPTURE_OPTIONS__ = {"capture_hover": true};' in script


def test_registry_sets_hover_capture_flag() -> None:
    sess = recorder_session.registry.create(capture_hover=True)
    try:
        assert sess.capture_hover is True
    finally:
        recorder_session.registry.pop(sess.session_id)


def test_status_exposes_current_url_and_ignores_blank_urls() -> None:
    sess = RecordingSession(session_id="current-url")

    sess._remember_current_url("about:blank")
    assert sess.status()["current_url"] == ""

    sess._remember_current_url("https://example.com/app?team=abc#leads")

    assert sess.status()["current_url"] == "https://example.com/app?team=abc#leads"


def test_ensure_bridge_installs_missing_child_frame() -> None:
    sess = RecordingSession(session_id="frame-bridge")
    sess._bridge_script = "window.__SKILL_BRIDGE_V1__ = true;"

    class FakeFrame:
        def __init__(self, installed: bool) -> None:
            self.installed = installed
            self.calls: list[str] = []

        def evaluate(self, script: str) -> bool | None:
            self.calls.append(script)
            if "const hasWin = !!window.__SKILL_BRIDGE_V1__" in script:
                return not self.installed
            self.installed = True
            return None

    class FakePage:
        frames: list[FakeFrame]

        def __init__(self) -> None:
            self.frames = [FakeFrame(installed=True), FakeFrame(installed=False)]

        def is_closed(self) -> bool:
            return False

    page = FakePage()

    sess._ensure_bridge_installed_sync(page)

    assert len(page.frames[0].calls) == 1
    assert "const hasWin = !!window.__SKILL_BRIDGE_V1__" in page.frames[0].calls[0]
    assert len(page.frames[1].calls) == 2
    assert "const hasWin = !!window.__SKILL_BRIDGE_V1__" in page.frames[1].calls[0]
    assert page.frames[1].calls[1] == sess._bridge_script
    assert page.frames[1].installed is True
    assert sess.binding_errors == []


def test_frame_ready_installs_bridge_immediately() -> None:
    sess = RecordingSession(session_id="frame-ready")
    sess._bridge_script = "window.__SKILL_BRIDGE_V1__ = true;"

    class FakeFrame:
        def __init__(self) -> None:
            self.installed = False
            self.calls: list[str] = []

        def evaluate(self, script: str) -> bool | None:
            self.calls.append(script)
            if "const hasWin = !!window.__SKILL_BRIDGE_V1__" in script:
                return not self.installed
            self.installed = True
            return None

    frame = FakeFrame()

    sess._on_frame_ready(frame)

    assert len(frame.calls) == 2
    assert "const hasWin = !!window.__SKILL_BRIDGE_V1__" in frame.calls[0]
    assert frame.calls[1] == sess._bridge_script
    assert frame.installed is True


def test_binding_source_child_frame_adds_frame_context() -> None:
    sess = RecordingSession(session_id="frame-context")

    class FakeElement:
        def evaluate(self, script: str) -> dict:
            if "getBoundingClientRect" in script:
                return {"x": 42, "y": 18, "w": 600, "h": 720}
            return {
                "id": "object-builder-ui",
                "data-test-id": "object-builder-ui-iframe",
                "data-selenium-test": "associate-panel-iframe",
                "name": "",
                "title": "",
                "aria-label": "",
                "src": "https://app-na2.hubspot.com/object-builder/246242636/0-1/embed?",
            }

    class FakeFrame:
        def __init__(self, parent: object | None, url: str = "") -> None:
            self.parent_frame = parent
            self.url = url

        def frame_element(self) -> FakeElement:
            return FakeElement()

    class FakePage:
        pass

    payload = _payload()
    sess._binding_sink_sync(
        {
            "page": FakePage(),
            "frame": FakeFrame(
                object(),
                "https://app-na2.hubspot.com/object-builder/246242636/0-1/embed?",
            ),
        },
        payload,
    )

    queued_payload, _page = sess._pending_payloads.get_nowait()
    assert queued_payload["frame"]["chain"][0]["selector"] == 'iframe[id="object-builder-ui"]'
    assert 'iframe[data-test-id="object-builder-ui-iframe"]' in queued_payload["frame"]["chain"][0]["fallback_selectors"]
    assert queued_payload["_frame_offset"] == {"x": 42.0, "y": 18.0}


def test_frame_offset_adjusts_visual_bbox_before_capture(monkeypatch, tmp_path) -> None:
    sess = RecordingSession(session_id="frame-bbox", data_root=tmp_path)
    sess._video_session_start_wall_ms = 1
    captured: dict[str, object] = {}

    class FakePage:
        viewport_size = {"width": 1280, "height": 720}

        def is_closed(self) -> bool:
            return False

    def fake_save_action_images(_page, _session_dir, _seq, bbox, **_kwargs):
        captured["bbox"] = dict(bbox)
        return "images/full.jpg", "images/el.jpg"

    monkeypatch.setattr(recorder_session, "save_action_images", fake_save_action_images)

    payload = _payload()
    payload["_frame_offset"] = {"x": 50, "y": 20}
    payload["frame"] = {
        "chain": [
            {
                "selector": 'iframe[id="object-builder-ui"]',
                "fallback_selectors": [],
                "url": "",
                "url_pattern": "",
            }
        ]
    }

    event = sess._finalize_payload_sync(FakePage(), tmp_path / "sessions" / sess.session_id, payload)

    assert captured["bbox"] == {"x": 51, "y": 21, "w": 20, "h": 10}
    assert event.visual.bbox == {"x": 51, "y": 21, "w": 20, "h": 10}
    assert event.visual.viewport == "1280x720"
    assert event.frame.chain[0]["selector"] == 'iframe[id="object-builder-ui"]'


def test_visual_capture_failure_keeps_event(monkeypatch, tmp_path) -> None:
    sess = RecordingSession(session_id="visual-fallback", data_root=tmp_path)
    sess._video_session_start_wall_ms = 1

    class FakePage:
        def is_closed(self) -> bool:
            return False

    sess._page = FakePage()

    def fail_screenshot(*_args, **_kwargs):
        raise RuntimeError("screenshot failed")

    monkeypatch.setattr(recorder_session, "save_action_images", fail_screenshot)

    sess._consume_payload_sync(_payload())

    assert len(sess.snapshot_events()) == 1
    assert sess.snapshot_events()[0]["visual"]["full_screenshot"] is None
    assert any(err.startswith("visual_capture_error:click") for err in sess.binding_errors)


def test_finalize_video_recording_skips_frame_extraction_when_no_events(tmp_path) -> None:
    sess = RecordingSession(session_id="empty-video", data_root=tmp_path)
    session_dir = tmp_path / "sessions" / sess.session_id
    session_dir.mkdir(parents=True)
    raw_video = session_dir / "playwright-output.webm"
    raw_video.write_bytes(b"video")

    sess._finalize_video_recording_sync()

    assert not raw_video.exists()
    assert (session_dir / "recording.webm").read_bytes() == b"video"
    assert not (session_dir / "events.jsonl").exists()
    assert sess.binding_errors == ["video_frame_extraction_skipped:no_events"]


def test_finalize_video_recording_requires_events_file_when_events_exist(tmp_path) -> None:
    sess = RecordingSession(session_id="missing-events-file", data_root=tmp_path)
    session_dir = tmp_path / "sessions" / sess.session_id
    session_dir.mkdir(parents=True)
    (session_dir / "recording.webm").write_bytes(b"video")
    sess._materialized.append(object())  # type: ignore[arg-type]

    with pytest.raises(FileNotFoundError, match="events.jsonl not found"):
        sess._finalize_video_recording_sync()
