# Conxa — AI-Native Automation Platform

Record real browser workflows once. Compile them into durable, self-healing skills. Let Claude execute them reliably — forever.

---

## What This Is

Conxa is infrastructure that makes any software platform operable by AI. Three systems, three owners:

```
Company (SaaS vendor)        Conxa Cloud              Customer (end user)
─────────────────────        ───────────              ──────────────────
Build Studio (Windows)  →    Render + Vercel      →   Runtime (Claude Desktop)
Record + compile locally     Proxy / host / bill      Execute locally via MCP
```

- **Build Studio** — Windows Electron + Python desktop app. Records browser workflows via Playwright, compiles them into structured skill packages with multi-signal element identity, self-healing recovery blocks, and outcome assertions. Everything happens locally; the cloud is never involved in recording or compilation.
- **Conxa Cloud** — Thin SaaS layer. Proxies LLM calls (metered), hosts published skill packages, handles billing (Razorpay), manages team auth (Clerk), and streams telemetry from the runtime.
- **Runtime** — Node.js MCP server that ships to the customer's machine as a bundled `.exe`. Syncs skill packages from the cloud, executes them step-by-step with a 5-tier self-healing recovery cascade, and surfaces them to Claude via MCP tools.

---

## Repository Layout

```
packages/conxa-core/        Shared Python foundation — pip package `conxa_core`
                            Installed by BOTH the cloud backend and the Build Studio

conxa-builder/              Build Studio — Windows desktop app
  electron/                 Electron shell (main.js, preload.js, React + Vite renderer)
  python/                   Python stdio backend (spawned by Electron over JSON-RPC)
    conxa_compile/          Full local pipeline: recorder → pipeline → compiler → editor

conxa-cloud/                Cloud SaaS — coordination only, no recording or execution
  backend/                  FastAPI (Render) — LLM proxy, auth, billing, skill hosting
  frontend/                 Next.js 16 dashboard (Vercel) — Dashboard, Plugins, Billing, Team

runtime/                    Node.js MCP server — ships to ~/.conxa/runtime/ on customer machine

docs/                       Authoritative documentation — read before changing anything
data/                       Runtime state: sessions, plugins, skills, cache, chromium
```

---

## Documentation

Read the relevant doc before making non-trivial changes — the code is downstream of these.

| Document | When to read it |
|---|---|
| [`docs/TRD.md`](docs/TRD.md) | Recorder, compiler, runtime, auth flows, API surface, recovery cascade. Full technical deep-dive with sequence diagrams. |
| [`docs/App-Flow.md`](docs/App-Flow.md) | End-to-end user flows — onboarding, record, compile, build, install, execute, update. |
| [`docs/Backend-Schema.md`](docs/Backend-Schema.md) | Data models, API contracts, ERD diagrams, KV namespace map. |
| [`docs/UI-UX-Brief.md`](docs/UI-UX-Brief.md) | Every screen in Build Studio and Cloud Dashboard. |
| [`docs/Implementation-Plan.md`](docs/Implementation-Plan.md) | Prioritised 4-phase engineering roadmap. Start here for new tasks. |
| [`docs/PRD.md`](docs/PRD.md) | Product vision, personas, positioning, long-term roadmap. |
| [`docs/cost_model.md`](docs/cost_model.md) | LLM unit economics — cost per compile, hosting cost, revenue model. |

New to the codebase? Start with `docs/TRD.md`.

---

## Getting Started

### Prerequisites

- Python 3.10+, pip
- Node.js 18+, npm
- Windows 10/11 x64 (Build Studio only; cloud backend and runtime run cross-platform)

### Cloud backend

```bash
# Install shared foundation first (editable for dev), then cloud deps
pip install -e packages/conxa-core
cd conxa-cloud/backend && pip install -r requirements.txt

# Run the API server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Tests — run from conxa-cloud/
cd .. && pytest -q tests
```

### Cloud frontend

```bash
cd conxa-cloud/frontend
npm install
npm run dev       # local dev server
npm run lint
npm run build     # production build (Vercel)
```

### Build Studio (Windows)

```bash
# 1. Install shared foundation and pipeline deps
pip install -e packages/conxa-core
cd conxa-builder/python && pip install -r requirements.txt && python -m playwright install chromium

# 2. Install Electron shell deps
cd ../electron && npm install

# 3. Run in development (starts Vite renderer + Electron; Electron spawns the Python backend)
npm run dev
```

### Runtime (MCP server)

```bash
cd runtime
npm install
npm start                  # MCP stdio mode — connect from Claude Desktop
npm run build:win          # → dist/runtime-win.exe
npm run build:mac          # → dist/runtime-mac
```

