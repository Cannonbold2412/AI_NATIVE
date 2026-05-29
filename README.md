# Conxa — AI-Native Automation Platform

Record real browser workflows once. Compile them into durable, self-healing skills. Replay them anywhere via Claude with zero maintenance.

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
app/                    FastAPI backend (Python 3.11+)
  api/                  HTTP routes, all mounted under /api/v1
  recorder/             Playwright session capture + bridge.js injection
  pipeline/             Event normalise / dedupe / enrich
  compiler/             Events → SkillPackage (selectors, assertions, recovery)
  execution/            Lifecycle state machine, checkpoint, drift, trace
  llm/                  Multi-provider LLM router (Groq, Google AI Studio, NVIDIA NIM)
  services/             Plugin builder, installer builder, LLM metering, publish
  storage/              JSON/SQLite stores, DOM snapshots, plugin/installer templates
  models/               Pydantic schemas: SkillPackage, RecordedEvent, Plugin
  auth/                 Playwright storageState manager
  editor/               Workflow editor service + DTOs

runtime/                Node.js MCP runtime (ships to ~/.conxa/runtime/)
  server.js             MCP stdio server — Claude integration point
  run.js                Step executor + 5-tier self-healing recovery cascade
  auth_manager.js       Token storage (keytar), session encryption, auth-failure recovery
  sync.js               Delta skill-pack sync with exponential backoff
  browser.js            Playwright browser/context lifecycle

frontend/               Next.js 16 App Router UI (cloud dashboard)
  src/                  Dashboard, Plugins, SkillPackBuilder, TestPlugin pages

conxa-builder/          Build Studio — Windows desktop app
  electron/             Electron shell (main.js, preload.js, renderer)
    renderer/src/       React 18 + TypeScript + Vite UI
      pages/            SetupWizard, PluginDetail, RecordingFeed,
                        CompileProgress, StepEditor
      components/       Sidebar, WorkflowViewer, StepEditorPanel,
                        ValidationReportPanel, SuggestionsPanel
  python/               Python backend (stdio JSON-RPC)
    backend.py          Command dispatcher (create_plugin, record, compile, build, publish)
    services/           LLM proxy client, auth service (Clerk PKCE), bootstrap,
                        installer builder, metadata reporter

scripts/
  test_plugin.py        End-to-end plugin validator (5 phases)
  recompile_session.py  Recompile a session and dump the selector report

tests/                  pytest suite — unit, integration, e2e
docs/architecture.md    Authoritative deep-dive: iframe pipeline, recovery cascade,
                        data contracts, observability

.github/workflows/
  build-runtime.yml     Builds runtime-win.exe + keytar.node → GitHub Release
  build-studio.yml      PyInstaller backend + electron-builder NSIS installer
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

```bash
cd conxa-builder/electron
npm install
npm run dev        # starts Vite renderer + Electron in parallel
npm run build      # PyInstaller backend + electron-builder NSIS installer
```

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

- **Backend + worker**: build with `./build.sh`, start with `./start.sh`. Required env vars: `SKILL_AUTH_REQUIRED=true`, Clerk issuer + JWKS, DB (`SKILL_DATABASE_URL`), Redis, Blob store, LLM provider keys, `CORS_ORIGINS`.
- **Frontend**: Vercel, project root `frontend`. Set `API_ORIGIN` to the backend URL, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`.

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
