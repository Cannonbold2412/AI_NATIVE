# Conxa Production Architecture

## System Overview

Conxa is a marketplace for AI-native automation plugins. Workflows are recorded from real browser interactions, compiled into structured skills, and executed by AI agents with self-healing recovery.

---

## Folder Structure

```
app/
├── api/                    HTTP routes (FastAPI)
│   ├── routes.py           Recorder, compile, skill CRUD, patch
│   ├── execution_routes.py Execution lifecycle: status, pause, resume, cancel, trace
│   ├── run_routes.py       Plugin run event ingestion
│   ├── workflow_routes.py  Workflow editor API
│   ├── skill_pack_routes.py  Skill package build/export
│   └── plugin_routes.py   Plugin management
│
├── auth/
│   └── session_manager.py  Auth session lifecycle: validate, save, clear
│
├── compiler/               Phase 3: events → SkillPackage
│   ├── build.py            compile_skill_package() — orchestrator
│   ├── validation_planner.py  Multi-assertion compilation
│   ├── action_policy.py    Recovery gating per action type
│   ├── patch.py            1-click step fix (apply_step_patch)
│   └── recovery_policy.py  Default recovery blocks
│
├── execution/              Execution lifecycle + observability
│   ├── lifecycle.py        State machine: idle→running→paused→completed/failed
│   ├── checkpoint.py       Step-level checkpoint for pause/resume
│   ├── drift_detector.py   Pre-execution environment drift check
│   └── trace.py            Per-step trace JSONL + aggregation
│
├── models/
│   ├── skill_spec.py       SkillPackage, SkillStep, ElementFingerprint, Assertion
│   └── events.py           RecordedEvent schema
│
├── pipeline/               Phase 2: normalize recorded events
│   └── run.py              run_pipeline() — dedupe, enrich, clean
│
├── recorder/               Phase 1: Playwright capture
│   ├── session.py          RecordingSession class
│   └── bridge.js           In-page event capture (injected into browser)
│
└── storage/
    └── plugin_templates/
        └── runtime/        Distributed runtime (installed in ~/.conxa/runtime/)
            ├── run.js      Step executor + fingerprint-scored recovery
            ├── server.js   MCP server (Claude Code integration)
            └── cli.js      Plugin manager CLI

frontend/                   Next.js workflow editor UI
```

---

## System Boundaries

### 1. Recording → Processing → Compilation (offline, deterministic)

```
Browser interaction
    ↓
bridge.js (in-page)
    → serializes target, selectors, DOM diff, stable attributes
    → emits to __skillReport binding
    ↓
RecordingSession (Python/Playwright)
    → saves RecordedEvent to events.jsonl + screenshots
    ↓
run_pipeline() — Phase 2
    → normalize, dedupe, enrich
    ↓
compile_skill_package() — Phase 3
    → builds ElementFingerprint (stable identity)
    → builds Assertion[] (multi-assertion outcome validation)
    → builds RecoveryBlock (anchors + strategies)
    → builds SkillMeta.structural_fingerprint (drift detection baseline)
    → outputs SkillPackage JSON
```

### 2. Runtime Execution (production)

```
Claude Agent / User
    → calls MCP tool: execute_plan (async: true → get execution_id)
    → polls: get_execution_status(execution_id)
    ↓
server.js
    → validates auth session (getCachedBrowser with storage_state)
    → calls runPlan(page, steps, inputs, startFrom, slug)
    ↓
runPlan (run.js)
    For each step:
    1. Poll pause signal (pause/resume support)
    2. waitForStable() — adaptive timing, no fixed sleeps
    3. waitForUrlState() — pre-step URL gate
    4. executeStep() — primary action
    5. If primary fails → resolveElement() [fingerprint scoring]
       - Score all candidates against ElementFingerprint
       - Pick highest-scoring above 0.45 threshold
       - Dialog-scoped → fuzzy tag+text (last resort)
    6. verifyAssertions() — outcome verification
       - url_pattern | url_changed | selector_present | text_present
       - Required assertions halt execution
       - Advisory assertions log warnings
    7. writeCheckpoint() — step-level recovery point
```

---

## Iframe Pipeline

Conxa fully supports recording and executing actions inside nested iframes. Here's how iframe-recorded actions flow through the complete pipeline:

