# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

Conxa: a marketplace for AI-native automation plugins. Real browser workflows are recorded, compiled into structured skills with durable element identity and outcome assertions, then replayed by an MCP runtime on the user's machine with a 5-tier self-healing recovery cascade.

`docs/architecture.md` is the authoritative deep-dive. Read it before non-trivial changes to the recorder, compiler, or runtime.

## Working Principles

1. **Think before coding.** State assumptions. If multiple interpretations exist, surface them — don't silently pick one. If a simpler approach exists, call it out. If something is unclear, stop and ask.
2. **Simplicity first.** Write the minimum code needed. No speculative abstractions, no configurability for single-use code, no handling for impossible scenarios. If 200 lines could be 50, rewrite it.
3. **Surgical changes.** Touch only what the task requires. Don't refactor unrelated code; mention issues rather than fixing them. Match existing style. Every changed line must trace to the task. If your changes leave unused code, remove only what *you* introduced.
4. **Goal-driven.** Define success → implement → verify. Bug → reproduce → fix → verify. Refactor → ensure no behavior change.

### Token & file constraints
- Don't read files larger than ~25KB completely. Use `offset`/`limit`, or `grep`/`tail` to locate the relevant chunk first.
- Recorded session artifacts (`data/sessions/<id>/events.jsonl`, screenshots, compile reports) can be very large — always scope reads.

## Repository Layout

```
conxa-builder/        Electron desktop studio (Windows; records + compiles locally)
  electron/           Electron main process + React renderer (Vite + TypeScript)
  python/             Python stdio backend (spawned by Electron; imports app/ as lib)
    backend.py        JSON-RPC dispatcher
    services/         auth_service, bootstrap, installer_builder, llm_proxy_client
  pyinstaller.spec    Bundles python/ + conxa-cloud/backend/app/ into dist/backend/

conxa-cloud/          Cloud SaaS (Render + Vercel)
  backend/            FastAPI backend (Python 3.11+)
    app/              Main package
      main.py         Entrypoint; mounts every router under /api/v1
      config.py       Pydantic settings (env_prefix=SKILL_)
      db.py           SQLAlchemy session + init_db()
      worker.py       Render worker entrypoint (queue scaffold)
      api/            HTTP routes (all included under /api/v1 by main.py)
      recorder/       Phase 1: Playwright capture + injected bridge.js
      pipeline/       Phase 2: normalize / dedupe / enrich recorded events
      compiler/       Phase 3: events → SkillPackage (selectors, assertions,
                      recovery blocks, structural fingerprint)
      execution/      Lifecycle state machine, checkpoint, drift, trace
      llm/            LLM clients + multi-provider router (see ROUTER_SETUP.md)
      services/       plugin_builder, jobs, executor, saas, skill_pack/, rbac
      storage/        JSON/SQLite stores, snapshots, plugin/installer templates
      models/         Pydantic schemas: SkillPackage, RecordedEvent, Plugin
      auth/           Plugin auth session manager (Playwright storageState)
      editor/         Workflow editor service + DTOs + patch gate
      anchors/, confidence/, metrics/, policy/   Supporting modules
    requirements.txt
    build.sh, start.sh   Render build/start scripts
    Aptfile              System packages for Playwright/Chromium on Render
    ROUTER_SETUP.md      Multi-provider LLM router config
  frontend/           Next.js 16 App Router UI
    src/              Pages: Dashboard, Plugins, SkillPackBuilder, TestPlugin, …
    proxy.ts          Clerk middleware
    package.json      Clerk, TanStack Query, Tailwind 4, shadcn, Framer Motion
  scripts/
    test_plugin.py          End-to-end plugin validator (5 phases)
    PLUGIN_TEST_README.md   Phase definitions + invocation modes
    recompile_session.py    Recompile a session, dump compile report
    plugin_test/            Phase implementations imported by test_plugin.py
  tests/              pytest suite (unit + tests/integration + tests/e2e)
  pytest.ini          Sets pythonpath=backend so tests find app/

runtime/              Node.js MCP runtime (ships to ~/.conxa/runtime/)
  server.js           MCP stdio server (Claude Code integration)
  run.js              Step executor + fingerprint-scored recovery
  skill_loader.js, browser.js, auth_manager.js, sync.js, tracker.js
  package.json        @yao-pkg/pkg bundles for win/mac

data/                 Runtime state: sessions/, plugins/, skills/, saas/, cache/, chromium/
docs/architecture.md  Authoritative deep-dive: phases, iframe pipeline, recovery cascade,
                      data contracts, observability, migration phases
```

