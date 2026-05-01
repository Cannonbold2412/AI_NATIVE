"""Lightweight regression tests for pipeline, confidence, and compiler (no Playwright)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import settings


def _minimal_click_event() -> dict:
    return {
        "action": {"action": "click", "timestamp": "2026-01-01T00:00:00Z", "value": None},
        "target": {
            "tag": "button",
            "id": "submit",
            "classes": ["btn", "primary"],
            "inner_text": "  Submit  ",
            "role": "button",
            "aria_label": None,
            "name": None,
        },
        "selectors": {
            "css": "#submit",
            "xpath": "/button[1]",
            "text_based": 'text="Submit"',
            "aria": '[role="button"]',
        },
        "context": {"parent": "form#f", "siblings": [], "index_in_parent": 0, "form_context": "form#f"},
        "semantic": {
            "normalized_text": "submit",
            "role": "button",
            "input_type": None,
            "intent_hint": "activate_control",
        },
        "anchors": [{"element": "h1", "relation": "above"}],
        "visual": {
            "full_screenshot": "images/evt_0001_full.jpg",
            "element_snapshot": "images/evt_0001_element.jpg",
            "bbox": {"x": 10, "y": 20, "w": 80, "h": 32},
            "viewport": "800x600",
            "scroll_position": "0,0",
        },
        "page": {"url": "https://example.com/app", "title": "App"},
        "state_change": {"before": "aaa", "after": "bbb"},
        "timing": {"wait_for": "load", "timeout": 5000},
        "extras": {},
    }


def _write_minimal_screenshot(session_id: str, ev: dict, *, data_dir: Path) -> None:
    rel = str(ev["visual"]["full_screenshot"])
    dest = data_dir / "sessions" / session_id / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), (210, 210, 210)).save(dest, "JPEG")


_VISION_ANCHOR_OK = {
    "primary_phrase": "Submit control in form",
    "secondary": [{"element": "login form", "relation": "inside"}],
}


def _compile_with_vision_mocks(session_id: str, events: list[dict], *, call_llm_return=_VISION_ANCHOR_OK):
    """Prepare temp session JPEGs and return (data_dir, patch context managers)."""
    data_dir = Path(tempfile.mkdtemp())
    for ev in events:
        if str((ev.get("action") or {}).get("action") or "") != "scroll":
            _write_minimal_screenshot(session_id, ev, data_dir=data_dir)
    return (
        data_dir,
        patch.object(settings, "data_dir", data_dir),
        patch.object(settings, "llm_endpoint", "https://example.com/v1"),
        patch.object(settings, "llm_enabled", True),
        patch.object(settings, "llm_anchor_vision", True),
        patch("app.llm.intent_llm.call_llm", return_value=None),
        patch("app.llm.anchor_vision_llm.call_llm", return_value=call_llm_return),
    )


class PhaseTests(unittest.TestCase):
    def test_phase2_pipeline_cleans_and_enriches(self) -> None:
        from app.pipeline.run import PIPELINE_VERSION, run_pipeline

        out = run_pipeline([_minimal_click_event()])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["extras"]["pipeline_version"], PIPELINE_VERSION)
        self.assertEqual(out[0]["target"]["inner_text"], "Submit")
        self.assertIn("content_fp", out[0]["extras"])
        self.assertEqual(out[0]["extras"]["primary_selector_kind"], "css")
        self.assertIn("selector_signature", out[0]["extras"])

    def test_phase5_layered_self_match_executes(self) -> None:
        from app.compiler.build import build_signal_reference
        from app.confidence.layered import layered_decision

        ev = _minimal_click_event()
        ref = build_signal_reference(ev)
        decision = layered_decision(ref, ref)
        self.assertEqual(decision["decision"], "execute")
        self.assertEqual(decision["layer"], "dom")

    def test_phase3_compiler_emits_steps(self) -> None:
        from app.compiler.build import compile_skill_package
        from app.pipeline.run import run_pipeline

        evs = run_pipeline([_minimal_click_event()])
        data_dir, *patchers = _compile_with_vision_mocks("sess", evs)
        try:
            with ExitStack() as stack:
                for p in patchers:
                    stack.enter_context(p)
                pkg = compile_skill_package(
                    evs,
                    skill_id="skill_test",
                    source_session_id="sess",
                    title="t",
                    version=1,
                )
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
        self.assertEqual(pkg.meta.id, "skill_test")
        self.assertEqual(len(pkg.skills[0].steps), 1)
        self.assertEqual(pkg.skills[0].steps[0].action, "click")
        dumped = pkg.skills[0].steps[0].model_dump()
        self.assertIn("signals", dumped)
        self.assertIn("decision_policy", dumped)
        self.assertIn("intent", dumped)
        self.assertNotIn("state_diff", dumped)
        sem = dumped.get("signals", {}).get("semantic") or {}
        self.assertEqual(sem.get("final_intent"), dumped.get("intent"))
        self.assertEqual(sem.get("llm_intent"), dumped.get("intent"))
        anchors = dumped.get("signals", {}).get("anchors") or []
        self.assertTrue(anchors)
        self.assertEqual(anchors[0].get("relation"), "target")
        blob = " ".join(str(a.get("element") or "") for a in anchors)
        self.assertNotIn("h1", blob)

    def test_phase6_patch_bumps_version(self) -> None:
        from app.compiler.build import compile_skill_package
        from app.compiler.patch import apply_step_patch
        from app.pipeline.run import run_pipeline

        evs = run_pipeline([_minimal_click_event()])
        data_dir, *patchers = _compile_with_vision_mocks("s", evs)
        try:
            with ExitStack() as stack:
                for p in patchers:
                    stack.enter_context(p)
                pkg = compile_skill_package(
                    evs,
                    skill_id="skill_x",
                    source_session_id="s",
                    title="t",
                    version=1,
                )
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
        doc = pkg.model_dump(mode="json")
        patched = apply_step_patch(
            doc,
            0,
            {"target": {"primary_selector": "#submit2"}},
        )
        self.assertEqual(patched["meta"]["version"], 2)
        self.assertEqual(patched["skills"][0]["steps"][0]["target"]["primary_selector"], "#submit2")

    def test_phase6_patch_recomputes_recovery_strategies_from_resolved_intent(self) -> None:
        from unittest.mock import patch

        from app.compiler.build import compile_skill_package
        from app.compiler.patch import apply_step_patch
        from app.llm.semantic_llm import SemanticLLMOutput
        from app.pipeline.run import run_pipeline

        evs = run_pipeline([_minimal_click_event()])
        data_dir, *patchers = _compile_with_vision_mocks("s", evs)
        try:
            with ExitStack() as stack:
                for p in patchers:
                    stack.enter_context(p)
                pkg = compile_skill_package(
                    evs,
                    skill_id="skill_nav_patch",
                    source_session_id="s",
                    title="t",
                    version=1,
                )
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
        doc = pkg.model_dump(mode="json")
        step = doc["skills"][0]["steps"][0]
        step["intent"] = ""
        rec = dict(step.get("recovery") or {})
        rec["intent"] = ""
        rec["final_intent"] = ""
        rec["strategies"] = ["semantic match", "position match", "visual match"]
        step["recovery"] = rec

        fake = SemanticLLMOutput(
            intent="navigate_to_checkout",
            normalized_text="checkout",
            confidence=0.95,
            source="test",
        )
        with patch("app.compiler.patch.enrich_semantic", return_value=fake):
            patched = apply_step_patch(doc, 0, {"target": {"primary_selector": "#go"}})

        out_rec = patched["skills"][0]["steps"][0]["recovery"]
        self.assertEqual(out_rec.get("intent"), "navigate_to_checkout")
        self.assertEqual(out_rec.get("final_intent"), "navigate_to_checkout")
        self.assertIn("url_state_match", out_rec.get("strategies") or [])
        self.assertIn("llm_reasoned_match", out_rec.get("strategies") or [])

    def test_compiler_validation_commit_waits_dom_when_no_url_signal(self) -> None:
        from app.compiler.validation_planner import infer_wait_for_shape

        policy = {
            "workflow": {"commit_intent_substrings": ["submit", "confirm"]},
            "validation": {
                "default_timeout_ms": 5000,
                "submit_min_timeout_ms": 8000,
                "commit_no_evidence_wait": "dom_change",
            },
        }
        step = {
            "action": {"action": "click"},
            "semantic": {"llm_intent": "submit_login_form"},
            "target": {"tag": "button", "inner_text": "Sign in", "type": "submit"},
            "timing": {"timeout": 5000},
        }
        state_diff = {"url_changed": False, "dom_changed": False}
        wf = infer_wait_for_shape(step, state_diff, policy)
        self.assertEqual(wf.get("type"), "intent_outcome")
        self.assertGreaterEqual(int(wf.get("timeout") or 0), 8000)

    def test_compiler_validation_commit_prefers_url_when_recorded(self) -> None:
        from app.compiler.validation_planner import infer_wait_for_shape

        policy = {
            "workflow": {"commit_intent_substrings": ["submit"]},
            "validation": {"default_timeout_ms": 5000, "submit_min_timeout_ms": 8000},
        }
        step = {
            "action": {"action": "click"},
            "semantic": {"llm_intent": "submit_form"},
            "target": {"tag": "button", "type": "submit", "inner_text": "OK"},
            "timing": {"timeout": 5000},
        }
        state_diff = {"url_changed": True, "dom_changed": False}
        wf = infer_wait_for_shape(step, state_diff, policy)
        self.assertEqual(wf.get("type"), "url_change")
        self.assertGreaterEqual(int(wf.get("timeout") or 0), 8000)

    def test_compiler_validation_commit_no_diff_prefers_url_when_intent_checkout(self) -> None:
        from app.compiler.validation_planner import infer_wait_for_shape

        policy = {
            "workflow": {"commit_intent_substrings": ["submit"]},
            "validation": {"default_timeout_ms": 5000, "submit_min_timeout_ms": 8000, "commit_no_evidence_wait": "dom_change"},
            "decision_layer": {
                "intent_primary_validation": True,
                "commit_intent_prefer_url_substrings": ["checkout", "payment"],
                "commit_intent_prefer_dom_substrings": ["modal", "dialog"],
            },
        }
        step = {
            "action": {"action": "click"},
            "semantic": {"final_intent": "submit_checkout_payment"},
            "target": {"tag": "button", "type": "submit", "inner_text": "Pay"},
            "timing": {"timeout": 5000},
        }
        state_diff = {"url_changed": False, "dom_changed": False}
        wf = infer_wait_for_shape(step, state_diff, policy)
        self.assertEqual(wf.get("type"), "url_change")
        self.assertGreaterEqual(int(wf.get("timeout") or 0), 8000)

    def test_compiler_validation_non_commit_intent_dropdown_element_appear(self) -> None:
        from app.compiler.validation_planner import infer_wait_for_shape

        policy = {
            "workflow": {"commit_intent_substrings": ["submit"]},
            "validation": {"default_timeout_ms": 5000, "navigation_min_timeout_ms": 6000},
            "decision_layer": {
                "intent_primary_validation": True,
                "intent_validation_facets": [
                    {
                        "intent_substrings": ["dropdown", "menu"],
                        "actions": ["click"],
                        "skip_when_commit": True,
                        "wait_for_type": "element_appear",
                    }
                ],
            },
        }
        step = {
            "action": {"action": "click"},
            "semantic": {"final_intent": "open_filter_dropdown"},
            "selectors": {"aria": '[aria-haspopup="listbox"]'},
            "target": {"tag": "button", "inner_text": "Filter"},
            "timing": {"timeout": 4000},
        }
        state_diff = {"url_changed": False, "dom_changed": False}
        wf = infer_wait_for_shape(step, state_diff, policy)
        self.assertEqual(wf.get("type"), "element_appear")
        self.assertIn("aria-haspopup", str(wf.get("target") or ""))

    def test_infer_success_conditions_merges_intent_tokens_when_intent_primary(self) -> None:
        from app.compiler.validation_planner import infer_success_conditions

        policy = {
            "decision_layer": {"intent_primary_validation": True, "success_add_intent_tokens": True},
            "validation": {"default_timeout_ms": 5000},
        }
        wait_for = {"type": "intent_outcome", "timeout": 8000}
        state_diff = {"new_elements": [], "removed_elements": [], "text_change": ["welcome"]}
        out = infer_success_conditions(wait_for, state_diff, "https://ex.test/app", policy, final_intent="submit_login_form")
        tokens = out.get("expected_text_tokens") or []
        self.assertIn("welcome", tokens)
        self.assertIn("submit", tokens)
        self.assertIn("login", tokens)
        self.assertTrue(out.get("intent_validation_primary"))
        self.assertEqual(out.get("final_intent"), "submit_login_form")

    def test_effective_intent_prefers_final_intent_field(self) -> None:
        from app.compiler.intent_access import get_effective_intent

        self.assertEqual(
            get_effective_intent({"final_intent": "focus_email", "llm_intent": "old_value"}),
            "focus_email",
        )

    def test_clean_anchors_prefers_semantic_parent_scope_over_bare_form(self) -> None:
        from app.compiler.v3 import clean_anchors
        from app.policy.bundle import load_policy_bundle

        pol = load_policy_bundle().data
        out = clean_anchors(
            [{"element": "h1", "relation": "above"}],
            {"parent": "form#checkout", "siblings": [], "form_context": "form#checkout"},
            pol,
            target={"inner_text": "Place order", "tag": "button", "aria_label": "", "name": ""},
            semantic={"normalized_text": "place order"},
        )
        elements = [str(a.get("element") or "") for a in out]
        self.assertTrue(any("form#checkout" in e for e in elements))
        self.assertNotIn("form", elements)

    def test_anchor_ranking_orders_by_target_overlap(self) -> None:
        from app.compiler.decision_layer import rank_merged_anchors
        from app.policy.bundle import load_policy_bundle

        pol = load_policy_bundle().data
        ev = {
            "target": {"inner_text": "Save", "name": "save_btn", "aria_label": "Save draft"},
            "semantic": {"normalized_text": "save"},
            "context": {"parent": "div.toolbar", "siblings": ["span:autosaved"]},
        }
        anchors = [
            {"element": "form", "relation": "inside"},
            {"element": "save draft", "relation": "near"},
        ]
        ranked = rank_merged_anchors(anchors, ev, "click_save", pol)
        self.assertEqual(ranked[0].get("element"), "save draft")

    def test_anchor_ranking_prefers_scope_and_intent_over_bare_form(self) -> None:
        from app.compiler.decision_layer import rank_merged_anchors
        from app.policy.bundle import load_policy_bundle

        pol = load_policy_bundle().data
        ev = {
            "target": {
                "inner_text": "Pay now",
                "name": "pay",
                "aria_label": "",
                "placeholder": "",
            },
            "semantic": {"normalized_text": "pay now"},
            "context": {"parent": "div#pay-panel", "siblings": []},
        }
        anchors = [
            {"element": "form", "relation": "inside"},
            {"element": "form#checkout", "relation": "inside"},
        ]
        ranked = rank_merged_anchors(anchors, ev, "submit_checkout_payment", pol)
        self.assertEqual(ranked[0].get("element"), "form#checkout")

    def test_recovery_strategies_merge_decision_layer_intent_facets(self) -> None:
        from app.compiler.recovery_policy import recovery_strategies_for_intent
        from app.policy.bundle import load_policy_bundle

        pol = load_policy_bundle().data
        strat = recovery_strategies_for_intent("navigate_to_account_settings", pol)
        self.assertIn("semantic match", strat)
        self.assertIn("url_state_match", strat)

    def test_default_recovery_block_includes_final_intent(self) -> None:
        from app.compiler.recovery_policy import default_recovery_block
        from app.models.skill_spec import RecoveryBlock
        from app.policy.bundle import load_policy_bundle

        pol = load_policy_bundle().data
        raw = default_recovery_block("open_filter_dropdown", [], pol)
        block = RecoveryBlock(**raw)
        self.assertEqual(block.intent, "open_filter_dropdown")
        self.assertEqual(block.final_intent, "open_filter_dropdown")

    def test_clean_steps_merges_nonconsecutive_duplicate_type_in_place(self) -> None:
        """Later type on same field updates the earlier type row; cross-field order stays chronological."""
        from app.compiler.v3 import clean_steps

        def _ev(action: str, name: str, value: str | None = None) -> dict:
            base = {
                "target": {"tag": "input", "name": name, "id": f"id_{name}"},
                "selectors": {
                    "css": f"#{name}",
                    "aria": f'[role="input"][name="{name}"]',
                    "text_based": "",
                },
                "semantic": {"role": "input", "input_type": "email" if name == "email" else "password"},
                "context": {"form_context": "form"},
                "page": {"url": "https://example.com/login", "title": "Login"},
                "timing": {"timeout": 5000},
            }
            if action == "type":
                return {**base, "action": {"action": "type", "value": value}}
            return {**base, "action": {"action": "click", "value": None}}

        seq = [
            _ev("click", "email"),
            _ev("type", "email", "a@b.com"),
            _ev("click", "password"),
            _ev("type", "email", "c@d.com"),
            _ev("type", "password", "secret"),
        ]
        out = clean_steps(seq, {})
        names = []
        for s in out:
            act = (s.get("action") or {}).get("action")
            nm = (s.get("target") or {}).get("name")
            val = (s.get("action") or {}).get("value")
            names.append((act, nm, val))
        self.assertEqual(
            names,
            [
                ("type", "email", "c@d.com"),
                ("type", "password", "secret"),
            ],
        )
        from app.compiler.v3 import sanitize_steps_preserving_order

        with_focus = sanitize_steps_preserving_order(out, {})
        actions = [(s.get("action") or {}).get("action") for s in with_focus]
        self.assertEqual(actions, ["focus", "type", "focus", "type"])

    def test_sanitize_steps_preserving_order_inserts_focus_only_when_needed(self) -> None:
        from app.compiler.v3 import clean_steps, sanitize_steps_preserving_order

        type_email = {
            "action": {"action": "type", "value": "x@y.com"},
            "target": {"tag": "input", "name": "email"},
            "selectors": {"css": "#e", "aria": '[role="input"][name="email"]', "text_based": ""},
            "semantic": {"role": "input", "input_type": "email"},
            "context": {"form_context": "form"},
            "page": {"url": "https://example.com/login", "title": "Login"},
            "timing": {"timeout": 5000},
        }
        focus_pw = {
            "action": {"action": "focus"},
            "target": {"tag": "input", "name": "password"},
            "selectors": {"css": "#p", "aria": '[role="input"][name="password"]', "text_based": ""},
            "semantic": {"role": "input", "input_type": "password"},
            "context": {"form_context": "form"},
            "page": {"url": "https://example.com/login", "title": "Login"},
            "timing": {"timeout": 5000},
        }
        type_pw = {
            "action": {"action": "type", "value": "pw"},
            "target": {"tag": "input", "name": "password"},
            "selectors": {"css": "#p", "aria": '[role="input"][name="password"]', "text_based": ""},
            "semantic": {"role": "input", "input_type": "password"},
            "context": {"form_context": "form"},
            "page": {"url": "https://example.com/login", "title": "Login"},
            "timing": {"timeout": 5000},
        }
        cleaned = clean_steps([type_email, focus_pw, type_pw], {})
        out = sanitize_steps_preserving_order(cleaned, {})
        actions = [(s.get("action") or {}).get("action") for s in out]
        self.assertEqual(actions, ["focus", "type", "focus", "type"])

    def test_compiler_clean_steps_drops_post_type_field_click(self) -> None:
        from app.compiler.v3 import clean_steps

        type_ev = {
            "action": {"action": "type", "value": "secret"},
            "target": {"tag": "input", "name": "password", "id": "x"},
            "selectors": {"css": "#x", "aria": "[role=\"input\"][name=\"password\"]"},
            "semantic": {"role": "input", "input_type": "password"},
            "context": {"form_context": "form"},
            "page": {"url": "https://example.com/login", "title": "Login"},
            "timing": {"timeout": 5000},
        }
        click_ev = {
            "action": {"action": "click"},
            "target": {"tag": "input", "name": "password", "id": "x"},
            "selectors": {"css": "#x", "aria": "[role=\"input\"][name=\"password\"]"},
            "semantic": {"role": "input", "input_type": "password"},
            "context": {"form_context": "form"},
            "page": {"url": "https://example.com/login", "title": "Login"},
            "timing": {"timeout": 5000},
        }
        out = clean_steps([type_ev, click_ev], {})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["action"]["action"], "type")

    def test_selector_filters_reject_dynamic_id_and_weak_tokens(self) -> None:
        from app.compiler.selector_filters import selector_passes_filters

        self.assertFalse(selector_passes_filters("#_r_3_"))
        self.assertFalse(selector_passes_filters("password"))
        self.assertFalse(selector_passes_filters('[role="input"][name="email"]'))
        self.assertFalse(selector_passes_filters('[role="path"]'))
        self.assertTrue(selector_passes_filters('input[name="password"]'))

    def test_intent_normalization_maps_click_prefix_on_editable(self) -> None:
        from app.policy.intent_ontology import normalize_compiler_intent

        ev = {
            "action": {"action": "focus"},
            "target": {"tag": "input", "name": "password"},
            "semantic": {"input_type": "password"},
        }
        policy = {"intent": {"generic_intents": ["interact"]}}
        out = normalize_compiler_intent(ev, "click_password", policy)
        self.assertEqual(out, "focus_password")

    def test_static_audit_flags_weak_reference(self) -> None:
        from app.confidence.uncertainty import audit_reference

        ref = {
            "action_kind": "click",
            "selectors": {"css": ""},
            "anchors": [],
            "visual": {"bbox": {"x": 1, "y": 1, "w": 0, "h": 0}},
        }
        issues = audit_reference(ref)
        self.assertIn("empty_primary_css", issues)
        self.assertIn("anchors_empty", issues)
        self.assertIn("weak_visual_bbox", issues)

    def test_static_audit_downgrades_missing_anchors_when_signals_are_strong(self) -> None:
        from app.confidence.uncertainty import audit_reference

        ref = {
            "action_kind": "type",
            "selectors": {"css": 'input[name="email"]', "aria": '[aria-label="Email"]'},
            "semantic": {"llm_intent": "enter_email"},
            "anchors": [],
            "visual": {"bbox": {"x": 1, "y": 1, "w": 40, "h": 20}},
        }
        issues = audit_reference(ref)
        self.assertIn("anchors_empty_warn", issues)
        self.assertNotIn("anchors_empty", issues)

    def test_static_audit_requires_anchors_for_destructive_intent(self) -> None:
        from app.confidence.uncertainty import audit_reference

        ref = {
            "action_kind": "click",
            "selectors": {"css": 'button[data-action="delete"]'},
            "target": {"inner_text": "Delete account", "role": "button", "type": "button"},
            "semantic": {"llm_intent": "delete_account"},
            "anchors": [],
            "visual": {"bbox": {"x": 2, "y": 2, "w": 30, "h": 20}},
        }
        issues = audit_reference(ref)
        self.assertIn("anchors_empty_required", issues)

    def test_static_audit_weak_destructive_intent_is_warning_only(self) -> None:
        from app.confidence.uncertainty import audit_reference

        ref = {
            "action_kind": "click",
            "selectors": {"css": 'button[data-action="remove-filter"]', "aria": '[aria-label="Apply"]'},
            "target": {"inner_text": "Apply", "role": "button", "type": "button"},
            "semantic": {"llm_intent": "remove_filter"},
            "anchors": [],
            "visual": {"bbox": {"x": 2, "y": 2, "w": 30, "h": 20}},
        }
        issues = audit_reference(ref)
        self.assertIn("anchors_empty_warn", issues)
        self.assertNotIn("anchors_empty_required", issues)

    def test_static_audit_explicit_destructive_flag_requires_anchors(self) -> None:
        from app.confidence.uncertainty import audit_reference

        ref = {
            "action_kind": "click",
            "selectors": {"css": 'button[data-kind="danger"]'},
            "target": {"inner_text": "Confirm", "role": "button", "type": "button"},
            "semantic": {"llm_intent": "confirm_action", "is_destructive": True},
            "anchors": [],
            "visual": {"bbox": {"x": 2, "y": 2, "w": 30, "h": 20}},
        }
        issues = audit_reference(ref)
        self.assertIn("anchors_empty_required", issues)

    def test_infer_wait_non_commit_ignores_dom_when_policy_none(self) -> None:
        from app.compiler.validation_planner import infer_wait_for_shape

        policy = {
            "workflow": {"commit_intent_substrings": ["submit"]},
            "validation": {"default_timeout_ms": 5000, "non_commit_dom_wait_on_diff": "none"},
        }
        step = {
            "action": {"action": "click"},
            "semantic": {"final_intent": "click_sidebar_item"},
            "target": {"tag": "span"},
            "timing": {},
        }
        state_diff = {"url_changed": False, "dom_changed": True}
        wf = infer_wait_for_shape(step, state_diff, policy)
        self.assertEqual(wf.get("type"), "none")

    def test_destructive_click_uses_element_appear_when_selector_present(self) -> None:
        from app.compiler.validation_planner import infer_wait_for_shape

        policy = {
            "workflow": {"commit_intent_substrings": ["submit"]},
            "decision_layer": {"intent_primary_validation": True},
            "validation": {
                "default_timeout_ms": 4000,
                "submit_min_timeout_ms": 8000,
                "navigation_min_timeout_ms": 6000,
                "destructive_require_confirmation_wait": True,
                "destructive_wait_for_type": "element_appear",
            },
        }
        step = {
            "action": {"action": "click"},
            "semantic": {"final_intent": "delete_account_row"},
            "selectors": {"aria": '[data-testid="confirm-delete"]'},
            "target": {"tag": "button", "inner_text": "Delete"},
            "timing": {"timeout": 4000},
        }
        wf = infer_wait_for_shape(step, {"url_changed": False, "dom_changed": False}, policy)
        self.assertEqual(wf.get("type"), "element_appear")
        self.assertIn("confirm-delete", str(wf.get("target") or ""))

    def test_commit_no_evidence_intent_first_prefers_url_for_checkout(self) -> None:
        from app.compiler.validation_planner import infer_wait_for_shape

        policy = {
            "workflow": {"commit_intent_substrings": ["submit"]},
            "validation": {
                "default_timeout_ms": 5000,
                "submit_min_timeout_ms": 8000,
                "commit_no_evidence_wait": "dom_change",
                "commit_no_evidence_intent_first": True,
            },
            "decision_layer": {
                "intent_primary_validation": True,
                "commit_intent_prefer_url_substrings": ["checkout", "payment"],
            },
        }
        step = {
            "action": {"action": "click"},
            "semantic": {"final_intent": "submit_checkout_payment"},
            "target": {"tag": "button", "type": "submit", "inner_text": "Pay"},
            "timing": {"timeout": 5000},
        }
        state_diff = {"url_changed": False, "dom_changed": False}
        wf = infer_wait_for_shape(step, state_diff, policy)
        self.assertEqual(wf.get("type"), "url_change")

    def test_normalize_upgrades_click_button_with_visible_text(self) -> None:
        from app.policy.bundle import get_policy_bundle
        from app.policy.intent_ontology import normalize_compiler_intent

        pol = get_policy_bundle().data
        ev = {
            "action": {"action": "click"},
            "target": {"tag": "button", "inner_text": "Save draft", "name": "", "aria_label": ""},
            "semantic": {"normalized_text": "save draft", "role": "button"},
        }
        out = normalize_compiler_intent(ev, "click_button", pol)
        self.assertTrue(out.startswith("activate_control_") or "save" in out)

    def test_normalize_strips_click_path_uses_intent_hint(self) -> None:
        from app.policy.bundle import get_policy_bundle
        from app.policy.intent_ontology import normalize_compiler_intent

        pol = get_policy_bundle().data
        ev = {
            "action": {"action": "click"},
            "target": {"tag": "path", "inner_text": "Export CSV", "name": "", "aria_label": ""},
            "semantic": {"normalized_text": "export csv", "role": "graphics-symbol", "intent_hint": "activate_control"},
        }
        out = normalize_compiler_intent(ev, "click_path", pol)
        self.assertNotIn("path", out)
        self.assertNotEqual(out, "click_path")

    def test_compile_requires_source_session_for_vision_anchors(self) -> None:
        from app.compiler.build import compile_skill_package
        from app.llm.anchor_vision_llm import VisionAnchorGenerationError
        from app.pipeline.run import run_pipeline

        evs = run_pipeline([_minimal_click_event()])
        with self.assertRaises(VisionAnchorGenerationError) as ctx:
            compile_skill_package(
                evs,
                skill_id="x",
                source_session_id="   ",
                title="t",
                version=1,
            )
        self.assertEqual(ctx.exception.reason, "source_session_id_required")

    def test_vision_llm_failure_aborts_compile(self) -> None:
        from app.compiler.build import compile_skill_package
        from app.llm.anchor_vision_llm import VisionAnchorGenerationError
        from app.pipeline.run import run_pipeline

        evs = run_pipeline([_minimal_click_event()])
        data_dir, *patchers = _compile_with_vision_mocks("sess", evs, call_llm_return=None)
        try:
            with ExitStack() as stack:
                for p in patchers:
                    stack.enter_context(p)
                with self.assertRaises(VisionAnchorGenerationError) as ctx:
                    compile_skill_package(
                        evs,
                        skill_id="y",
                        source_session_id="sess",
                        title="t",
                        version=1,
                    )
                self.assertEqual(ctx.exception.reason, "vision_llm_empty_response")
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
