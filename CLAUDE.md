# CLAUDE.md

This file is guidance for Claude Code when working in this repository.

---

## What This Is

Conxa is an AI-native automation platform. SaaS companies record browser workflows in the Build Studio (Electron + Python, Windows), compile them into structured skill packages with multi-signal element identity and self-healing recovery, publish them to the Conxa Cloud, and distribute them to end customers as `.exe` installers that run via Claude Desktop's MCP protocol. Execution is entirely local on the customer's machine — the cloud is coordination infrastructure, not an execution environment.

Three systems, three owners:

```
Company (SaaS vendor)        Conxa Cloud              Customer (end user)
─────────────────────        ───────────              ──────────────────
Build Studio (Windows)  →    Render + Vercel      →   Runtime (Claude Desktop)
Record + compile locally     Proxy / host / bill      Execute locally via MCP
```

---

## Documentation — Read First

The `docs/` folder is the authoritative source of truth for this codebase. Before making non-trivial changes, read the relevant doc rather than inferring from code alone.

| Doc | Read it when… |
|---|---|
| [`docs/TRD.md`](docs/TRD.md) | Touching the recorder, compiler, runtime, auth flows, API surface, or recovery cascade. This is the authoritative technical deep-dive: architecture, all auth flows with sequence diagrams, pipeline stages, data contracts, security model, known gaps. |
| [`docs/App-Flow.md`](docs/App-Flow.md) | Changing how a user flow works end-to-end — onboarding, record, compile, build, install, execute, update. |
| [`docs/Backend-Schema.md`](docs/Backend-Schema.md) | Changing data models, adding API endpoints, modifying KV namespaces, or changing telemetry event schemas. Contains ERD diagrams and full API contracts with request/response examples. |
| [`docs/UI-UX-Brief.md`](docs/UI-UX-Brief.md) | Changing any screen in the Build Studio or Cloud Dashboard. Documents every screen's purpose, inputs, outputs, and known UX issues. |
| [`docs/Implementation-Plan.md`](docs/Implementation-Plan.md) | Starting on a new engineering task. Contains the prioritised 4-phase roadmap with specific files to change and risk assessments per item. |
| [`docs/PRD.md`](docs/PRD.md) | Understanding product goals, personas, positioning, or long-term strategy. **Do not edit for individual features** — see doc maintenance rules below. |
| [`docs/cost_model.md`](docs/cost_model.md) | Making decisions that affect LLM usage at compile or execution time. |

---

## Working Principles

1. **Think before coding.** State assumptions. If multiple interpretations exist, surface them — don't silently pick one. If a simpler approach exists, call it out. If something is unclear, stop and ask.
2. **Simplicity first.** Write the minimum code needed. No speculative abstractions, no configurability for single-use code, no handling for impossible scenarios. If 200 lines could be 50, rewrite it.
3. **Surgical changes.** Touch only what the task requires. Don't refactor unrelated code; mention issues rather than fixing them. Match existing style. Every changed line must trace to the task. If your changes leave unused code, remove only what *you* introduced.
4. **Goal-driven.** Define success → implement → verify. Bug → reproduce → fix → verify. Refactor → ensure no behavior change.

### Token and file constraints

- Don't read files larger than ~25 KB completely. Use `offset`/`limit`, or `grep`/`tail` to find the relevant chunk first.
- Session artifacts (`data/sessions/<id>/events.jsonl`, screenshots, compile reports) can be very large — always scope reads.

---

## Repository Layout

