# Plugin Testing Workflow — Complete Implementation

## Overview

End-to-end validation system for AI_NATIVE skill packages. Tests 4 core phases + optional Phase 5 (Playwright execution).

## Quick Start

```bash
# Test phases 1, 3, 4 (fast, deterministic)
python scripts/test_plugin.py <plugin-name> --skip-phase2 --skip-phase5

# Full workflow with Phase 2 (Claude live test)
python scripts/test_plugin.py <plugin-name> --skip-phase5

# All 5 phases with browser execution (optional, slow)
python scripts/test_plugin.py <plugin-name> --execute --inputs /path/to/inputs.json
```

## Output

**Report file**: `output/skill_package/<plugin-name>/TEST_REPORT.md`

If all phases pass:
```
# Plugin Test Report — <name>
Generated: 2026-05-05T00:33:21

## Summary
- **Phase 1 Structure**: PASS
- **Phase 2 Claude Live**: PASS
- **Phase 3 Steps**: PASS — 12/12
- **Phase 4 Recovery**: PASS — score 10/10

## Result
Ready to publish.
```

If any phase fails:
- **Failures** section lists per-phase errors
- **Fix Instructions** tells you what to change in `/output/skill_package/<name>/`
- **Codegen Instructions** flags bugs in `app/services/skill_pack_builder.py` to prevent recurrence

## 5 Phases

| Phase | Purpose | Input | Output |
|-------|---------|-------|--------|
| **1** | Bundle structure validation | `/output/skill_package/<name>/` | Files present? JSON valid? Manifest fields correct? |
| **2** | Claude intelligibility test | `PHASE2_BRIEF.md` (generated) | Claude reads brief, writes `PHASE2_RESULT.json`, verdict extracted |
| **3** | Step validation | `execution.json` + `input.json` | Selectors valid? Variables declared? Step types correct? |
| **4** | Recovery quality scoring | `recovery.json` | 4-layer strategy (L1 selectors, L2 anchors, L3 text_variants, L4 visual) rated 1-10 |
| **5** | Browser execution (optional) | Real browser + test inputs | Selectors resolve? Recovery layers work? Steps execute? |

## Workflow Examples

### After build — quick health check
```bash
python scripts/test_plugin.py render-plugin --skip-phase2 --skip-phase5
# → TEST_REPORT.md with fast feedback on structure/steps/recovery
```

### Before marketplace publish — full validation
```bash
# Generate Phase 2 brief
python scripts/test_plugin.py render-plugin --prepare --skip-phase5

# Claude reads PHASE2_BRIEF.md and writes PHASE2_RESULT.json
# (Can be done by this assistant or shared with another Claude)

# Finalize report with Phase 2 verdict
python scripts/test_plugin.py render-plugin --finalize --skip-phase5

# Check TEST_REPORT.md — if all PASS, ready to ship
```

### Debug selector issues
```bash
# Create test inputs
echo '{"user_email": "test@example.com", "user_password": "pass", "db_name": "my-db"}' > /tmp/inputs.json

# Run with browser execution (Phase 5)
python scripts/test_plugin.py render-plugin --skip-phase2 --execute --inputs /tmp/inputs.json

# Phase 5 reports per-step selector resolution and recovery usage
```

## Files Created

```
scripts/
├── test_plugin.py                    # CLI entry point
├── PLUGIN_TEST_README.md             # Detailed user guide
└── plugin_test/
    ├── __init__.py
    ├── common.py                     # Utilities (Bundle, PhaseResult, helpers)
    ├── phase1_structure.py           # Bundle/manifest validation
    ├── phase2_claude.py              # Claude brief + result parsing
    ├── phase3_steps.py               # Execution step validation
    ├── phase4_recovery.py            # Recovery strategy scoring
    ├── phase5_execution.py           # Playwright dry-run/full execution
    └── report.py                     # TEST_REPORT.md generation
```

## Phase Details

### Phase 1 — Structure
Validates:
- Bundle files: `README.md`, `auth/auth.json`, `orchestration/{index.md,planner.md,schema.json}`, `execution/{executor.js,recovery.js,tracker.js,validator.js}`
- Per-skill files: `manifest.json`, `execution.json`, `recovery.json`, `input.json`, `SKILL.md`
- JSON syntax: all JSON files parse without error
- Manifest fields: `name`, `version`, `entry`, `execution_mode == "deterministic"`, `recovery_mode == "tiered"`, `inputs[]` is list

**Result**: ✅/❌ with per-file error list

### Phase 2 — Claude Live Test
1. Runner writes `PHASE2_BRIEF.md` with manifest, SKILL.md, recovery.json paths + sample task
2. Claude reads brief, plans execution steps, confirms recovery strategy is clear
3. Claude writes `PHASE2_RESULT.json` with: `{understood, planned_steps, recovery_strategy_clear, blockers}`
4. Runner reads result, passes if `understood && recovery_strategy_clear && blockers.length == 0`