### Stage 1 — Recording (bridge.js + session.py)

`bridge.js` is injected into every browser frame (mainframe + all iframes):
- Guard `if (window.__SKILL_BRIDGE_V1__) return;` prevents double-install
- Each frame independently captures events: click, type, select, hover, drag_drop, keyboard_shortcut, date_pick, etc.
- On action completion, `finalizeState()` calls `window.__skillReport(payload)` Playwright binding

`_binding_sink_sync()` (session.py:421) receives Playwright binding callback with `source.frame`:
- Calls `_frame_context_and_offset_sync(src_frame)` (session.py:122–157)
- Walks up the iframe parent chain:
  - For each iframe element: reads `id`, `data-test-id`, `data-selenium-test`, `name`, `title`, `aria-label`, `src`
  - Generates selectors via `_iframe_selectors_from_attrs()` (session.py:69–75)
  - Extracts `url` (iframe src) and generates `url_pattern` regex
  - Builds `{ selector, fallback_selectors[], url, url_pattern }` dict per layer
- Accumulates `offset.x/y` so all bounding boxes are in **page-level coordinates** (not frame-local)
- Returns `FrameContext` with `chain[]` list ordered outermost→innermost

Output written to `events.jsonl`:
```json
{
  "action": "click",
  "target": { "selector": "button.submit" },
  "frame": {
    "chain": [
      {
        "selector": "iframe#payment-form",
        "fallback_selectors": ["iframe[name='checkout']", "iframe[src*='pay.example.com']"],
        "url": "https://pay.example.com/embed",
        "url_pattern": "^https://pay\\.example\\.com/embed.*"
      }
    ]
  }
}
```

### Stage 2 — Normalize (pipeline/run.py)

Frame chain passes through `RecordedEvent.model_validate()` unchanged:
- No transformation applied
- Chain is preserved verbatim in normalized event
- `FrameContext` validated by Pydantic, empty selectors allowed (filtered downstream)

### Stage 3 — Compile (compiler/build.py)

`_build_frame_context(ev)` (build.py:112–130) **transforms** the chain:
- **Filters** chain entries with empty `selector`
- **Caps** `fallback_selectors` at 5 per entry
- **Sanitizes** `selector` and `url` strings (strips whitespace)
- Returns `{}` (empty dict) if chain is empty or all selectors are empty
- Stores result in `SkillStep.frame`

`frame_enter` and `frame_exit` actions get `no_recovery_block` (no retry on these marker types).

Compiled output (part of `SkillStep`):
```json
{
  "action": "click",
  "target": { "selector": "button.submit" },
  "frame": {
    "chain": [
      {
        "selector": "iframe#payment-form",
        "fallback_selectors": ["iframe[name='checkout']", "iframe[src*='pay.example.com']"],
        "url": "https://pay.example.com/embed",
        "url_pattern": "^https://pay\\.example\\.com/embed.*"
      }
    ]
  }
}
```

### Stage 4 — Build (plugin_builder.py)

`_sanitize_runtime_frame()` (plugin_builder.py:168–185):
- Removes empty values (empty strings, None)
- Caps chain entries
- Writes frame context into `execution.json` per step (identical structure to compiled form)

Runtime-ready step in `execution.json`:
```json
{
  "action": "click",
  "target": { "selector": "button.submit" },
  "frame": {
    "chain": [
      {
        "selector": "iframe#payment-form",
        "fallback_selectors": ["iframe[name='checkout']"],
        "url": "https://pay.example.com/embed",
        "url_pattern": "^https://pay\\.example\\.com/embed.*"
      }
    ]
  }
}
```

### Stage 5 — Execution (run.js)

`frameChain(step)` extracts `step.frame.chain[]` (or returns `[]` if no frame context).

`rootCandidates(page, step, inputs)` (run.js:103–122) walks the frame chain depth-first:
- Starts with `[page]` (mainframe)
- For each chain entry, calls `root.frameLocator(selector)` for each root
  - Playwright's `frameLocator()` navigates into the iframe (innermost for nested frames)
  - Returns a `FrameLocator` object (not a Locator)
- Accumulates results; if any chain entry has zero results, stops and falls back to `[page]`
- Returns `[frameLocator]` for innermost frame, or `[page]` if chain empty or not found

