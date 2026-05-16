"""Tests for recorder login flow classification — Phase 2."""

from __future__ import annotations

from app.models.events import (
    ActionMeta, DomContext, PageContext, RecordedEvent,
    SemanticFeatures, Selectors, StateChange, TargetDom, Timing, UrlStatePair, UrlStateEntry, VisualFeatures,
)
from app.recorder.session import classify_login_flow, _parse_url_state


# ─────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────

def _make_event(
    url: str = "https://app.example.com",
    title: str = "",
    input_type: str | None = None,
    target_name: str | None = None,
    url_state_before_url: str = "",
    url_state_after_url: str = "",
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
        url_state=UrlStatePair(
            before=UrlStateEntry(url=url_state_before_url or url, title=title),
            after=UrlStateEntry(url=url_state_after_url or url, title=title),
        ) if (url_state_before_url or url_state_after_url) else None,
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


# ─────────────────────────────────────────────────
# _parse_url_state
# ─────────────────────────────────────────────────

class TestParseUrlState:
    def test_parses_valid_url_state(self):
        raw = {
            "before": {"url": "https://example.com/login", "title": "Login"},
            "after": {"url": "https://example.com/dashboard", "title": "Dashboard"},
        }
        result = _parse_url_state(raw)
        assert result is not None
        assert result["before"]["url"] == "https://example.com/login"
        assert result["after"]["url"] == "https://example.com/dashboard"
        assert result["before"]["title"] == "Login"
        assert result["after"]["title"] == "Dashboard"

    def test_returns_none_for_none(self):
        assert _parse_url_state(None) is None

    def test_returns_none_for_empty_dict(self):
        assert _parse_url_state({}) is None

    def test_handles_missing_after(self):
        raw = {"before": {"url": "https://example.com/login", "title": "Login"}, "after": None}
        result = _parse_url_state(raw)
        assert result is not None
        assert result["after"]["url"] == ""

    def test_handles_missing_fields(self):
        raw = {"before": {}, "after": {}}
        result = _parse_url_state(raw)
        assert result is not None
        assert result["before"]["url"] == ""
        assert result["after"]["title"] == ""


# ─────────────────────────────────────────────────
# UrlStatePair model
# ─────────────────────────────────────────────────

class TestUrlStatePairModel:
    def test_round_trips_through_model(self):
        pair = UrlStatePair(
            before=UrlStateEntry(url="https://example.com/before", title="Before"),
            after=UrlStateEntry(url="https://example.com/after", title="After"),
        )
        dumped = pair.model_dump()
        restored = UrlStatePair.model_validate(dumped)
        assert restored.before.url == "https://example.com/before"
        assert restored.after.url == "https://example.com/after"

    def test_defaults_to_empty_strings(self):
        pair = UrlStatePair()
        assert pair.before.url == ""
        assert pair.after.title == ""

    def test_recorded_event_with_url_state(self):
        event = _make_event(
            url="https://app.example.com",
            url_state_before_url="https://app.example.com/before",
            url_state_after_url="https://app.example.com/after",
        )
        assert event.url_state is not None
        assert event.url_state.before.url == "https://app.example.com/before"
        assert event.url_state.after.url == "https://app.example.com/after"

    def test_recorded_event_without_url_state_is_none(self):
        event = _make_event()
        assert event.url_state is None
