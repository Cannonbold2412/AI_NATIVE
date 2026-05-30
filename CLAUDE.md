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
packages/conxa-core/  Shared Python foundation — pip package `conxa_core`, installed by
  conxa_core/         BOTH the cloud backend and the Build Studio (one source of truth):
    config.py         Pydantic settings (env_prefix=SKILL_)
    db.py             Dual store: Postgres (cloud) / filesystem fallback (Studio); + healthcheck()
    models/           Pydantic schemas: SkillPackage, RecordedEvent, Plugin
    storage/          JSON/SQLite stores, snapshots, plugin/installer templates
    llm/              Router protocol + get/set_router singleton + HTTP client (call_llm)
    metrics/, progress.py (job-event sink), workspace.py (LOCAL_WORKSPACE_ID), skill_pack_build_log.py
  pyproject.toml      Declares package-data so templates/bridge.js ship on `pip install`

conxa-builder/        Electron desktop studio (Windows; records + compiles + builds LOCALLY)
  electron/           Electron main process + React renderer (Vite + TypeScript)
  python/             Python stdio backend (spawned by Electron; depends on conxa-core)
    backend.py        JSON-RPC dispatcher; installs the cloud proxy via conxa_core.llm.set_router
    requirements.txt  playwright, Pillow, bs4, lxml  (conxa-core installed separately)
    services/         auth_service, bootstrap, llm_proxy_client, metadata_reporter
    conxa_compile/    The local pipeline (moved out of the cloud):
      recorder/       Playwright capture + injected bridge.js
      pipeline/       Normalize / dedupe / enrich recorded events
      compiler/       Events → SkillPackage (selectors, assertions, recovery, fingerprint)
      editor/         Workflow editor service + DTOs + patch gate
      llm/            Task clients (intent/semantic/recovery/vision/anchor) + openapi_client
      anchors/, confidence/, policy/   supporting modules
      plugin_builder.py, installer_builder.py, conxa_runtime.py
  pyinstaller.spec    Collects conxa_core + conxa_compile into dist/backend/

conxa-cloud/          Thin cloud SaaS (Render + Vercel) — proxy/auth/billing/dashboard/hosting
  backend/            FastAPI backend (depends on conxa-core; NO recorder/compiler/Playwright)
    app/
      main.py         Routers + fail-fast prod config validation + /healthz, /readyz
      worker.py       Render worker entrypoint (queue scaffold)
      api/            llm_proxy, razorpay, product, publish (+installer hosting),
                      skillpack_update (runtime sync), updates, tracking, run, job, plugins, security
      llm/router.py   Multi-provider pool (Groq, Google AI Studio, NVIDIA NIM) behind the proxy
      services/       saas (billing/workspace), rbac, llm_metering, jobs (status)
    requirements.txt, build.sh, start.sh, Dockerfile, Aptfile, ROUTER_SETUP.md
  frontend/           Next.js 16 dashboard (Dashboard, Plugins, Billing, Team, Settings)
    package.json      Clerk, TanStack Query, Tailwind 4, shadcn, Framer Motion
  scripts/            recompile_session.py, test_plugin.py (compile tools; need conxa-builder/python on PYTHONPATH)
  tests/              pytest suite (core + compile + cloud)
  pytest.ini          pythonpath = backend ../conxa-builder/python ../packages/conxa-core

runtime/              Node.js MCP runtime (standalone; ships to ~/.conxa/runtime/)
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
# Install the shared foundation first (editable for dev), then the cloud deps.
pip install -e packages/conxa-core
cd conxa-cloud/backend && pip install -r requirements.txt   # (or ./build.sh — used by Render)

# Run the API (no Playwright — the cloud no longer records/compiles)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# (start.sh runs the same without --reload, on $PORT)

# Tests (run from conxa-cloud/). pytest.ini puts backend, conxa-builder/python and
# packages/conxa-core on the path, so `app`, `conxa_compile` and `conxa_core` all resolve.
cd .. && pytest -q tests

# Compile tools live with the Studio pipeline now — put conxa_compile on the path:
PYTHONPATH=../conxa-builder/python python scripts/recompile_session.py <session_id>
PYTHONPATH=../conxa-builder/python python scripts/test_plugin.py <plugin-slug> --skip-phase2 --skip-phase5
```

### Build Studio backend (local pipeline)

```bash
pip install -e packages/conxa-core
cd conxa-builder/python && pip install -r requirements.txt && python -m playwright install chromium
python backend.py   # stdio JSON-RPC backend (normally spawned by Electron)
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

Copy `.env.example` → `.env`. All backend settings use the `SKILL_` env prefix (see `packages/conxa-core/conxa_core/config.py`). LLM provider keys feed the multi-provider router — see `conxa-cloud/backend/ROUTER_SETUP.md` (Groq, Google AI Studio, and NVIDIA NIM are enabled by default).

## Architecture: The Big Picture

### Offline pipeline (record → compile → package)