All interactive actions (click, fill, etc.) call `withLocator()` which:
1. Converts `FrameLocator` to `Locator` via `locatorCandidates()`
2. Tries each candidate with `loc.first().click()` / `loc.fill()` etc.
3. Falls back to main page if all candidates fail
4. If the step has a frame context and all candidates fail, logs `frame_context_failed` event to recovery log

Explicit iframe handling:
- `frame_enter` validates that the iframe chain can be reached; throws error if not found (logs `frame_enter_failed`)
- `frame_exit` marks the point where we leave the iframe context (logs `frame_exited`)
- Both actions log to recovery.log for full observability

**Recovery signals**:
- `frame_not_found` — logged when a frameLocator chain entry returns zero results (selector did not match any iframe)
- `frame_context_failed` — logged when element action fails inside an iframe (action succeeded on main page but not within the frame)
- `frame_enter_failed` — logged when explicit frame_enter step finds no matching iframe
- `frame_entered` — logged when frame_enter step successfully navigates to an iframe

---

## Data Contracts

### ElementFingerprint (compiled into each SkillStep)
```json
{
  "role": "button",
  "tag": "button",
  "inner_text": "Sign In",
  "aria_label": "Sign in to your account",
  "name": "",
  "placeholder": "",
  "data_testid": "signin-btn",
  "input_type": "",
  "css_class_tokens": ["btn", "primary"],
  "anchor_phrases": ["Login form", "Email field"],
  "position_hint": { "x_pct": 0.5, "y_pct": 0.7 }
}
```

### Assertion (compiled into ValidationBlock.assertions)
```json
[
  { "type": "url_pattern",    "target": "^https://app.example.com/dashboard.*", "timeout_ms": 10000, "required": true },
  { "type": "selector_present","target": ".welcome-banner",                     "timeout_ms": 5000,  "required": false }
]
```

### Execution State (lifecycle.py)
```json
{
  "execution_id": "uuid",
  "skill_id": "skill_abc",
  "state": "running",
  "current_step": 4,
  "total_steps": 12,
  "created_at": "2026-05-22T10:00:00Z",
  "updated_at": "2026-05-22T10:00:15Z",
  "error": null,
  "result": null
}
```

### Step Trace Record (trace.jsonl)
```json
{
  "execution_id": "uuid",
  "step_index": 3,
  "step_type": "click",
  "intent": "click_submit_button",
  "started_at": "2026-05-22T10:00:12Z",
  "completed_at": "2026-05-22T10:00:13Z",
  "duration_ms": 847.3,
  "outcome": "recovered",
  "recovery_via": "fingerprint_scored",
  "recovery_score": 0.82,
  "assertion_warnings": [],
  "page_url_after": "https://app.example.com/dashboard"
}
```

---

## Runtime Recovery Cascade

```
executeStep(primary)
    ↓ fail
resolveElement()
    ├─ Score fallback_selectors against ElementFingerprint
    ├─ Score anchor text selectors
    ├─ Score data-testid / aria-label derived selectors
    ├─ Dialog-scoped: [role="dialog"] primary
    └─ Fuzzy tag+text DOM scan
        ↓ best score ≥ 0.45
executeStep(resolved selector)
    ↓ fail
Throw enriched error (failedAt, preShot)
    → L4: vision (MCP: returns pre-step + reference screenshot)
    → L5: intent (MCP: returns interactive element map)
```

---

## Authentication Architecture

- Each plugin has `~/.conxa/plugins/{slug}/auth/auth.json` (Playwright storageState)
- Auth state is loaded into BrowserContext before execution
- `session_manager.py` validates auth by navigating to `protected_url`
- On session expiry: re-auth skill must be run, then execution resumes
- Auth credentials never pass through skill steps (stored separately, not in git)

---

## Observability

| What             | Where                                              |
|------------------|----------------------------------------------------|
| Step trace       | `~/.conxa/data/executions/{id}/trace.jsonl`        |
| Execution state  | `~/.conxa/data/executions/{id}/state.json`         |
| Checkpoint       | `~/.conxa/data/executions/{id}/checkpoint.json`    |
| Recovery events  | `~/.conxa/recovery.log` (JSONL, 10MB rotation)     |
| Plugin run log   | `~/.conxa/data/runs/{plugin}.jsonl`                |

