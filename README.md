# Conxa — AI-Native Automation Platform

Record real browser workflows once. Compile them into durable, self-healing skills. Replay them anywhere via Claude with zero maintenance.

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/TRD.md`](docs/TRD.md) | Full technical reference — system architecture, all auth flows (with sequence diagrams), pipelines, recovery cascade, API surface, database schema, security model, known gaps |
| [`docs/PRD.md`](docs/PRD.md) | Product — vision, personas, competitive positioning, value props, success metrics, roadmap |
| [`docs/App-Flow.md`](docs/App-Flow.md) | End-to-end user flows with Mermaid diagrams — onboarding, record, compile, build, install, execute, recover, update |
| [`docs/Backend-Schema.md`](docs/Backend-Schema.md) | Data models, API contracts, ERD diagrams, KV namespace map, multi-tenancy design |
| [`docs/UI-UX-Brief.md`](docs/UI-UX-Brief.md) | Every screen in Build Studio and Cloud Dashboard — purpose, UX issues, bottlenecks, missing experiences |
| [`docs/Implementation-Plan.md`](docs/Implementation-Plan.md) | Prioritised engineering roadmap across 4 phases — what's broken, what to fix, which files, dependencies, risks |
| [`docs/cost_model.md`](docs/cost_model.md) | Unit economics — LLM cost per compile, hosting cost, revenue model |

> **Start with `docs/TRD.md`** for a new engineer onboarding. Start with `docs/PRD.md` for product/business context.

---

## What This Is

Conxa is a full-stack platform for building and running AI-native automation plugins:

- **Record** — a Playwright-powered browser captures every user action (click, type, navigate, select) along with full DOM snapshots, a11y trees, and screenshots.
- **Compile** — raw events are normalised, deduplicated, and passed through an LLM-assisted compiler that produces structured skills: element fingerprints, CSS/ARIA/XPath selectors, outcome assertions, and recovery blocks.
- **Replay** — a Node.js MCP runtime executes skills step-by-step with a 5-tier self-healing recovery cascade. Claude invokes skills via MCP tools (`execute_plan`, `list_skills`, etc.).
- **Build Studio** — a Windows Electron desktop app (in progress) that records locally against the employee's real authenticated browser, compiles via a metered cloud LLM proxy, and packages distributable `.exe` installers for end users.

---

## Repository Layout

```
packages/conxa-core/      Shared Python foundation (pip package `conxa_core`)
  conxa_core/
    config.py             Pydantic settings (env_prefix=SKILL_)
    db.py                 Dual store: Postgres (cloud) / filesystem fallback (Studio)
    models/               Pydantic schemas: SkillPackage, RecordedEvent, Plugin
    storage/              JSON/SQLite stores, DOM snapshots, plugin/installer templates
    llm/                  Router protocol + get/set_router singleton + HTTP client (call_llm)
    metrics/, progress.py, workspace.py, skill_pack_build_log.py   shared primitives
  Installed by BOTH the cloud backend and the Build Studio — one source of truth.

conxa-builder/            Build Studio — Windows desktop app (records + compiles LOCALLY)
  electron/               Electron shell (main.js, preload.js, React+Vite renderer)
  python/                 Python stdio backend (spawned by Electron)
    backend.py            JSON-RPC dispatcher (create_plugin, record, compile, build, publish)
    requirements.txt      playwright, Pillow, bs4, lxml (+ conxa-core, installed separately)
    services/             LLM proxy client, auth (Clerk PKCE), bootstrap, metadata reporter
    conxa_compile/        The local pipeline (moved out of the cloud):
      recorder/           Playwright capture + injected bridge.js
      pipeline/           Event normalise / dedupe / enrich
      compiler/           Events → SkillPackage (selectors, assertions, recovery)
      editor/             Workflow editor service + DTOs + patch gate
      llm/                Task clients (intent, semantic, recovery, vision, anchor) + openapi_client
      anchors/, confidence/, policy/   supporting modules
      plugin_builder.py, installer_builder.py, conxa_runtime.py
  pyinstaller.spec        Collects conxa_core + conxa_compile into dist/backend/