## Common Commands

### Backend

```bash
cd conxa-cloud/backend

# Install deps + Playwright Chromium
pip install -r requirements.txt
python -m playwright install chromium
# (or run ./build.sh — used by Render)

# Run the API
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# (start.sh runs the same without --reload, on $PORT)

# Tests (run from conxa-cloud/)
cd ..
pytest -q tests                              # full suite
pytest -q tests/test_pipeline_gates.py       # single file
pytest -q tests/test_phases.py::test_x -x    # single test, stop on first failure

# Recompile a previously recorded session and dump the compile report
python scripts/recompile_session.py <session_id>

# End-to-end plugin validation
# Phases 1 (structure) + 3 (steps) + 4 (recovery) — fast, deterministic
python scripts/test_plugin.py <plugin-slug> --skip-phase2 --skip-phase5
# Add Phase 5 (Playwright execution) when real selectors/URLs are wanted
python scripts/test_plugin.py <plugin-slug> --skip-phase2 --execute --inputs path/to/inputs.json
```

### Frontend

```bash
cd conxa-cloud/frontend
npm install
npm run dev       # local dev server
npm run lint      # eslint
npm run build     # production build (Vercel)
```

### Runtime (Node.js MCP)

```bash
cd runtime
npm install
npm start                     # node server.js (MCP stdio)
npm run build:win             # @yao-pkg/pkg → dist/runtime-win.exe
npm run build:mac             # @yao-pkg/pkg → dist/runtime-mac
```

### Configuration

Copy `.env.example` → `.env`. All backend settings use the `SKILL_` env prefix (see `conxa-cloud/backend/app/config.py`). LLM provider keys feed the multi-provider router — see `conxa-cloud/backend/ROUTER_SETUP.md` (Groq, Google AI Studio, and NVIDIA NIM are enabled by default).

## Architecture: The Big Picture

### Offline pipeline (record → compile → package)

```
Browser
  └─ conxa-cloud/backend/app/recorder/bridge.js      injected into every frame; captures
                                  click / type / select / hover / drag / etc.
  ↓
conxa-cloud/backend/app/recorder/session.py    Playwright binding sink; walks iframe parent
                                               chain, accumulates page-level offsets
  ↓ events.jsonl  +  screenshots
conxa-cloud/backend/app/pipeline/run.py        normalize / dedupe / enrich
  ↓
conxa-cloud/backend/app/compiler/build.py      compile_skill_package() — produces:
    • ElementFingerprint per step      (role / tag / text / aria / testid / anchors)
    • Assertion[] per step              (url_pattern, selector_present, …)
    • RecoveryBlock (anchors, fallback selectors)
    • SkillMeta.structural_fingerprint  (drift baseline)
  ↓
conxa-cloud/backend/app/services/plugin_builder.py   data-only plugin folder under
                                  output/skill_package/{slug}-plugin/
                                  (auth files are NEVER placed in build output)
```

### Runtime (production, on user machine)

```
~/.conxa/
├── runtime/                     shared Node MCP server (installed once)
├── plugins/<slug>/              data-only plugin
│   ├── plugin.json              manifest
│   ├── CLAUDE.md                Claude reads this for skill discovery
│   ├── skills/<slug>/           one folder per workflow
│   └── auth/auth.json           Playwright storageState (local only)
├── data/executions/<id>/        state.json, checkpoint.json, trace.jsonl
├── data/runs/<plugin>.jsonl     plugin run log
└── recovery.log                 JSONL, rotated at 10 MB
```

`runtime/run.js` executes each step:

1. Poll pause signal (supports pause/resume via API control file).
2. `waitForStable()` — adaptive timing, no fixed sleeps.
3. `waitForUrlState()` — pre-step URL gate.
4. `executeStep()` — primary action.
5. On failure → `resolveElement()` scores candidates against ElementFingerprint; dialog-scoped and fuzzy fallbacks if needed.
6. `verifyAssertions()` — required assertions halt execution; advisory ones log warnings.
7. `writeCheckpoint()` — step-level recovery point.