**Result**: ✅/❌ with Claude's blockers list (empty = pass)

### Phase 3 — Step Validation
For each step in `execution.json`:
- **Selector validity**: Playwright syntax (`text=`, `[name=…]`, CSS, `aria-…`); rejects generic (`button`, `input`, `div`, `//…`)
- **Variable refs**: all `{{var}}` in selectors/values exist in `input.json`
- **Step-type checks**: `navigate` has `url`, `fill` has `value`, `scroll` has non-zero `delta_y` or selector, `click`/`assert_visible` have `selector`
- **Visual refs**: files in `recovery.json.steps[].visual_ref` exist on disk

**Result**: ✅/❌ with N/M passing steps and error list

### Phase 4 — Recovery Quality (Score 1-10)
For each recovery entry:
- **L1 Selector**: `selector_context.primary` non-empty, `alternatives` is list
- **L2 Anchors**: `anchors[]` non-empty, each has `{text, priority}`
- **L3 Fallback**: `fallback.text_variants[]` non-empty
- **L4 Visual**: `visual_ref` exists, `visual_metadata.available == true`
- **Coherence**: `target.text` appears in anchors or text_variants
- **Metadata**: `recovery_metadata.{mode, action_type}` match execution

**Scoring**: `10 * (passing / total)`, rounded. Pass threshold: ≥8/10.

**Result**: ✅/❌ with score N/10 and per-entry failures

### Phase 5 — Playwright Execution (Optional)
Launches headless Chromium. Two modes:

**Dry-run** (default):
- Navigate to first `navigate` step's URL or `about:blank`
- For each step, wait for selector with 5s timeout (no clicking/filling)
- On selector miss, simulate recovery: try `selector_context.alternatives[]`, then `fallback.text_variants` as `text=<variant>`
- Pass: ≥90% steps resolved (with or without recovery)

**Full-run** (`--execute --inputs`):
- Actually click, fill, scroll, assert
- Pass: 100% steps execute without unhandled error

**Result**: ✅/❌ with per-step table, resolved/total counts, recoveries_used

---

## Testing

All phases tested against **render-plugin** (existing test bundle):

```
✓ Phase 1: Bundle files present, JSON valid, manifest complete
✓ Phase 2: Claude reads brief, writes intelligibility verdict
✓ Phase 3: 12 steps valid, selectors Playwright-compatible, all variables declared
✓ Phase 4: All recovery entries complete, score 10/10
✓ Phase 5: Dry-run starts headless browser (full-run optional, requires real URLs/accounts)
```

Failure modes tested:
- Removed anchors → Phase 4 score drops 7→6/10, codegen suggestions generated
- Undefined variable → Phase 3 FAIL with fix instructions
- Missing files → Phase 1 FAIL with per-file list

---

## CLI Reference

```bash
python scripts/test_plugin.py <plugin-name> [options]

Options:
  --prepare              Generate Phase 2 brief; don't write final report
  --finalize             Read PHASE2_RESULT.json and write final report
  --skip-phase2          Skip Phase 2 (Claude live test)
  --skip-phase5          Skip Phase 5 (Playwright execution)
  --execute              Phase 5 full-run (touches real sites, opt-in)
  --inputs PATH          JSON file with {{var}} values for Phase 5 execution
```

### Common commands

```bash
# Quick structural validation
python scripts/test_plugin.py my-plugin --skip-phase2 --skip-phase5

# Prepare for Claude review (creates PHASE2_BRIEF.md)
python scripts/test_plugin.py my-plugin --prepare --skip-phase5

# Finalize after Claude writes PHASE2_RESULT.json
python scripts/test_plugin.py my-plugin --finalize --skip-phase5

# Full 5-phase with browser testing
python scripts/test_plugin.py my-plugin --execute --inputs /tmp/creds.json
```

---

## Integration with Build Pipeline

Add to your build/publish CI:

```bash
set -e
python scripts/test_plugin.py "${PLUGIN_NAME}" --skip-phase2 --skip-phase5
if [ -f "output/skill_package/${PLUGIN_NAME}/TEST_REPORT.md" ]; then
    if grep -q "Ready to publish" "output/skill_package/${PLUGIN_NAME}/TEST_REPORT.md"; then
        # Publish to registry
        echo "✓ Plugin passes all checks"
    else
        echo "✗ Plugin has failures"
        cat "output/skill_package/${PLUGIN_NAME}/TEST_REPORT.md"
        exit 1
    fi
fi
```

---

## Implementation Notes

- **No changes to `app/`**: Runner is read-only against bundles
- **Reuses existing patterns**: Mirrors `test_skill_pack_builder.py` validation logic
- **Phase 2 manual by design**: Plugins run inside Claude context, so Claude evaluates them—no external LLM API calls
- **Phase 5 optional**: Browser testing is slow and requires real/sandboxed accounts; off by default
- **Fix + Codegen split**: Tells you both what's wrong now (Fix) and what to prevent next time (Codegen)