```
packages/conxa-core/        Shared Python foundation — pip package `conxa_core`
  conxa_core/               Installed by BOTH cloud backend and Build Studio
    config.py               Pydantic settings (env_prefix=SKILL_)
    db.py                   Dual store: Postgres (cloud) / filesystem (Studio) + healthcheck()
    models/                 Pydantic schemas: SkillPackage, RecordedEvent, Plugin
    storage/                JSON/SQLite stores, snapshots, plugin/installer templates
    llm/                    Router protocol + get/set_router singleton + HTTP client (call_llm)
    metrics/, progress.py, workspace.py, skill_pack_build_log.py
  pyproject.toml            Package-data: templates/bridge.js ships with pip install

conxa-builder/              Electron desktop studio — records + compiles + builds LOCALLY (Windows)
  electron/                 Electron main + React renderer (Vite + TypeScript)
  python/                   Python stdio backend (spawned by Electron; depends on conxa-core)
    backend.py              JSON-RPC dispatcher; wires cloud proxy via conxa_core.llm.set_router
    requirements.txt        playwright, Pillow, bs4, lxml  (conxa-core installed separately)
    services/               auth_service, bootstrap, llm_proxy_client, metadata_reporter
    conxa_compile/          Full local pipeline (no cloud involvement):
      recorder/             Playwright capture + injected bridge.js
      pipeline/             Normalize / dedupe / enrich recorded events
      compiler/             Events → SkillPackage (selectors, assertions, recovery, fingerprint)
      editor/               Workflow editor service + DTOs + patch gate
      llm/                  Task clients (intent, semantic, recovery, vision, anchor) + openapi_client
      anchors/, confidence/, policy/
      plugin_builder.py, installer_builder.py, conxa_runtime.py
  pyinstaller.spec          Bundles conxa_core + conxa_compile into dist/backend/

conxa-cloud/                Thin cloud SaaS — proxy / auth / billing / dashboard / hosting
  backend/                  FastAPI (depends on conxa-core; NO recorder/compiler/Playwright)
    app/
      main.py               Routers + fail-fast prod config validation + /healthz, /readyz
      worker.py             Render worker entrypoint (queue scaffold)
      api/                  llm_proxy, razorpay, product, publish, skillpack_update,
                            updates, tracking, run, job, plugins, security
      llm/router.py         Multi-provider pool: Groq, Google AI Studio, NVIDIA NIM
      services/             saas, rbac, llm_metering, jobs
    requirements.txt, build.sh, start.sh, Dockerfile, Aptfile, ROUTER_SETUP.md
  frontend/                 Next.js 16 dashboard (Dashboard, Plugins, Billing, Team, Settings)
    package.json            Clerk, TanStack Query, Tailwind 4, shadcn/ui, Framer Motion
  scripts/                  recompile_session.py, test_plugin.py
  tests/                    pytest suite (core + compile + cloud)
  pytest.ini                pythonpath = backend ../conxa-builder/python ../packages/conxa-core

runtime/                    Node.js MCP server — ships to ~/.conxa/runtime/ on customer machine
  server.js                 MCP stdio server (@modelcontextprotocol/sdk)
  run.js                    Step executor + fingerprint-scored 5-tier recovery
  skill_loader.js           Skill pack loading + input validation
  browser.js                Playwright browser lifecycle
  auth_manager.js           Per-company token via keytar; AES-256-GCM session encryption
  sync.js                   Skill pack delta sync with SHA-256 atomic writes
  tracker.js                Telemetry batching → POST /tracking/{co}/events
  package.json              @yao-pkg/pkg bundles for win/mac

data/                       Runtime state: sessions/, plugins/, skills/, saas/, cache/, chromium/

docs/
  TRD.md                    Authoritative technical deep-dive
  PRD.md                    Product strategy — vision, personas, positioning, roadmap
  App-Flow.md               End-to-end user flows with Mermaid diagrams
  Backend-Schema.md         Data models, API contracts, ERD diagrams, KV namespace map
  UI-UX-Brief.md            Every screen in Build Studio and Cloud Dashboard; UX issues
  Implementation-Plan.md    Prioritised engineering roadmap across 4 phases
  cost_model.md             Unit economics — LLM cost per compile, hosting, revenue model
```

---

## Common Commands

### Cloud backend

```bash
# Install shared foundation first (editable for dev), then cloud deps
pip install -e packages/conxa-core
cd conxa-cloud/backend && pip install -r requirements.txt   # or ./build.sh (used by Render)

# Run the API server (no Playwright — cloud does not record or compile)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# start.sh runs the same without --reload, binding to $PORT

# Tests — run from conxa-cloud/
# pytest.ini puts backend, conxa-builder/python, and packages/conxa-core on the path
cd .. && pytest -q tests

# Compile tools require conxa_compile on PYTHONPATH
PYTHONPATH=../conxa-builder/python python scripts/recompile_session.py <session_id>
PYTHONPATH=../conxa-builder/python python scripts/test_plugin.py <plugin-slug> --skip-phase2 --skip-phase5
```