conxa-cloud/              Thin cloud SaaS (Render + Vercel) — proxy/auth/billing/dashboard/hosting
  backend/                FastAPI backend (depends on conxa-core; NO recorder/compiler)
    app/
      main.py             Entrypoint; routers + fail-fast config validation + /healthz, /readyz
      api/                llm_proxy, razorpay, product, publish (+ installer hosting),
                          skillpack_update (runtime sync), updates, tracking, run, job, plugins
      llm/router.py       Multi-provider pool (Groq, Google AI Studio, NVIDIA NIM) behind the proxy
      services/           saas (billing/workspace), rbac, llm_metering, jobs (status)
      worker.py           Render worker entrypoint
    requirements.txt, build.sh, start.sh, Dockerfile, Aptfile
  frontend/               Next.js 16 dashboard (Dashboard, Plugins, Billing, Team, Settings)
  scripts/                recompile_session.py, test_plugin.py (compile tools; need conxa-builder/python on PYTHONPATH)
  tests/                  pytest suite (core + compile + cloud; see pytest.ini pythonpath)

runtime/                  Node.js MCP runtime (standalone; ships to ~/.conxa/runtime/)
  server.js               MCP stdio server — Claude integration point
  run.js                  Step executor + 5-tier self-healing recovery cascade
  auth_manager.js         Token storage (keytar), session encryption, auth-failure recovery
  sync.js                 Delta skill-pack sync (atomic write + sha256 verify)
  browser.js              Playwright browser/context lifecycle

docs/architecture.md      Authoritative deep-dive: iframe pipeline, recovery cascade, data contracts

.github/workflows/
  build-runtime.yml       Builds runtime-win.exe + keytar.node → GitHub Release
  build-studio.yml        Installs conxa-core wheel → PyInstaller → electron-builder NSIS installer
```

### How the three units relate

```
conxa-core ──pip install──▶ Build Studio (records + compiles + builds LOCALLY)
           ──pip install──▶ Cloud backend (LLM proxy, auth, billing, dashboard, hosting)
Build Studio ──/llm/proxy, auth, publish upload──▶ Cloud
Runtime (Node) ──skill-pack sync, telemetry, updates, auth──▶ Cloud
```


---

## Architecture

### Record → Compile → Package (offline pipeline)

```
Browser
  └─ recorder/bridge.js          injected into every frame; captures events
  ↓
recorder/session.py              Playwright sink; accumulates iframe offsets
  ↓  events.jsonl + screenshots + DOM snapshots
pipeline/run.py                  normalise / dedupe / enrich
  ↓
compiler/build.py                compile_skill_package():
    • ElementFingerprint          role / tag / text / aria / data-testid / anchors
    • Assertion[]                 url_pattern, selector_present, text_match, …
    • RecoveryBlock               anchor signals + fallback selectors
    • structural_fingerprint      drift baseline for version detection
  ↓
services/plugin_builder.py       data-only plugin folder
                                  (auth files never in build output)
```

### Runtime — 5-tier self-healing recovery cascade

For every step, tiers run in order. LLM fires only at Tier 3+.

| Tier | Method | LLM tokens |
|------|--------|-----------|
| 1 | Compiled selectors (CSS, ARIA, text, XPath) | 0 |
| 2 | a11y tree — role + name lookup | 0 |
| 3 | LLM semantic recovery — Claude reads current DOM | yes |
| 4 | Vision recovery — Claude reads screenshot | yes |
| 5 | Escalation — human review queue | — |

### Build Studio (Electron + PyInstaller, Windows)

```
main.js
  ├─ spawns backend.exe (PyInstaller bundle of python/backend.py + app/)
  ├─ stdio JSON-RPC bridge (python:cmd IPC → renderer)
  └─ electron-updater (4h poll, stable/beta channels)

Renderer (React 18 + Vite + HashRouter)
  SetupWizard → PluginDetail → RecordingFeed → CompileProgress → StepEditor

backend.py commands
  create_plugin, start_recording, stop_recording, compile,
  build_plugin, build_installer, publish, list_workflows, patch_step, …
```

---

## Getting Started

### Backend (Python)

```bash
# Install dependencies + Playwright Chromium
pip install -r requirements.txt
python -m playwright install chromium

# Start the API (development)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Run tests
pytest -q tests

# Recompile a recorded session and inspect the selector report
python scripts/recompile_session.py <session_id>
```

Copy `.env.example` → `.env`. All settings use the `SKILL_` prefix. At minimum, set one LLM provider — see `ROUTER_SETUP.md`.

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
npm run build      # production build for Vercel
```

