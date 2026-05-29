"""Tests for recorder login flow classification — Phase 2."""

from __future__ import annotations

from app.models.events import (
    ActionMeta, DomContext, PageContext, RecordedEvent, SnapshotRef,
    SemanticFeatures, Selectors, StateChange, TargetDom, Timing, VisualFeatures,
)
from app.recorder.session import classify_login_flow


# ─────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────

def _make_event(
    url: str = "https://app.example.com",
    title: str = "",
    input_type: str | None = None,
    target_name: str | None = None,
) -> RecordedEvent:
    return RecordedEvent(
        action=ActionMeta(action="click", timestamp="2026-01-01T00:00:00Z"),
        target=TargetDom(tag="input", name=target_name),
        selectors=Selectors(css="input", xpath="//input", text_based="", aria=""),
        context=DomContext(parent="form", siblings=[], index_in_parent=0),
        semantic=SemanticFeatures(normalized_text="", role="input", input_type=input_type, intent_hint="provide_input"),
        visual=VisualFeatures(bbox={"x": 0, "y": 0, "w": 0, "h": 0}, viewport="1280x800", scroll_position="0,0"),
        page=PageContext(url=url, title=title),
        state_change=StateChange(before="", after=""),
        timing=Timing(),
        ancestors=[],
        surrounding_text="",
        snapshot=SnapshotRef(ref="", dom_hash=""),
    )


# ─────────────────────────────────────────────────
# classify_login_flow
# ─────────────────────────────────────────────────

class TestClassifyLoginFlow:
    def test_password_field_is_login(self):
        events = [
            _make_event(url="https://app.example.com/login", input_type="text"),
            _make_event(url="https://app.example.com/login", input_type="password"),
            _make_event(url="https://app.example.com/login"),
        ]
        assert classify_login_flow(events) == "login"

    def test_password_in_target_name_is_login(self):
        events = [
            _make_event(url="https://app.example.com/login", target_name="password"),
        ]
        assert classify_login_flow(events) == "login"

    def test_login_url_without_password_is_login(self):
        events = [
            _make_event(url="https://app.example.com/signin"),
            _make_event(url="https://app.example.com/signin"),
        ]
        assert classify_login_flow(events) == "login"

    def test_normal_workflow_is_workflow(self):
        events = [
            _make_event(url="https://dashboard.example.com/services"),
            _make_event(url="https://dashboard.example.com/services"),
        ]
        assert classify_login_flow(events) == "workflow"

    def test_empty_events_is_workflow(self):
        assert classify_login_flow([]) == "workflow"

    def test_oauth_url_is_login(self):
        events = [_make_event(url="https://accounts.example.com/oauth/authorize")]
        assert classify_login_flow(events) == "login"

    def test_auth_url_path_is_login(self):
        events = [_make_event(url="https://app.example.com/auth/login")]
        assert classify_login_flow(events) == "login"

    def test_sso_url_is_login(self):
        events = [_make_event(url="https://app.example.com/sso/callback")]
        assert classify_login_flow(events) == "login"

    def test_dashboard_with_form_is_workflow(self):
        events = [
            _make_event(url="https://dashboard.example.com/create", input_type="text"),
            _make_event(url="https://dashboard.example.com/create", input_type="text"),
        ]
        assert classify_login_flow(events) == "workflow"

    def test_mixed_events_login_detected(self):
        events = [
            _make_event(url="https://dashboard.example.com/services"),
            _make_event(url="https://app.example.com/login", input_type="password"),
            _make_event(url="https://dashboard.example.com/services"),
        ]
        assert classify_login_flow(events) == "login"


def test_recorded_event_omits_url_state_field():
    event = _make_event()
    assert "url_state" not in event.model_dump()