### Build Studio backend (local pipeline)

```bash
pip install -e packages/conxa-core
cd conxa-builder/python && pip install -r requirements.txt && python -m playwright install chromium
python backend.py   # stdio JSON-RPC backend — normally spawned by Electron, not run directly
```

### Cloud frontend

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
npm start                     # node server.js — MCP stdio mode
npm run build:win             # @yao-pkg/pkg → dist/runtime-win.exe
npm run build:mac             # @yao-pkg/pkg → dist/runtime-mac
```

### Configuration

Copy `.env.example` → `.env`. All backend settings use the `SKILL_` env prefix — see `packages/conxa-core/conxa_core/config.py`. LLM provider keys feed the multi-provider router — see `conxa-cloud/backend/ROUTER_SETUP.md`. Groq, Google AI Studio, and NVIDIA NIM are enabled by default.

---

## Architecture

The full technical reference — pipeline stages, runtime filesystem layout, all auth flows, recovery cascade tiers, API surface, and known gaps — is in **[`docs/TRD.md`](docs/TRD.md)**. Read it before touching the recorder, compiler, or runtime.

Quick orientation:

- **Build Studio** (`conxa-builder/python/conxa_compile/`): `bridge.js` → `session.py` → `pipeline/run.py` → `compiler/build.py` → `plugin_builder.py`. All local. Cloud is not involved.
- **Cloud** (`conxa-cloud/`): coordination only — LLM proxy, skill pack hosting, telemetry ingest, billing. Does not record, compile, or execute.
- **Runtime** (`runtime/`): Node MCP server on the customer's machine. Syncs packs from Cloud, executes skills step-by-step with 5-tier self-healing recovery, streams telemetry back.

MCP tools exposed by `runtime/server.js`: `execute_skill`, `execute_sequence`, `list_skills`, `get_skill_inputs`, `get_execution_status`, `cancel_execution`, `refresh_skills`, `get_runtime_status`, `read_skill_files`.

---

## Where to Look First

| Concern | Code path |
|---|---|
| Recorder event types | `conxa_compile/recorder/bridge.js` → `pipeline/` → `compiler/build.py` → `runtime/run.js` |
| Selector compilation / scoring | `conxa_compile/compiler/llm_selector_generator_v2.py`, `selector_score.py`, `selector_filters.py` |
| Runtime element resolution | `runtime/run.js` — `resolveElement`, `withLocator`, `rootCandidates` |
| Assertions / outcome validation | `conxa_compile/compiler/validation_planner.py`; runtime `verifyAssertions()` |
| Plugin packaging | `conxa_compile/plugin_builder.py` (data-only output, auth excluded) |
| LLM calls (compile side) | task clients in `conxa_compile/llm/` → `conxa_core.llm.get_router()` → cloud proxy |
| LLM provider pool (cloud) | `conxa-cloud/backend/app/llm/router.py` behind `POST /api/v1/llm/proxy/{text,vision}` |
| Frame / iframe handling | `docs/TRD.md` § "Iframe Pipeline"; `bridge.js`, `session.py`, `build.py`, `run.js` |
| Shared data models | `packages/conxa-core/conxa_core/models/` — SkillPackage, RecordedEvent, Plugin |
| Auth (Build Studio) | `conxa-builder/python/services/auth_service.py` — Clerk PKCE → OS keyring |
| Auth (Runtime) | `runtime/auth_manager.js` — per-company token in keytar; AES-256-GCM session |
| Auth (Cloud API) | `conxa-cloud/backend/app/api/security.py` — Clerk JWT via PyJWT + JWKS |
| Telemetry | `runtime/tracker.js` → `conxa-cloud/backend/app/api/tracking_routes.py` |
| Skill pack sync | `runtime/sync.js` ↔ `app/api/skillpack_update_routes.py` |
| Frontend screens | `conxa-cloud/frontend/src/` — Dashboard, Plugins, Billing, Team, Settings |

---

## Deployment

**Cloud backend** runs on Render. Root directory: `conxa-cloud/backend`. `build.sh` installs `packages/conxa-core` then `requirements.txt`. `start.sh` runs `uvicorn app.main:app` (`init_db()` creates schema on startup). A `Dockerfile` exists (build context = repo root). `GET /readyz` gates deploys (DB ping); `GET /healthz` is liveness. With `SKILL_AUTH_REQUIRED=true` the app **refuses to start** unless `SKILL_DATABASE_URL`, Clerk issuer/JWKS, `CORS_ORIGINS`, Razorpay credentials, and at least one LLM provider key are set. No silent fallback to filesystem DB in production.

**Cloud frontend** runs on Vercel. Project root: `conxa-cloud/frontend`. Build: `npm run build`. The Next.js route handler `/api/v1/*` proxies to `API_ORIGIN`. Requires `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY`.

**Runtime** ships as a bundled `.exe` embedded in the NSIS installer. `@yao-pkg/pkg` bundles `runtime/` into `dist/runtime-win.exe`. Installed to `%LOCALAPPDATA%\conxa\runtime\` on Windows. Self-updates by polling `/api/v1/updates/runtime-manifest`.

---

## Key Invariants

These are non-negotiable. Do not work around them.

- **Auth files never enter build output.** `auth/auth.json`, Playwright storageState, and credentials are local runtime state only. `plugin_builder.py` enforces this — the check must remain.
- **Tier 1/2 recovery costs zero LLM tokens.** LLM fires at Tier 3+ only. Do not introduce silent LLM fallbacks into compiled-selector or a11y resolution paths.
- **Iframe chain is preserved verbatim** from recording through compile and execution. Bounding boxes are page-level (offsets accumulated up the parent chain in `session.py`).
- **`frame_enter` / `frame_exit` steps get `no_recovery_block`.** These are navigation markers, not interactable elements. They are never retried.
- **All API routes live under `/api/v1`.** The frontend and runtime both depend on this prefix. Do not route anything else there.
- **The cloud does not compile or execute.** Recording, compilation, plugin building, and skill execution are local-only. Keep them that way.

---

## Maintaining the Docs

The `docs/` files are living documentation. After making significant changes to the codebase, update the relevant doc so it stays accurate. A doc that drifts from the code is worse than no doc.

### Which doc to update after which changes

| Change type | Update |
|---|---|
| Architecture change — new system, new component, new communication path | `docs/TRD.md` |
| Auth flow change — new token type, new validation step, new storage | `docs/TRD.md` |
| New or changed API endpoint | `docs/TRD.md`, `docs/Backend-Schema.md` |
| Data model change — new field, new model, new KV namespace | `docs/Backend-Schema.md` |
| New telemetry event code | `docs/Backend-Schema.md` |
| Recovery cascade change — new tier, changed tier order or cost | `docs/TRD.md`, `docs/App-Flow.md` |
| User flow change — new screen, new step in an existing flow | `docs/App-Flow.md` |
| New screen or significant screen redesign | `docs/UI-UX-Brief.md` |
| Engineering task completed from the roadmap | `docs/Implementation-Plan.md` (mark done or update status) |
| New gap or tech debt identified | `docs/Implementation-Plan.md` |

### What does NOT require a doc update

- Bug fixes that do not change observable behavior or data contracts.
- Internal refactors that keep the same API surface and data models.
- Configuration changes, dependency version bumps.
- Test additions.

When in doubt, update the doc. A stale sentence in the TRD costs future engineers hours.

### PRD update policy

**Do not edit `docs/PRD.md` for individual features, bug fixes, or incremental improvements.**

`docs/PRD.md` is a strategic document. It reflects the company's vision, product positioning, competitive analysis, and multi-year roadmap. It should only change when something fundamentally shifts at the company level:

- A new target market or customer segment is adopted.
- The business model changes (e.g., from per-plugin to platform licensing).
- The distribution model changes significantly (e.g., moving beyond MCP).
- The core value proposition shifts (e.g., adding a cloud execution tier).
- A new phase is added to the roadmap after completing a major milestone.

For everything else — adding a feature, fixing a flow, shipping a phase — update the technical docs (`TRD.md`, `Backend-Schema.md`, `App-Flow.md`, `Implementation-Plan.md`) and leave the PRD alone.