### Configuration

Copy `.env.example` → `.env`. All backend settings use the `SKILL_` prefix — see `packages/conxa-core/conxa_core/config.py`. LLM provider keys feed the multi-provider pool (Groq, Google AI Studio, NVIDIA NIM by default) — see `conxa-cloud/backend/ROUTER_SETUP.md`.

---

## Architecture

### Record → Compile → Package

```
bridge.js (injected into every frame)
  ↓
recorder/session.py          Playwright sink; accumulates iframe offsets
  ↓  events.jsonl + screenshots + DOM snapshots
pipeline/run.py              normalise / dedupe / enrich
  ↓
compiler/build.py            compile_skill_package():
    • ElementFingerprint     role / tag / text / aria / data-testid / anchors
    • Assertion[]            url_pattern, selector_present, text_match, …
    • RecoveryBlock          anchor signals + fallback selectors
    • structural_fingerprint drift baseline for version detection
  ↓
plugin_builder.py            data-only skill package (auth files never included)
```

### Runtime — 5-Tier Self-Healing Recovery

For every step, tiers run in order. LLM fires only at Tier 3+.

| Tier | Method | LLM cost |
|------|--------|----------|
| 1 | Compiled selectors (CSS, ARIA, text, XPath) | 0 |
| 2 | a11y tree — role + name lookup | 0 |
| 3 | Semantic recovery — Claude reads current DOM | yes |
| 4 | Vision recovery — Claude reads screenshot | yes |
| 5 | Escalation — human review queue | — |

### MCP Tools (exposed to Claude)

| Tool | Description |
|------|-------------|
| `execute_skill` | Execute a workflow skill. Returns result on success, or failure data for recovery. |
| `execute_sequence` | Execute an ordered list of skills in one shared browser session. |
| `list_skills` | List all installed company workflow skills. Call once before planning. |
| `get_skill_inputs` | Return the input schema for a skill. Call before `execute_skill`. |
| `get_execution_status` | Return the status of any currently running execution. |
| `cancel_execution` | Cancel the currently running execution. Safe to call at any time. |
| `refresh_skills` | Force an immediate skill pack sync from Conxa servers. |
| `get_runtime_status` | Return runtime diagnostics: loaded packs, sync URLs, log paths. |
| `read_skill_files` | Debug — inspect raw execution.json and recovery.json for a skill. |

---

## Deployment

### Cloud backend (Render)

Root directory: `conxa-cloud/backend`. `build.sh` installs `packages/conxa-core` then `requirements.txt`; `start.sh` runs `uvicorn app.main:app`. `GET /readyz` gates deploys (DB ping); `GET /healthz` is liveness.

With `SKILL_AUTH_REQUIRED=true` the backend **refuses to start** unless `SKILL_DATABASE_URL`, Clerk issuer/JWKS, `CORS_ORIGINS`, Razorpay credentials, and at least one LLM provider key are set. No silent fallback to filesystem DB in production.

### Cloud frontend (Vercel)

Project root: `conxa-cloud/frontend`. Requires `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `API_ORIGIN`, and `CONXA_API_PROXY_SECRET` (must match backend `SKILL_API_PROXY_SHARED_SECRET`).

### Build Studio (`.exe`)

Tagged `studio-v*` push triggers `build-studio.yml`: builds `conxa-core` as a wheel → PyInstaller bundles the Python backend → electron-builder wraps into NSIS installer → uploaded to GitHub Releases.

### Runtime (`.exe`)

Tagged `runtime-v*` push triggers `build-runtime.yml`: `@yao-pkg/pkg` bundles `runtime/` → `dist/runtime-win.exe` → GitHub Release. Installed to `%LOCALAPPDATA%\conxa\runtime\` on the customer's machine. Self-updates by polling `/api/v1/updates/runtime-manifest`.

---

## Key Invariants

These are non-negotiable.

- **Auth files never enter build output.** `auth/auth.json`, Playwright storageState, and credentials are local runtime state only. `plugin_builder.py` enforces this.
- **Tier 1/2 recovery costs zero LLM tokens.** LLM fires at Tier 3+ only. No silent LLM fallbacks in compiled-selector or a11y paths.
- **Iframe chain is preserved verbatim** from recording through compile through execution. Bounding boxes are page-level (offsets accumulated up the parent chain).
- **`frame_enter` / `frame_exit` steps get `no_recovery_block`.** Never retried.
- **All API routes live under `/api/v1`.** The frontend and runtime both depend on this prefix.
- **The cloud does not compile or execute.** Recording, compilation, and skill execution are local-only.
