# Plugin Test Runner

End-to-end validation for AI_NATIVE skill packages. Tests 5 phases:

- **Phase 1**: Bundle structure (files present, JSON valid, manifest fields correct)
- **Phase 2**: Claude live test (Claude evaluates plugin intelligibility)
- **Phase 3**: Step validation (selectors valid, variables declared, step types correct)
- **Phase 4**: Recovery quality (4-layer recovery strategy present and coherent)
- **Phase 5**: Playwright execution (selectors resolve in headless browser, optional)

## Quick Start

```bash
# Test phases 1/3/4 only (fast, deterministic)
python scripts/test_plugin.py <plugin-name> --skip-phase2 --skip-phase5

# Full workflow with Claude evaluation
python scripts/test_plugin.py <plugin-name> --prepare --skip-phase5
# Then have Claude read PHASE2_BRIEF.md and write PHASE2_RESULT.json
python scripts/test_plugin.py <plugin-name> --finalize --skip-phase5

# All phases including browser execution (requires real selectors/URLs)
python scripts/test_plugin.py <plugin-name> --skip-phase2 --execute --inputs /path/to/inputs.json
```

## Output

A report file is written to:

```
output/skill_package/<plugin-name>/TEST_REPORT.md
```

If any phase fails, the report includes:
- **Failures**: per-phase error list
- **Fix Instructions**: how to patch the output bundle
- **Codegen Instructions**: bugs in `app/services/skill_pack_builder.py` to fix

If all phases pass:
- Summary only, plus "Ready to publish" footer

## Phases

### Phase 1 — Structure
Validates:
- Required files exist: `manifest.json`, `execution.json`, `recovery.json`, `input.json`, `SKILL.md`
- Bundle root has: `README.md`, `auth/auth.json`, `orchestration/{index.md,planner.md,schema.json}`, `execution/{executor.js,recovery.js,tracker.js,validator.js}`
- All JSON parses without error
- Manifest fields: `name`, `version`, `entry`, `execution_mode == "deterministic"`, `recovery_mode == "tiered"`, `inputs[]` is a list

**Result**: ✅/❌ with file-level failures

### Phase 2 — Claude Live Test
Claude evaluates whether the plugin is intelligible by:
1. Reading `manifest.json`, `SKILL.md`, `orchestration/planner.md`, `recovery.json`
2. Planning the steps it would execute for a sample task
3. Confirming the recovery strategy (anchors/text_variants) is clear

**Workflow**:
```bash
python scripts/test_plugin.py <name> --prepare  # Writes PHASE2_BRIEF.md
# Claude reads brief, writes PHASE2_RESULT.json
python scripts/test_plugin.py <name> --finalize  # Reads result, includes in report
```

**Result**: ✅/❌ with blockers Claude reports (empty = pass)

### Phase 3 — Step Validation
Validates each step in `execution.json`:
- Selector syntax valid (Playwright: `text=`, `[name=…]`, CSS, `aria-…`)
- Rejects overly generic selectors (`button`, `input`, `div`, `//…`)
- Variables (e.g., `{{db_name}}`) are declared in `input.json`
- Step-specific: `scroll` has non-zero `delta_y` or selector; `navigate` has `url`; `fill` has `value`; `click`/`assert_visible` have `selector`
- Visual refs in `recovery.json` exist on disk

**Result**: ✅/❌ with `[step-N: error]` list and pass rate (N/M)

### Phase 4 — Recovery Quality
Validates each entry in `recovery.json.steps`:
- **L1 selector**: `selector_context.primary` non-empty, `alternatives` is a list
- **L2 anchors**: `anchors[]` non-empty, each has `text` and `priority`
- **L3 fallback**: `fallback.text_variants[]` non-empty
- **L4 visual**: `visual_ref` present on disk, `visual_metadata.available == true`
- Coherence: `target.text` appears in at least one anchor or text variant
- Metadata: `recovery_metadata.mode == "tiered"`, `action_type` matches `execution.json`

**Scoring**: `10 * (passing_entries / total_entries)`, rounded. Pass threshold: 8/10.

**Result**: ✅/❌ with score N/10 and per-entry failures

### Phase 5 — Playwright Execution (Optional)
Launches headless Chromium and validates selectors resolve. Two modes:

**Dry-run** (default): Navigate to first URL, then for each step, wait for selector to resolve (timeout 5s) without clicking/filling.
- Simulates recovery layers when a selector misses (tries alternatives, then text_variants)
- Pass: ≥ 90% of steps resolved (with or without recovery)
- Records which selectors recovered

**Full-run** (`--execute --inputs /path/to/inputs.json`): Actually clicks, fills, scrolls, asserts.
- Requires real URLs and valid inputs
- Pass: 100% of steps execute without unhandled error
- Opt-in because it touches real sites

**Result**: ✅/❌ with per-step table, resolved/total counts, recoveries used

Can be skipped with `--skip-phase5` or auto-skips if playwright not installed.

## Fix & Codegen Workflow

1. Run test, get a report with failures
2. **Fix** section tells you what's wrong in the output bundle
3. **Codegen** section flags bugs in `skill_pack_builder.py` to prevent the issue next time
4. Either manually patch the output, or fix the builder, then re-test

Example:
```
### Phase 4 Recovery
- generated_skill/recovery.json[step_id=3]: L2 anchors empty

## Codegen Instructions
- `app/services/skill_pack_builder.py::generate_recovery` (~line 1329):
  ensure anchors always include `target.text` as a fallback.
```

Fix the builder, rebuild the bundle, re-test.

## Example Workflows

### Test after each build
```bash
python scripts/test_plugin.py render-plugin --skip-phase2 --skip-phase5
```

### Full validation before publishing to marketplace
```bash
python scripts/test_plugin.py render-plugin --prepare --skip-phase5
# Share PHASE2_BRIEF.md with Claude
# Claude writes PHASE2_RESULT.json
python scripts/test_plugin.py render-plugin --finalize --skip-phase5
# Check TEST_REPORT.md
```

### Debug selector issues with live browser
```bash
echo '{"user_email": "test@example.com", "user_password": "secret", "db_name": "my-db"}' > /tmp/inputs.json
python scripts/test_plugin.py render-plugin --skip-phase2 --execute --inputs /tmp/inputs.json
# Watch per-step table in report
```

## Limitations

- Phase 5 requires `playwright` (already in project deps)
- Phase 5 full-run touches real sites — use sandbox accounts only
- Phase 2 requires Claude to manually read and respond (not auto-LLM call, by design)
- Generic selector rejection is conservative (whitelists text=, [name=], CSS, aria-…)