### Self-healing recovery cascade

For every action, tiers run in order; LLM only fires from Tier 3:

1. **Compiled selectors** — generated from recorded DOM at compile time.
2. **a11y tree** — role + name lookup (DOM-shift tolerant).
3. **LLM recovery** — Claude locates the element semantically on current DOM.
4. **Vision** — Claude vision model locates by screenshot.
5. **Escalation** — human review queue. No silent fallback or guessing.

Selectors are cached by `(dom_hash, bbox, model)`. Iframe context flows through every stage — see `docs/architecture.md` § "Iframe Pipeline".

### API surface

- Everything mounts under `/api/v1/*` (`conxa-cloud/backend/app/main.py`).
- Execution lifecycle: `GET /api/v1/executions`, `GET /api/v1/executions/{id}`, `POST /api/v1/executions/{id}/{pause,resume,cancel}`, `GET /api/v1/executions/{id}/trace`.
- MCP tools exposed by `runtime/server.js`: `execute_plan` (sync or `async: true`), `get_execution_status`, `pause_execution`, `resume_execution`, `cancel_execution`, `list_skills`, `read_skill_files`, `install_plugin`, `search_registry`.
- Frontend reaches the backend via the Next.js `/api/v1/*` route handler; set `API_ORIGIN` in production.

## Where to Look First

| Concern                            | Code paths                                                                  |
| ---------------------------------- | --------------------------------------------------------------------------- |
| Recorder event types               | `conxa-cloud/backend/app/recorder/bridge.js` → `app/pipeline/` → `app/compiler/build.py` → `runtime/run.js` |
| Selector compilation / scoring     | `conxa-cloud/backend/app/compiler/llm_selector_generator_v2.py`, `selector_score.py`, `selector_filters.py` |
| Runtime element resolution         | `runtime/run.js` — `resolveElement`, `withLocator`, `rootCandidates`        |
| Execution lifecycle / pause-resume | `conxa-cloud/backend/app/execution/lifecycle.py`, `checkpoint.py`; runtime pause-signal polling |
| Assertions / outcome validation    | `conxa-cloud/backend/app/compiler/validation_planner.py`; runtime `verifyAssertions()` |
| Plugin packaging                   | `conxa-cloud/backend/app/services/plugin_builder.py` (data-only output, auth excluded) |
| LLM calls                          | `conxa-cloud/backend/app/llm/client.py` → `app/llm/router.py` (multi-provider pool) |
| Frame / iframe handling            | `docs/architecture.md` § "Iframe Pipeline"; `bridge.js`, `session.py`, `build.py`, `run.js` |
| Auth / session validation          | `conxa-cloud/backend/app/auth/session_manager.py`                          |
| Frontend product shell             | `conxa-cloud/frontend/src/` (DashboardPage, PluginsPage, SkillPackBuilderPage, …) |

## Deployment

- **Backend + worker** on Render: set root directory to `conxa-cloud/backend`; build with `build.sh`, API starts via `start.sh` (`uvicorn app.main:app`). Worker entrypoint is `app/worker.py`. Required env: `SKILL_AUTH_REQUIRED=true`, Clerk issuer/JWKS, DB, Redis, Blob, Razorpay, allowed CORS origins, LLM provider keys, app URL.
- **Frontend** on Vercel: set project root to `conxa-cloud/frontend`, build `npm run build`. The Next route handler `/api/v1/*` proxies to `API_ORIGIN`. Set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` for Clerk.
- System packages for Playwright/Chromium on the API host are listed in `conxa-cloud/backend/Aptfile`.

## Key Invariants

- Auth files (`auth/auth.json`, credentials) are **local runtime state**. They are never placed in build output and never committed.
- Tier 1/2 recovery costs zero LLM tokens. LLM only fires at Tier 3+. Don't introduce silent LLM fallbacks.
- Iframe chain is preserved verbatim from recording through compile and execution; bounding boxes are page-level (offsets accumulated up the chain).
- `frame_enter` / `frame_exit` actions get `no_recovery_block` — no retry on these markers.
- All API routes live under `/api/v1`; the frontend depends on this.