Set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` for auth.

### Runtime (MCP server)

```bash
cd runtime
npm install
npm start          # MCP stdio server — connect from Claude Code
npm run build:win  # → dist/runtime-win.exe
npm run build:mac  # → dist/runtime-mac
```

### Build Studio (Electron, Windows only)

The Build Studio has two parts that must both be set up: a **Python backend** (the record/compile pipeline, spawned by Electron over stdio) and an **Electron shell** (Vite renderer + main process).

#### Prerequisites

- Windows 10/11 x64
- Python 3.10+ and pip
- Node.js 18+ and npm
- PyInstaller (`pip install pyinstaller`) — only needed for production builds

#### 1 — Python backend setup

Run these once from the **repo root**:

```bash
# Install the shared foundation in editable mode (brings pydantic, SQLAlchemy, etc.)
pip install -e packages/conxa-core

# Install the local pipeline dependencies (Playwright, Pillow, bs4, lxml, ffmpeg)
pip install -r conxa-builder/python/requirements.txt

# Download Chromium for recording
python -m playwright install chromium
```

#### 2 — Electron shell setup

```bash
cd conxa-builder/electron
npm install
```

#### 3 — Run in development

```bash
# From conxa-builder/electron — starts Vite renderer on :5174 and Electron in parallel
npm run dev
```

Electron spawns `conxa-builder/python/backend.py` automatically over stdio JSON-RPC.
Set any required env vars before running (see Configuration below).

#### 4 — Configuration

Create a `.env` file in `conxa-builder/python/` (all vars use the `SKILL_` prefix):

```env
# LLM proxy — required for compile to work; points to the cloud backend
SKILL_LLM_PROXY_URL=https://your-cloud-backend/api/v1/llm/proxy

# Clerk OAuth — required for sign-in
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_...

# Optional: override local data directory (defaults to ~/.conxa/data)
SKILL_DATA_DIR=C:\Users\you\.conxa\data
```

See `packages/conxa-core/conxa_core/config.py` for the full list. LLM provider setup: `conxa-cloud/backend/ROUTER_SETUP.md`.

#### 5 — Build a production installer

The production build runs in two stages — PyInstaller bundles the Python backend first, then `electron-builder` wraps everything into an NSIS `.exe`.

**Stage 1 — bundle the Python backend:**

```bash
# From the repo root (pyinstaller.spec lives in conxa-builder/)
pip install pyinstaller
pip install -e packages/conxa-core   # must be a real install so data files materialise

cd conxa-builder
pyinstaller pyinstaller.spec
# → dist/backend/   (--onedir bundle; backend.exe + all deps)
```

**Stage 2 — build the Electron NSIS installer:**

```bash
cd conxa-builder/electron
npm run build
# Runs: vite build (renderer → renderer/dist/) then electron-builder
# → dist/studio/Conxa-Build-Studio-Setup.exe
```

`electron-builder` picks up `conxa-builder/dist/backend/` as an `extraResource`, so the PyInstaller bundle must exist before this step.

#### CI build (GitHub Actions)

The `build-studio.yml` workflow automates the full pipeline on a `studio-v*` tag push:
builds `conxa-core` as a wheel → installs deps → PyInstaller → electron-builder → uploads `Conxa-Build-Studio-Setup.exe` to GitHub Releases.

---

## Cloud API Endpoints

All routes mount under `/api/v1`.

| Route | Description |
|-------|-------------|
| `POST /llm/proxy/text` | Metered LLM text proxy (requires `X-Conxa-Client: build-studio`) |
| `POST /llm/proxy/vision` | Metered LLM vision proxy |
| `GET /llm/proxy/usage` | Monthly token usage for the authenticated org |
| `POST /plugins/publish` | Publish a skill package to the registry |
| `POST /plugins/{slug}/installer/upload` | Upload a compiled `.exe` installer |
| `GET /installers/{slug}` | Public installer download (no auth — end users) |
| `GET /updates/deps-manifest` | NSIS + runtime download URLs for Build Studio bootstrap |
| `GET /updates/runtime-manifest` | Runtime self-update manifest (cached 24h by runtime) |
| `GET /executions` | List active/recent executions |
| `POST /executions/{id}/{pause,resume,cancel}` | Control a running execution |

---

## MCP Tools (Claude integration)

The runtime exposes these tools to Claude via stdio MCP:

| Tool | Description |
|------|-------------|
| `execute_plan` | Run a named skill with inputs (sync or async) |
| `get_execution_status` | Poll an async execution |
| `pause_execution` / `resume_execution` / `cancel_execution` | Lifecycle control |
| `list_skills` | List available skills from installed plugins |
| `read_skill_files` | Read skill metadata (steps, assertions, recovery) |
| `install_plugin` | Install a plugin from the Conxa registry |
| `search_registry` | Search the skill registry |

---

## Deployment

### Cloud (Render + Vercel)

- **Backend**: root directory `conxa-cloud/backend`. `build.sh` installs the shared
  foundation (`pip install ../../packages/conxa-core`) then `requirements.txt`; `start.sh`
  runs `uvicorn app.main:app`. A `Dockerfile` is provided (build context = repo root:
  `docker build -f conxa-cloud/backend/Dockerfile .`). The schema is created by `init_db()`
  on startup; `GET /readyz` gates the deploy (checks the DB), `GET /healthz` is liveness.
  Required env: `SKILL_AUTH_REQUIRED=true`, Clerk issuer/JWKS/audience, `SKILL_DATABASE_URL`,
  `SKILL_API_PROXY_SHARED_SECRET`, `CORS_ORIGINS`, Razorpay key/secret/webhook secret, LLM provider keys. **With
  `SKILL_AUTH_REQUIRED=true` the backend refuses to start if any of these are unset** (no
  silent filesystem-DB fallback). The cloud no longer records or compiles — no Playwright.
- **Frontend**: Vercel, project root `conxa-cloud/frontend`. Set `API_ORIGIN`,
  `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, and server-only
  `CONXA_API_PROXY_SECRET`. The proxy secret must match backend
  `SKILL_API_PROXY_SHARED_SECRET` so dashboard/plugin API calls use the active
  Clerk organization workspace instead of falling back to a personal workspace.

