"""Tests for the Phase 1-4 redesign: LLM-compiled selectors + DOM snapshots."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.compiler.llm_selector_generator import (
    SelectorCompileTask,
    is_obviously_invalid,
    rank_candidates,
    task_from_recorded_event,
    validate_selector,
)
from app.execution.element_resolver import (
    TIER_A11Y,
    TIER_COMPILED,
    TIER_LLM_RECOVERY,
    TierMetrics,
    _PromotionState,
    escalate_step_failure,
    escalation_queue,
)
from app.llm.openapi_client import SelectorCandidate
from app.models.events import Ancestor, RecordedEvent, SnapshotRef
from app.models.skill_spec import (
    SkillBlock,
    SkillMeta,
    SkillPackage,
    SkillStep,
    WorkflowIntentGraph,
    WorkflowIntentStep,
)
from app.storage import selector_cache, snapshots


# ─── Phase 1: LLM client + selector cache ─────────────────────────────────────


class SelectorCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._settings_patch = mock.patch("app.storage.selector_cache.settings")
        m = self._settings_patch.start()
        m.data_dir = self.tmp
        m.selector_cache_enabled = True
        m.selector_cache_ttl_days = 30

    def tearDown(self):
        self._settings_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cache_roundtrip(self):
        bbox = {"x": 10, "y": 20, "w": 100, "h": 30}
        selector_cache.set("hash_a", bbox, "model_x", [{"selector": "button"}])
        got = selector_cache.get("hash_a", bbox, "model_x")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["selector"], "button")

    def test_cache_miss_returns_none(self):
        self.assertIsNone(selector_cache.get("missing_hash", {"x": 0, "y": 0, "w": 0, "h": 0}, "model_x"))

    def test_cache_disabled_skips_all(self):
        with mock.patch("app.storage.selector_cache.settings") as m:
            m.data_dir = self.tmp
            m.selector_cache_enabled = False
            selector_cache.set("hash_b", None, None, [{"selector": "div"}])
            self.assertIsNone(selector_cache.get("hash_b", None, None))


class SnapshotStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._settings_patch = mock.patch("app.storage.snapshots.settings")
        m = self._settings_patch.start()
        m.data_dir = self.tmp

    def tearDown(self):
        self._settings_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dom_snapshot_dedup(self):
        sid = "sess_a"
        html = "<html><body>hello</body></html>"
        h1, _ = snapshots.save_dom_snapshot(sid, html)
        h2, _ = snapshots.save_dom_snapshot(sid, html)
        self.assertEqual(h1, h2)
        stats = snapshots.dedup_stats(sid)
        self.assertEqual(stats["unique_dom_snapshots"], 1)

    def test_dom_snapshot_roundtrip(self):
        sid = "sess_b"
        html = "<html><body>roundtrip</body></html>"
        h, _ = snapshots.save_dom_snapshot(sid, html)
        out = snapshots.read_dom_snapshot(sid, h)
        self.assertEqual(out, html)

    def test_a11y_snapshot(self):
        sid = "sess_c"
        h, _ = snapshots.save_dom_snapshot(sid, "<html></html>")
        snapshots.save_a11y_snapshot(sid, {"role": "WebArea"}, h)
        got = snapshots.read_a11y_snapshot(sid, h)
        self.assertEqual(got["role"], "WebArea")


# ─── Phase 2: RecordedEvent model extensions ──────────────────────────────────


class RecordedEventExtensionsTests(unittest.TestCase):
    def _base_event(self) -> dict:
        return {
            "action": {"action": "click", "timestamp": "2026-01-01T00:00:00Z"},
            "target": {"tag": "button", "classes": []},
            "selectors": {"css": "button", "xpath": "/button", "text_based": "", "aria": ""},
            "context": {"parent": "", "siblings": [], "index_in_parent": 0, "form_context": None},
            "semantic": {"normalized_text": "", "role": "button", "intent_hint": "click"},
            "visual": {"bbox": {"x": 0, "y": 0, "w": 10, "h": 10}, "viewport": "1024x768", "scroll_position": "0,0"},
            "page": {"url": "about:blank", "title": ""},
            "state_change": {"before": "", "after": ""},
            "timing": {"wait_for": "load", "timeout": 5000},
            "ancestors": [],
            "surrounding_text": "",
            "snapshot": {"ref": "", "dom_hash": ""},
        }

    def test_new_signals_populate(self):
        data = self._base_event()
        data["ancestors"] = [{"tag": "div", "id": "wrap", "classes": ["x"], "outer_html": "<div></div>"}]
        data["surrounding_text"] = "Save Cancel"
        data["snapshot"] = {"ref": "ref_a", "dom_hash": "sha256xyz"}
        ev = RecordedEvent.model_validate(data)
        self.assertEqual(ev.ancestors[0].tag, "div")
        self.assertEqual(ev.surrounding_text, "Save Cancel")
        self.assertEqual(ev.snapshot.ref, "ref_a")
        self.assertEqual(ev.snapshot.dom_hash, "sha256xyz")


# ─── Phase 3: LLM selector generator ──────────────────────────────────────────


class SelectorValidationTests(unittest.TestCase):
    def test_rejects_xpath(self):
        self.assertTrue(is_obviously_invalid("//div[@id='x']"))
        self.assertTrue(is_obviously_invalid("/html/body/button"))

    def test_rejects_generic_tag(self):
        self.assertTrue(is_obviously_invalid("button"))
        self.assertTrue(is_obviously_invalid("div"))

    def test_accepts_stable_selectors(self):
        self.assertFalse(is_obviously_invalid("[data-testid=submit]"))
        self.assertFalse(is_obviously_invalid("button.primary"))
        self.assertFalse(is_obviously_invalid("#email-input"))

    def test_validate_against_html(self):
        html = '<html><body><button data-testid="x">A</button><input name="email"/></body></html>'
        ok, n = validate_selector('[data-testid="x"]', html)
        self.assertTrue(ok)
        self.assertEqual(n, 1)
        ok, n = validate_selector('input[name="email"]', html)
        self.assertTrue(ok)

    def test_validate_rejects_no_match(self):
        html = "<html><body><span/></body></html>"
        ok, _ = validate_selector('[data-testid="missing"]', html)
        self.assertFalse(ok)


class CandidateRankingTests(unittest.TestCase):
    def test_testid_outranks_class(self):
        c1 = SelectorCandidate("button.btn", 1, "", "")
        c2 = SelectorCandidate("[data-testid=submit]", 3, "", "")
        c3 = SelectorCandidate("[aria-label=Save]", 2, "", "")
        ranked = rank_candidates([c1, c2, c3])
        self.assertEqual(ranked[0].selector, "[data-testid=submit]")
        self.assertEqual(ranked[1].selector, "[aria-label=Save]")


class TaskFromEventTests(unittest.TestCase):
    def test_extracts_bbox_and_snapshot(self):
        ev = {
            "action": {"action": "fill"},
            "target": {"tag": "input", "classes": [], "placeholder": "Email"},
            "visual": {"bbox": {"x": 5, "y": 10, "w": 200, "h": 30}},
            "ancestors": [{"tag": "form", "id": "login", "classes": [], "outer_html": ""}],
            "surrounding_text": "Email Password",
            "snapshot": {"ref": "ref1", "dom_hash": "abcd"},
        }
        task = task_from_recorded_event(ev, 7)
        self.assertEqual(task.step_index, 7)
        self.assertEqual(task.snapshot_hash, "abcd")
        self.assertEqual(task.action_type, "fill")
        self.assertEqual(task.element_bbox["w"], 200)
        self.assertEqual(task.target_dom["placeholder"], "Email")


# ─── Phase 4: tier metrics + promotion ────────────────────────────────────────


class TierMetricsTests(unittest.TestCase):
    def test_distribution_sums_to_one(self):
        tm = TierMetrics()
        for _ in range(7):
            tm.record(TIER_COMPILED)
        for _ in range(2):
            tm.record(TIER_A11Y)
        tm.record(TIER_LLM_RECOVERY)
        snap = tm.snapshot()
        self.assertAlmostEqual(sum(snap["distribution"].values()), 1.0, places=4)
        self.assertEqual(snap["distribution"][TIER_COMPILED], 0.7)
        self.assertEqual(snap["recovery_rate"], 0.1)

    def test_ignores_unknown_tier(self):
        tm = TierMetrics()
        tm.record("garbage")
        self.assertEqual(tm.snapshot()["total"], 0)


class PromotionStateTests(unittest.TestCase):
    def test_promotes_after_five_wins(self):
        ps = _PromotionState()
        results = [ps.record_success("s", 0, "[data-testid=x]") for _ in range(5)]
        self.assertEqual(results, [False, False, False, False, True])

    def test_reset_clears_counter(self):
        ps = _PromotionState()
        for _ in range(3):
            ps.record_success("s", 0, "[data-testid=x]")
        ps.reset("s", 0, "[data-testid=x]")
        # After reset, the next success starts again at 1.
        self.assertFalse(ps.record_success("s", 0, "[data-testid=x]"))


class EscalationQueueTests(unittest.TestCase):
    def test_escalation_logged(self):
        initial = len(escalation_queue.pending())
        escalate_step_failure(
            skill_id="sk_e",
            step_index=1,
            step={"action": "click"},
            error_summary="all tiers failed",
            tier_attempts=[{"tier": "tier1_compiled", "ok": False}],
        )
        pending = escalation_queue.pending()
        self.assertEqual(len(pending), initial + 1)
        last = pending[-1]
        self.assertEqual(last["skill_id"], "sk_e")
        self.assertTrue(last["context"]["compile_required"])


# ─── Workflow intent graph ────────────────────────────────────────────────────


class WorkflowIntentGraphTests(unittest.TestCase):
    def test_graph_default_empty(self):
        pkg = SkillPackage(meta=SkillMeta(id="x"), skills=[SkillBlock(steps=[])])
        self.assertEqual(pkg.intent_graph.goal, "")
        self.assertEqual(pkg.intent_graph.steps, [])

    def test_graph_serializes(self):
        g = WorkflowIntentGraph(
            goal="Add a contact",
            steps=[WorkflowIntentStep(index=0, intent="click add", verification_anchor="modal_open")],
        )
        s = g.model_dump()
        self.assertEqual(s["goal"], "Add a contact")
        self.assertEqual(s["steps"][0]["intent"], "click add")


if __name__ == "__main__":
    unittest.main()