API endpoints:
- `GET /api/v1/executions` — list all executions
- `GET /api/v1/executions/{id}` — execution status + checkpoint
- `GET /api/v1/executions/{id}/trace` — step-level trace + aggregate stats
- `POST /api/v1/executions/{id}/pause` — pause at next step boundary
- `POST /api/v1/executions/{id}/resume` — resume from checkpoint
- `POST /api/v1/executions/{id}/cancel` — cancel

---

## MCP Integration (Claude Code)

Tools exposed via `server.js`:

| Tool                  | Description                                              |
|-----------------------|----------------------------------------------------------|
| `list_skills`         | Enumerate installed plugins and skills                   |
| `execute_plan`        | Run skills (sync or async: true for polling mode)        |
| `get_execution_status`| Poll execution progress, step count, errors              |
| `pause_execution`     | Pause at next step boundary                              |
| `resume_execution`    | Resume from checkpoint                                   |
| `cancel_execution`    | Cancel running/paused execution                          |
| `read_skill_files`    | Debug: inspect raw execution steps                       |
| `search_registry`     | Search plugin registry                                   |
| `install_plugin`      | Install from git/registry/local path                     |

Async flow:
```
Claude → execute_plan({ skills, async: true })
       ← { execution_id, status: "starting" }
Claude → get_execution_status({ execution_id })  (every 30s)
       ← { status: "running", step_current: 4, step_total: 12 }
Claude → get_execution_status({ execution_id })
       ← { status: "completed", result: { url, screenshot_b64 } }
```

---

## Migration Plan

### From current to production-ready

**Phase 1 (complete): Durable Element Identity + Outcome Validation**
- ElementFingerprint compiled into every SkillStep
- Assertion[] compiled into every ValidationBlock
- run.js: resolveElement() scoring replaces sequential L1→L3b
- run.js: verifyAssertions() after every action

**Phase 2 (complete): Execution Lifecycle**
- lifecycle.py: state machine (idle→running→paused→completed/failed)
- checkpoint.py: step-level recovery point
- API: /executions/{id}/pause, /resume, /cancel
- run.js: pause/resume via control file polling

**Phase 3 (complete): Adaptive Timing**
- run.js: waitForStable() replaces fixed 1.5s/3.5s sleeps
- networkIdle for navigate steps, DOM-stable for interactive steps

**Phase 4 (complete): Auth Decoupling**
- auth/session_manager.py: validate, save, clear session state
- Auth validation before execution, session scoped per plugin

**Phase 5 (complete): Observability**
- execution/trace.py: step-level JSONL trace with duration + outcome
- aggregate_trace(): failure rate, recovery rate, p50/p95 duration
- GET /executions/{id}/trace API

**Phase 6 (complete): MCP Enhancement**
- server.js: async execute_plan with execution_id + polling
- get_execution_status, pause, resume, cancel MCP tools
- In-memory execution registry in server.js

**Phase 7 (complete): Recording Improvements**
- bridge.js: buildStableSelector() — data-testid first priority
- bridge.js: interactiveSignature() + _computeDomDiff() — captures DOM changes after each action
- Compiler: _build_structural_fingerprint() in SkillMeta for drift detection

---

## Testing Strategy

### Unit tests
- `app/compiler/build.py`: test _build_element_fingerprint() extracts data-testid correctly
- `app/compiler/build.py`: test _build_assertions() produces correct assertion types
- `app/execution/lifecycle.py`: test state transitions, invalid transitions raise ValueError
- `app/execution/checkpoint.py`: test read/write/clear round-trip
- `app/execution/trace.py`: test append_step_trace + aggregate_trace

### Integration tests
- Full compile_skill_package() run with mock events → verify ElementFingerprint populated
- run.js: mock Playwright page, test resolveElement() scoring logic
- run.js: test verifyAssertions() with url_pattern, selector_present, text_present

### End-to-end tests (against real sites in CI)
- Login workflow: test that fingerprint scoring recovers when CSS class changes
- Form fill: test that assertion catches wrong URL after submit
- Pause/resume: test execution can pause mid-workflow and resume from correct step

### Drift detection test
- Record workflow against a site, modify the site's HTML, run drift_checker
- Assert drift_score > 0.5 when landmark selectors are gone
- Assert safe_to_proceed = True when drift_score < 0.5