### Build Studio (`.exe`)

CI (`build-studio.yml`) builds `conxa-core` as a wheel and installs it **non-editable**
(so package data — `bridge.js`, templates, policy JSON — materializes), installs
`conxa-builder/python/requirements.txt`, runs PyInstaller (`pyinstaller.spec` collects
`conxa_core` + `conxa_compile`), then electron-builder wraps `dist/backend/` into the NSIS
installer.

### CI — GitHub Actions

| Workflow | Trigger | Output |
|----------|---------|--------|
| `build-runtime.yml` | `runtime-v*` tag | `runtime-win.exe` + `keytar.node` → GitHub Release |
| `build-studio.yml` | `studio-v*` tag | `Conxa-Build-Studio-Setup.exe` → GitHub Release |

### LLM providers

Conxa uses a multi-provider pool. Configure in `.env` — see `ROUTER_SETUP.md`. Groq, Google AI Studio, and NVIDIA NIM are enabled by default. For tests without real keys: `SKILL_ALLOW_NO_PROVIDERS=1`.

---

## Key Invariants

- Auth files (`auth/auth.json`, storageState) are **local runtime state**. They are never placed in build output, never committed, and never included in published installers.
- Tier 1/2 recovery costs **zero LLM tokens**. LLM fires only at Tier 3+. No silent fallbacks.
- Iframe chain is preserved verbatim from recording through compile through execution. Bounding boxes are always page-level (offsets accumulated up the chain).
- All API routes live under `/api/v1`. The frontend and runtime depend on this prefix.
- `SKILL_DATA_DIR` controls the data root; `db.py` activates its filesystem fallback automatically when `SKILL_DATABASE_URL` is unset (used by Build Studio).

---

## Branch: `feat/local-first-migration`

This branch contains the full Conxa Local-First migration — 6 phases completed:

| Phase | What shipped |
|-------|-------------|
| 0 | Selector quality fix: full-page DOM + a11y fed to v2 scorer; eliminates bare-tag selectors |
| 1 | Cloud refactor: metered LLM proxy, plugin publish/installer hosting, public deps manifests |
| 2 | Build Studio Python backend: stdio JSON-RPC, all commands, IPC path-traversal validation |
| 3 | Electron shell: Bridge class, main.js process lifecycle, preload context isolation, Clerk OAuth |
| 4 | Build Studio UI: all pages (SetupWizard → PluginDetail → RecordingFeed → CompileProgress → StepEditor) |
| 4.5 | Cloud manifest endpoints for bootstrap + runtime self-updater |
| 5 | Runtime session recovery: auth-failure detection, headed re-login, headless surface-to-Claude |
| 6 | CI workflows, PyInstaller spec, electron-builder NSIS config, runtime self-update via `update.bat` |
