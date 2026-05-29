"""Tests for compound validation.wait_for {op, conditions}."""

from __future__ import annotations

import unittest

from app.compiler.wait_for_shape import (
    destructive_wait_for_is_non_none,
    is_wait_group,
    leaf_wait_for_conditions,
    wait_for_combinator,
)


class WaitForShapeTests(unittest.TestCase):
    def test_legacy_single(self) -> None:
        wf = {"type": "url_change", "target": "", "timeout": 5000}
        self.assertIsNone(wait_for_combinator(wf))
        self.assertEqual(len(leaf_wait_for_conditions(wf)), 1)
        self.assertTrue(destructive_wait_for_is_non_none(wf))

    def test_compound_or_one_branch(self) -> None:
        wf = {
            "op": "or",
            "conditions": [
                {"type": "url_change", "target": "", "timeout": 5000},
                {"type": "none", "target": "", "timeout": 5000},
            ],
        }
        self.assertEqual(wait_for_combinator(wf), "or")
        self.assertTrue(destructive_wait_for_is_non_none(wf))

    def test_compound_and_requires_all(self) -> None:
        wf = {
            "op": "and",
            "conditions": [
                {"type": "url_change", "target": "", "timeout": 5000},
                {"type": "none", "target": "", "timeout": 5000},
            ],
        }
        self.assertFalse(destructive_wait_for_is_non_none(wf))

    def test_compound_and_all_non_none(self) -> None:
        wf = {
            "op": "and",
            "conditions": [
                {"type": "url_change", "target": "", "timeout": 5000},
                {"type": "element_appear", "target": "#x", "timeout": 5000},
            ],
        }
        self.assertTrue(destructive_wait_for_is_non_none(wf))

    def test_nested_or_inside_and(self) -> None:
        wf = {
            "op": "and",
            "conditions": [
                {
                    "op": "or",
                    "conditions": [
                        {"type": "url_change", "target": "", "timeout": 5000},
                        {"type": "element_appear", "target": "#d", "timeout": 3000},
                    ],
                },
                {"type": "dom_change", "target": "", "timeout": 2000},
            ],
        }
        self.assertTrue(is_wait_group(wf))
        leaves = leaf_wait_for_conditions(wf)
        self.assertEqual(len(leaves), 3)
        self.assertTrue(destructive_wait_for_is_non_none(wf))


if __name__ == "__main__":
    unittest.main()
