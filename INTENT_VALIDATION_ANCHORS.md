# Intent-driven validation + semantic anchors

This document describes how intent, validation, anchors, and recovery are generated after the intent-first refactor.

## 1) Intent source of truth

Intent is produced in two stages:

1. **Pipeline enrichment (Phase 2)**  
   - `app/pipeline/run.py` → `_semantic_enrich_one()` calls `enrich_semantic(...)` from `app/llm/semantic_llm.py`.
   - This writes candidate `semantic.llm_intent`.

2. **Compiler finalization (Phase 3)**  
   - `app/compiler/build.py` → `_build_step()` calls:
     - `generate_intent_with_llm(ev)` (`app/llm/intent_llm.py`)
     - `normalize_compiler_intent(...)` (`app/policy/intent_ontology.py`)
   - Final normalized slug is stored in:
     - step-level `intent`
     - `signals.semantic.final_intent`
     - `signals.semantic.llm_intent`
   - If a pipeline candidate differs, it is preserved as `signals.semantic.intent_candidate`.

Read path is centralized in `app/compiler/intent_access.py`:
- `get_effective_intent(...)`: prefer `final_intent`, fallback `llm_intent`.

## 2) Validation (intent-driven, diff-supported)

Validation is built in `app/compiler/build.py` via:
- `_build_validation(...)` -> `validation_from_diff(...)` (`app/compiler/v3.py`) -> planner functions in `app/compiler/validation_planner.py`.

### Wait-for selection (`infer_wait_for_shape`)

Primary driver is now:
- `FINAL_INTENT + action + policy`

Supporting signal:
- `state_diff` (URL/DOM/text/element deltas)

Key behavior:
- `type/focus/fill` -> `wait_for: none`
- navigation actions -> `wait_for: url_change`
- click actions:
  - policy-defined intent facets (`decision_layer.intent_validation_facets`) can choose:
    - `url_change`
    - `dom_change`
    - `element_appear`
    - `element_disappear`
    - `none`
  - commit clicks still use diff channel scoring as fallback, but:
    - FINAL_INTENT can override no-evidence commit default through
      - `commit_intent_prefer_url_substrings`
      - `commit_intent_prefer_dom_substrings`

### Success conditions (`infer_success_conditions`)

- `state_diff` remains attached as evidence (`state_diff_as_hint`, `state_diff_strength`).
- Intent tokens from `decision_layer.intent_token_stopwords` + `intent_outcome_tokens(...)` are merged into `expected_text_tokens` when `intent_primary_validation` is on.
- Diff-derived `required_elements` are suppressed under low diff strength when intent-primary mode is active (`validation.intent_required_elements_min_diff_strength`).

## 3) Anchors (semantic + contextual)

Anchors start from recorder signals and become semantic/contextual in compiler.

### Compile-time anchor generation

In `app/compiler/v3.py`:
- `clean_anchors(...)` now accepts `target` and `semantic`.
- It keeps recorder anchors when valid, then adds semantic phrases from:
  - `context.parent`
  - `context.form_context`
  - `target.aria_label`
  - `target.placeholder`
  - `target.name`
  - `target.inner_text`
  - `semantic.normalized_text`
  - top context siblings (bounded)
- Phrase quality is controlled by `anchors.semantic_anchors` policy config.
- Generic structural fallbacks are gated by policy:
  - `allow_structural_form_fallback`
  - `allow_sibling_input_fallback`

In `app/compiler/recovery_policy.py`:
- `suggest_anchors_from_context(...)` also uses semantic contextual candidates first.
- Structural extras (`form`, `section`) are only added when allowed by policy and not redundant.
- Allowlist filtering permits both:
  - listed anchor elements
  - semantic phrases that pass `semantic_anchor_phrase_kept(...)`.

### Anchor ranking

`app/compiler/decision_layer.py` -> `rank_merged_anchors(...)` ranks merged anchors using:
- target/context overlap
- FINAL_INTENT token overlap
- scope markers (`#`, `.`, `[`, `/`, `@`)
- multi-word phrase bonus
- penalties for generic/low-information anchors

Weights are policy-driven (`decision_layer.anchor_rank_weights`).

## 4) Recovery now follows FINAL_INTENT

In `app/compiler/recovery_policy.py`:
- `default_recovery_block(...)` now includes both:
  - `intent`
  - `final_intent`
- `recovery_strategies_for_intent(...)` merges:
  - `recovery_defaults.strategies`
  - `recovery_defaults.intent_strategy_glue`
  - `decision_layer.intent_recovery_facets` via `intent_recovery_extra_strategies(...)`

In `app/compiler/patch.py` (Phase 6 patch flow):
- When LLM patch resolves/updates intent:
  - `recovery.intent` and `recovery.final_intent` are synchronized
  - recovery strategies are recomputed from `recovery_strategies_for_intent(...)`
  - `llm_reasoned_match` is appended deterministically

## 5) End-to-end flow

1. Recorder writes raw event (`anchors`, selectors, semantic hints, state probes).
2. `run_pipeline(...)` normalizes event and enriches candidate semantic intent.
3. `compile_skill_package(...)` builds each step with:
   - canonical FINAL_INTENT
   - semantic/contextual anchors + ranking
   - intent-driven validation with diff as support signal
   - FINAL_INTENT-aligned recovery block and strategies
4. API compile route runs static audit (`audit_reference`) before persistence.

## 6) File map

- **Intent**
  - `app/llm/semantic_llm.py`
  - `app/llm/intent_llm.py`
  - `app/pipeline/run.py`
  - `app/policy/intent_ontology.py`
  - `app/compiler/intent_access.py`
  - `app/compiler/build.py`

- **Validation**
  - `app/compiler/validation_planner.py`
  - `app/compiler/v3.py` (`validation_from_diff`, state snapshots/diff)
  - `app/compiler/decision_layer.py` (intent token logic + policy helpers)
  - `app/policy/default_policy.json` (`validation`, `decision_layer`)

- **Anchors**
  - `app/recorder/bridge.js`
  - `app/compiler/v3.py` (`clean_anchors`, semantic phrase helpers)
  - `app/compiler/recovery_policy.py` (`suggest_anchors_from_context`)
  - `app/compiler/decision_layer.py` (`rank_merged_anchors`)
  - `app/policy/default_policy.json` (`anchors.semantic_anchors`)

- **Recovery / patch**
  - `app/compiler/recovery_policy.py`
  - `app/compiler/patch.py`
  - `app/models/skill_spec.py` (`RecoveryBlock.final_intent`)

