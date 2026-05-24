"""Tests for ElementFingerprint compilation and Assertion building."""

from __future__ import annotations

import pytest

from app.compiler.build import (
    _build_assertions,
    _build_element_fingerprint,
    _build_structural_fingerprint,
)
from app.models.skill_spec import (
    Assertion,
    ElementFingerprint,
    RecoveryBlock,
    SkillStep,
    ValidationBlock,
)


# ─── ElementFingerprint ──────────────────────────────────────────────────────

def _make_ev(
    *,
    tag="button",
    inner_text="Sign In",
    aria_label="",
    name="",
    data_testid="",
    role="button",
    input_type="",
    classes=None,
    css="",
    x=100, y=400, vw=1280, vh=800,
    anchors=None,
):
    return {
        "target": {
            "tag": tag,
            "inner_text": inner_text,
            "aria_label": aria_label or None,
            "name": name or None,
            "classes": classes or [],
        },
        "semantic": {
            "role": role,
            "input_type": input_type or None,
            "normalized_text": inner_text.lower(),
        },
        "selectors": {
            "css": css or f"{tag}.btn",
            "aria": f'[role="{role}"][name="{inner_text}"]' if not data_testid else f'[data-testid="{data_testid}"]',
            "text_based": f'text="{inner_text}"',
            "xpath": f"//{tag}",
        },
        "visual": {
            "bbox": {"x": x, "y": y, "w": 80, "h": 30, "vw": vw, "vh": vh},
            "viewport": f"{vw}x{vh}",
        },
        "anchors": anchors or [{"element": "Login form", "relation": "inside"}],
        "action": {"action": "click", "value": None},
    }


def test_fingerprint_extracts_data_testid_from_css():
    ev = _make_ev(css='button[data-testid="signin-btn"]')
    fp = _build_element_fingerprint(ev)
    assert isinstance(fp, ElementFingerprint)
    assert fp.data_testid == "signin-btn"


def test_fingerprint_extracts_data_testid_from_aria():
    ev = _make_ev(css="button.btn")
    ev["selectors"]["aria"] = '[data-testid="submit-order"]'
    fp = _build_element_fingerprint(ev)
    assert fp.data_testid == "submit-order"


def test_fingerprint_extracts_basic_fields():
    ev = _make_ev(
        tag="button",
        inner_text="Submit",
        aria_label="Submit order",
        role="button",
        input_type="",
    )
    fp = _build_element_fingerprint(ev)
    assert fp.tag == "button"
    assert fp.inner_text == "Submit"
    assert fp.aria_label == "Submit order"
    assert fp.role == "button"


def test_fingerprint_trims_inner_text_to_120():
    long_text = "A" * 200
    ev = _make_ev(inner_text=long_text)
    fp = _build_element_fingerprint(ev)
    assert len(fp.inner_text) == 120


def test_fingerprint_filters_hash_like_classes():
    ev = _make_ev(classes=["btn", "primary", "a3f9b2c1", "abc123456789"])
    fp = _build_element_fingerprint(ev)
    # Hash-like classes should be filtered; stable tokens kept
    assert "btn" in fp.css_class_tokens
    assert "primary" in fp.css_class_tokens
    # Hash-like class with 4+ consecutive digits should be dropped
    assert not any("a3f9b2c1" in t for t in fp.css_class_tokens)


def test_fingerprint_position_hint_normalized():
    ev = _make_ev(x=640, y=400, vw=1280, vh=800)
    fp = _build_element_fingerprint(ev)
    assert fp.position_hint["x_pct"] == 0.5
    assert fp.position_hint["y_pct"] == 0.5


def test_fingerprint_anchor_phrases():
    anchors = [
        {"element": "Login form", "relation": "inside"},
        {"element": "Password field", "relation": "above"},
    ]
    ev = _make_ev(anchors=anchors)
    fp = _build_element_fingerprint(ev)
    assert "Login form" in fp.anchor_phrases
    assert "Password field" in fp.anchor_phrases


# ─── Assertion building ──────────────────────────────────────────────────────

def _make_validation(wait_for=None, success_conditions=None):
    return ValidationBlock(
        wait_for=wait_for or {},
        success_conditions=success_conditions or {},
    )


def test_assertions_url_changed_from_wait_for():
    ev = _make_ev()
    ev["action"]["action"] = "click"
    ev["page"] = {"url": "https://example.com/login"}
    validation = _make_validation(wait_for={"type": "url_change", "timeout": 8000})
    assertions = _build_assertions(ev, validation)
    assertion = next(a for a in assertions if a.type == "url_changed")
    assert assertion.target == ev["page"]["url"]


def test_assertions_element_appear_from_wait_for():
    ev = _make_ev()
    ev["action"]["action"] = "click"
    validation = _make_validation(
        wait_for={"type": "element_appear", "target": ".success-banner", "timeout": 5000},
    )
    assertions = _build_assertions(ev, validation)
    assert any(a.type == "selector_present" and a.target == ".success-banner" for a in assertions)


def test_assertions_empty_for_fill():
    ev = _make_ev()
    ev["action"]["action"] = "fill"
    ev["target"]["tag"] = "input"
    assertions = _build_assertions(ev, _make_validation())
    assert assertions == []


def test_assertions_advisory_from_success_conditions():
    ev = _make_ev()
    ev["action"]["action"] = "click"
    validation = _make_validation(
        wait_for={"type": "intent_outcome", "timeout": 5000},
        success_conditions={
            "required_elements": [".order-confirmation"],
            "expected_text_tokens": ["success"],
        },
    )
    assertions = _build_assertions(ev, validation)
    advisory = [a for a in assertions if not a.required]
    assert any(a.type == "selector_present" for a in advisory)
    assert any(a.type == "text_present" for a in advisory)


# ─── Structural fingerprint ──────────────────────────────────────────────────

def _make_step(intent="click_button", primary_selector="button.submit", data_testid="", inner_text="Submit", tag="button"):
    fp = ElementFingerprint(
        tag=tag, inner_text=inner_text, data_testid=data_testid, role="button"
    )
    return SkillStep(
        action="click",
        intent=intent,
        target={"primary_selector": primary_selector},
        element_fingerprint=fp,
    )


def test_structural_fingerprint_collects_landmarks():
    steps = [
        _make_step("navigate_to_login", "", "", "", ""),
        _make_step("fill_email", "input[type=email]", "", "Email", "input"),
        _make_step("click_submit", "button.submit", "signin-btn", "Sign In", "button"),
        _make_step("click_cancel", "button.cancel", "", "Cancel", "button"),
    ]
    # First step is navigate (action="navigate") — let's make it explicit
    steps[0] = SkillStep(
        action={"action": "navigate", "url": "https://example.com"},
        intent="navigate_to_start_url",
        target={},
        element_fingerprint=ElementFingerprint(),
    )
    fp = _build_structural_fingerprint(steps)
    assert fp["landmark_count"] >= 1
    assert any(lm.get("data_testid") == "signin-btn" for lm in fp["landmarks"])


def test_structural_fingerprint_skips_navigate_and_scroll():
    nav = SkillStep(action={"action": "navigate"}, intent="navigate_to_start_url", target={})
    scroll = SkillStep(action={"action": "scroll"}, intent="scroll_viewport", target={})
    click = _make_step("click_submit", "button.go", "go-btn", "Go", "button")
    fp = _build_structural_fingerprint([nav, scroll, click])
    assert fp["landmark_count"] == 1
