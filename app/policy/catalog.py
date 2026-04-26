"""Per-module catalog of former hardcoded sites and their policy-driven replacements."""

from __future__ import annotations

from typing import Any

from app.policy.interfaces import ReplacementTarget

# Each entry documents a migration site; runtime behavior is driven by default_policy.json.
HARDENED_SITE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "compiler_v3_submit_heuristic",
        "module": "app.compiler.v3",
        "category": "workflow",
        "replacement": ReplacementTarget.SUBMIT_DETECTION,
        "notes": "Submit-like clicks inferred from policy tokens + button semantics, not login-only lists.",
    },
    {
        "id": "compiler_v3_step_order",
        "module": "app.compiler.v3",
        "category": "workflow",
        "replacement": ReplacementTarget.WORKFLOW_ORDERING,
        "notes": "Recording order preserved; optional same-target focus-before-type insert only (no dependency reorder).",
    },
    {
        "id": "compiler_v3_selector_ranks",
        "module": "app.compiler.v3",
        "category": "selector",
        "replacement": ReplacementTarget.SELECTOR_PRIORITY,
        "notes": "Selector ranking uses policy base scores + stability heuristics.",
    },
    {
        "id": "compiler_v3_validation_login",
        "module": "app.compiler.v3",
        "category": "validation",
        "replacement": ReplacementTarget.VALIDATION_STATIC,
        "notes": "Success conditions derived from state_diff; no /login or dashboard literals.",
    },
    {
        "id": "validation_planner_channel_scores",
        "module": "app.compiler.validation_planner",
        "category": "validation",
        "replacement": ReplacementTarget.VALIDATION_STATIC,
        "notes": "Commit-click wait_for from policy channel_weights + state_diff; SPA default via commit_no_evidence_wait.",
    },
    {
        "id": "pipeline_selectors_canonical_order",
        "module": "app.pipeline.selectors",
        "category": "selector",
        "replacement": ReplacementTarget.SELECTOR_PRIORITY,
        "notes": "Canonical order and primary kind from policy + scored reordering metadata.",
    },
    {
        "id": "pipeline_semantic_email_password",
        "module": "app.pipeline.run",
        "category": "intent",
        "replacement": ReplacementTarget.INTENT_RULES,
        "notes": "input_type inference from configurable regex detectors, not two fixed branches.",
    },
    {
        "id": "semantic_llm_login_fallback",
        "module": "app.llm.semantic_llm",
        "category": "intent",
        "replacement": ReplacementTarget.INTENT_RULES,
        "notes": "Generic semantic slug from element + text tokens; confidence from policy table.",
    },
    {
        "id": "confidence_constants_inline",
        "module": "app.confidence.layered",
        "category": "recovery",
        "replacement": ReplacementTarget.CONFIDENCE_THRESHOLDS,
        "notes": "Thresholds/scorer weights resolved from step confidence_protocol / policy bundle.",
    },
    {
        "id": "recovery_block_static",
        "module": "app.compiler.build",
        "category": "recovery",
        "replacement": ReplacementTarget.RECOVERY_FIXED,
        "notes": "RecoveryBlock defaults from recovery_defaults + intent family strategies.",
    },
    {
        "id": "recorder_bridge_limits",
        "module": "app.recorder.bridge.js",
        "category": "signal",
        "replacement": ReplacementTarget.SIGNAL_CAPTURE,
        "notes": "Depth/debounce/slice limits from injected capture_profile.",
    },
    {
        "id": "audit_empty_css_only",
        "module": "app.confidence.uncertainty",
        "category": "selector",
        "replacement": ReplacementTarget.SELECTOR_PRIORITY,
        "notes": "Structural audit requires any resolved primary selector kind, not css-only.",
    },
]