```
(Runs locally in the Build Studio — conxa-builder/python/conxa_compile/)

Browser
  └─ conxa_compile/recorder/bridge.js      injected into every frame; captures
                                  click / type / select / hover / drag / etc.
  ↓
conxa_compile/recorder/session.py    Playwright binding sink; walks iframe parent
                                      chain, accumulates page-level offsets
  ↓ events.jsonl  +  screenshots
conxa_compile/pipeline/run.py        normalize / dedupe / enrich
  ↓
conxa_compile/compiler/build.py      compile_skill_package() — produces:
    • ElementFingerprint per step      (role / tag / text / aria / testid / anchors)
    • Assertion[] per step              (url_pattern, selector_present, …)
    • RecoveryBlock (anchors, fallback selectors)
    • SkillMeta.structural_fingerprint  (drift baseline)
  ↓ LLM calls route through conxa_core.llm.get_router() → metered cloud proxy
conxa_compile/plugin_builder.py      data-only plugin folder under
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

- Everything mounts under `/api/v1/*` (`conxa-cloud/backend/app/main.py`). The thin cloud serves the
  metered LLM proxy (`/llm/proxy/*`), auth, billing (`/subscriptions`, `/billing/*`), dashboard
  (`/dashboard`, `/plugins`), publish + installer hosting, runtime sync (`/skill-packs/*`), updates,
  and telemetry (`/runs`, `/tracking`). Recording, compiling, building, and execution are **not**
  served by the cloud — they run locally (Build Studio + runtime). `/healthz`, `/readyz` are unversioned.
- MCP tools exposed by `runtime/server.js`: `execute_plan` (sync or `async: true`), `get_execution_status`, `pause_execution`, `resume_execution`, `cancel_execution`, `list_skills`, `read_skill_files`, `install_plugin`, `search_registry`.
- Frontend reaches the backend via the Next.js `/api/v1/*` route handler; set `API_ORIGIN` in production.

## Where to Look First

| Concern                            | Code paths                                                                  |
| ---------------------------------- | --------------------------------------------------------------------------- |
| Recorder event types               | `conxa-builder/python/conxa_compile/recorder/bridge.js` → `conxa_compile/pipeline/` → `conxa_compile/compiler/build.py` → `runtime/run.js` |
| Selector compilation / scoring     | `conxa-builder/python/conxa_compile/compiler/llm_selector_generator_v2.py`, `selector_score.py`, `selector_filters.py` |
| Runtime element resolution         | `runtime/run.js` — `resolveElement`, `withLocator`, `rootCandidates`        |
| Assertions / outcome validation    | `conxa-builder/python/conxa_compile/compiler/validation_planner.py`; runtime `verifyAssertions()` |
| Plugin packaging                   | `conxa-builder/python/conxa_compile/plugin_builder.py` (data-only output, auth excluded) |
| LLM calls (compile side)           | task clients in `conxa_compile/llm/` → `conxa_core.llm.get_router()` (Studio installs the cloud proxy client) |
| LLM provider pool (cloud)          | `conxa-cloud/backend/app/llm/router.py` behind `POST /api/v1/llm/proxy/{text,vision}` |
| Frame / iframe handling            | `docs/architecture.md` § "Iframe Pipeline"; `bridge.js`, `session.py`, `build.py`, `run.js` |
| Shared data contracts              | `packages/conxa-core/conxa_core/models/` (SkillPackage, RecordedEvent, Plugin) |
| Frontend product shell             | `conxa-cloud/frontend/src/` (Dashboard, Plugins, Billing, Team, Settings)   |

## Deployment

- **Backend** on Render: root directory `conxa-cloud/backend`. `build.sh` installs the shared
  foundation (`pip install ../../packages/conxa-core`) then `requirements.txt`; `start.sh` runs
  `uvicorn app.main:app` (schema created by `init_db()`). A `Dockerfile` exists (build context = repo
  root). `GET /readyz` gates the deploy (DB ping), `GET /healthz` is liveness. With
  `SKILL_AUTH_REQUIRED=true` the app **refuses to start** unless `SKILL_DATABASE_URL`, Clerk
  issuer/JWKS, `CORS_ORIGINS`, Razorpay key/secret/webhook, and a provider key are set — no silent
  filesystem-DB fallback. The cloud no longer records/compiles, so no Playwright.
- **Frontend** on Vercel: set project root to `conxa-cloud/frontend`, build `npm run build`. The Next route handler `/api/v1/*` proxies to `API_ORIGIN`. Set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` for Clerk.
- System packages for Playwright/Chromium on the API host are listed in `conxa-cloud/backend/Aptfile`.

## Key Invariants

- Auth files (`auth/auth.json`, credentials) are **local runtime state**. They are never placed in build output and never committed.
- Tier 1/2 recovery costs zero LLM tokens. LLM only fires at Tier 3+. Don't introduce silent LLM fallbacks.
- Iframe chain is preserved verbatim from recording through compile and execution; bounding boxes are page-level (offsets accumulated up the chain).
- `frame_enter` / `frame_exit` actions get `no_recovery_block` — no retry on these markers.
- All API routes live under `/api/v1`; the frontend depends on this.
