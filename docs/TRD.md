# Technical Reference Document (TRD)

**Status:** Current as of 2026-06-01  
**Scope:** Conxa platform — Build Studio, Conxa Cloud, Runtime

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Conxa Build Studio](#2-conxa-build-studio)
3. [Conxa Cloud](#3-conxa-cloud)
4. [Conxa Runtime (MCP)](#4-conxa-runtime-mcp)
5. [Authentication & Platform Communication](#5-authentication--platform-communication)
6. [Recording Pipeline](#6-recording-pipeline)
7. [Compilation Pipeline](#7-compilation-pipeline)
8. [Skill Packaging Pipeline](#8-skill-packaging-pipeline)
9. [Execution Pipeline](#9-execution-pipeline)
10. [Recovery Architecture](#10-recovery-architecture)
11. [Skill Sync & Update Architecture](#11-skill-sync--update-architecture)
12. [Telemetry Architecture](#12-telemetry-architecture)
13. [LLM Router Architecture](#13-llm-router-architecture)
14. [Database & Storage Architecture](#14-database--storage-architecture)
15. [Security Model](#15-security-model)
16. [Deployment Architecture](#16-deployment-architecture)
17. [Known Gaps & Tech Debt](#17-known-gaps--tech-debt)

---

## 1. System Overview

Conxa is a three-tier platform:

```
┌─────────────────────────────────────────────────┐
│         Conxa Build Studio (Windows)            │
│  Electron app + Python stdio backend            │
│  All recording, compilation, packaging          │
│  happens 100% locally — nothing runs on cloud  │
└───────────────────┬─────────────────────────────┘
                    │ HTTPS / Bearer JWT
                    │ (LLM proxy, publish, auth)
┌───────────────────▼─────────────────────────────┐
│           Conxa Cloud                           │
│  FastAPI (Render) + Next.js (Vercel)            │
│  LLM metering proxy, skill pack hosting,        │
│  telemetry ingestion, billing, dashboard        │
└───────────────────┬─────────────────────────────┘
                    │ HTTPS at startup + async
                    │ (skill sync, telemetry out)
┌───────────────────▼─────────────────────────────┐
│           Conxa Runtime                         │
│  Node.js MCP server on end-user machine         │
│  Executes skills via Playwright                 │
│  Exposed to Claude Desktop as MCP tools         │
└─────────────────────────────────────────────────┘
```

**Key principle:** Execution is entirely on the end-user's machine. Conxa is
not in the execution hot path. The cloud is a coordination + telemetry layer.

---

## 2. Conxa Build Studio

### 2.1 Process Architecture

```
┌──────────────────────────────────────────────┐
│  Electron Main Process (electron/main.js)    │
│  • Window lifecycle                          │
│  • IPC bridge (electron/preload.js)          │
│  • Spawns Python backend as child process    │
│  • Deep-link auth callback handler           │
└────────────────┬─────────────────────────────┘
                 │ IPC (contextBridge)
┌────────────────▼─────────────────────────────┐
│  React Renderer (Vite + TypeScript)          │
│  electron/renderer/src/                      │
│  Pages: Dashboard, Plugins, Record,          │
│  HumanEdit, Compile, Build, Settings         │
│  State: Zustand (editorStore.ts)             │
└────────────────┬─────────────────────────────┘
                 │ lib/ipc.ts → window.conxa.send()
┌────────────────▼─────────────────────────────┐
│  Python Backend (python/backend.py)          │
│  stdio JSON-RPC: newline-delimited JSON      │
│  Protocol:                                   │
│    request  → {id, type, payload}            │
│    result   ← {id, type: "result", result}  │
│    error    ← {id, type: "error", code, msg}│
│    event    ← {type: "event", id, ...}       │
│  Threading: one thread per request           │
│  Async loop: background thread for Playwright│
└──────────────────────────────────────────────┘
```

### 2.2 Python Backend Commands

The backend dispatches on `type` field. All commands are in `backend.py`:

| Command | Purpose |
|---|---|
| `ping` | Health check |
| `bootstrap` | First-run dep download (NSIS, runtime binary) |
| `login` / `logout` / `whoami` | Clerk PKCE auth |
| `start_recording` / `stop_recording` | Playwright session lifecycle |
| `get_recording_status` | Live event count |
| `run_pipeline` | Normalize raw events |
| `compile` | Full compile → SkillPackage |
| `create_plugin` / `list_plugins` / `get_plugin` / `delete_plugin` | Plugin CRUD |
| `list_workflows` / `update_workflow` / `delete_workflow` | Workflow management |
| `build_plugin` | Build data-only plugin folder |
| `build_installer` | NSIS installer + cloud publish + upload |
| `test_workflow` | Local runtime test |
| `publish` | Push skill pack to cloud |
| `get_workflow` / `patch_step` / `reorder_steps` / `insert_step` / `delete_step` | Workflow editor |
| `validate_workflow` / `sign_off_workflow` | Quality gate |
| `list_skills` / `get_skill_document` / `delete_skill` / `rename_skill` | Skill library |
| `list_skill_packages` / `list_skill_package_files` | Skill pack browser |
| `list_runs` / `get_run` / `get_metrics` | Run history |
| `get_usage` | LLM proxy quota |

### 2.3 Data Directory Layout (Build Studio)

```
~/.conxa/              (or SKILL_DATA_DIR)
├── plugins/
│   └── {plugin_id}/
│       ├── plugin.json        (Plugin model)
│       └── auth/
│           └── auth.json      (Playwright storageState — NEVER in build output)
├── sessions/
│   └── {session_id}/
│       ├── events.jsonl       (raw RecordedEvent stream)
│       └── screenshots/
├── skills/
│   └── {skill_id}/
│       ├── skill.json         (SkillPackage JSON)
│       └── assets/            (screenshot thumbnails)
├── skill-packs/
│   └── {company_slug}/
│       ├── pack.json          (manifest with sync_endpoint, tracking)
│       └── {skill_slug}/
│           ├── execution.json
│           ├── recovery.json
│           └── inputs.json
├── runs/
│   └── {plugin_id}.jsonl
├── cache/
│   └── sessions/              (staged auth for runtime test)
├── deps/
│   ├── nsis/makensis.exe
│   └── runtime/{ver}/runtime-win.exe
└── kv/                        (filesystem fallback for DB)
```

### 2.4 Bootstrap Flow

On first launch, `services/bootstrap.py` runs `ensure_all()`:

1. Fetches `GET /api/v1/updates/deps-manifest` (public, no auth).
2. Downloads and SHA-256 verifies NSIS zip → extracts to `deps/nsis/`.
3. Downloads and verifies `runtime-win.exe` → places in `deps/runtime/{ver}/`.
4. Runs `playwright install chromium` to install the bundled browser.

This is idempotent — already-present deps are skipped.

---

## 3. Conxa Cloud

### 3.1 Architecture

```
Vercel (frontend)                    Render (backend)
──────────────────                   ─────────────────────────
Next.js 16                           FastAPI + uvicorn
conxa-cloud/frontend/                conxa-cloud/backend/
                                     
/app/(marketing)/    ← public site   app/main.py
/app/(protected)/    ← dashboard     app/api/
/app/sign-in/        ← Clerk embed   app/llm/router.py
/app/api/v1/[...]/   ← proxy        app/services/
route.ts             ← proxy to      
                       API_ORIGIN    PostgreSQL (SKILL_DATABASE_URL)
```

### 3.2 API Routes

All under `/api/v1/` except health endpoints:

| Prefix | Description | Auth |
|---|---|---|
| `GET /healthz` | Liveness | Public |
| `GET /readyz` | Readiness (DB ping) | Public |
| `POST /api/v1/llm/proxy/{text,vision}` | Metered LLM proxy | Clerk JWT + X-Conxa-Client header |
| `GET /api/v1/llm/proxy/usage` | Token quota status | Clerk JWT |
| `POST /api/v1/plugins/publish` | Skill pack publish | Clerk JWT |
| `POST /api/v1/plugins/{slug}/installer/upload` | Upload .exe | Clerk JWT |
| `GET /api/v1/installers/{slug}` | Public installer download | Public |
| `GET /api/v1/skill-packs/{co}/delta` | Runtime skill sync | Rate-limited; token optional |
| `POST /api/tracking/{co}/events` | Telemetry ingest | Package tracking token |
| `GET /api/v1/tracking/companies` | Company list | Clerk JWT |
| `GET /api/v1/tracking/{co}/runs` | Run summaries | Clerk JWT |
| `GET /api/v1/tracking/{co}/runs/{run_id}` | Run timeline | Clerk JWT |
| `GET /api/v1/updates/deps-manifest` | Bootstrap manifest | Public |
| `GET /api/v1/updates/runtime-manifest` | Runtime self-update manifest | Public |
| `GET /api/v1/updates/studio-manifest` | Studio download info | Public |
| `GET /api/v1/skill-packs/{company}/delta` | Skill-pack delta sync — authenticated by installer-embedded sync_token | Bearer: `pack.json.sync_token`; 401 if invalid |
| `POST /api/v1/telemetry/runtime-start` | Runtime phone-home — stores `runtime_registrations` KV entry per `(company, platform)` | Public (non-critical) |
| `GET /api/v1/telemetry/runtimes` | Runtime registration list for dashboard (active/stale, version distribution) | Clerk JWT |
| `GET /api/v1/audit-events` | Audit log for the authenticated workspace (publish, installer upload, plugin create/delete) | Clerk JWT |
| `POST /api/v1/subscriptions` | Create Razorpay subscription | Clerk JWT |
| `POST /api/v1/billing/webhook` | Razorpay webhook | Webhook secret HMAC |
| `GET /api/v1/dashboard` | Dashboard data | Clerk JWT |
| `GET /api/v1/plugins` | Plugin list | Clerk JWT |
| `GET /api/v1/runs` | Run list (local) | Clerk JWT |
| `GET /api/v1/jobs/{job_id}` | Job status | Clerk JWT |

### 3.3 Authentication Middleware

`app/api/security.py` — `ProductionRequestMiddleware`:

1. Attaches a request ID to every request.
2. Enforces body size limits (1MB general; 250MB for publish/upload).
3. When `SKILL_AUTH_REQUIRED=true`:
   - Extracts `Authorization: Bearer <token>`.
   - Verifies against Clerk JWKS (`SKILL_CLERK_JWKS_URL`).
   - Attaches `request.state.auth` with subject, org_id, claims.
4. Public paths bypass auth: health endpoints, installer downloads, update manifests, telemetry ingest, skill-pack delta GETs.

### 3.4 Workspace / Principal Model

`app/services/saas.py` provides `Principal`:

```python
@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str      # org_id from Clerk, or personal_<user_id>
    workspace_slug: str
    workspace_name: str
    role: str              # "owner" | "member" | "admin"
    email: str | None
    name: str | None
    auth_provider: str     # "clerk" | "local"
    identity_source: str
```

In local dev (`SKILL_AUTH_REQUIRED=false`), all requests are treated as a synthetic local principal.

### 3.5 Billing

Razorpay is the wired payment gateway (`app/api/razorpay_routes.py`). The config has orphaned `stripe_*` fields — these are **not wired** in any route handler (see §17).

---

## 4. Conxa Runtime (MCP)

### 4.1 Process Model

```
Claude Desktop (host)
        │  MCP stdio transport
        ▼
runtime-win.exe (runtime/server.js bundled by @yao-pkg/pkg)
        │
        ├── @modelcontextprotocol/sdk  (MCP protocol)
        ├── run.js                     (step executor)
        ├── skill_loader.js            (skill registry)
        ├── sync.js                    (skill pack sync)
        ├── auth_manager.js            (token + session management)
        ├── browser.js                 (Playwright browser lifecycle)
        └── tracker.js                 (telemetry event emission)
```

### 4.2 MCP Tools

Defined in `server.js` `_toolDefinitions()`:

| Tool | Description |
|---|---|
| `list_skills` | List installed skills, optionally filtered by company |
| `execute_skill` | Execute a single workflow skill |
| `execute_sequence` | Execute an ordered list of skills in one browser session |
| `get_skill_inputs` | Return input schema for a skill |
| `get_execution_status` | Status of current execution |
| `cancel_execution` | Stop the running execution |
| `refresh_skills` | Force immediate skill pack sync |
| `get_runtime_status` | Runtime diagnostics (non-mutating) |
| `read_skill_files` | Debug: inspect raw execution.json / recovery.json |

### 4.3 Startup Sequence

```mermaid
sequenceDiagram
    participant CD as Claude Desktop
    participant RT as Runtime (server.js)
    participant Cloud as Conxa Cloud

    CD->>RT: spawn process (MCP stdio)
    RT->>RT: resolve CONXA_DIR, CONXA_DATA_DIR
    RT->>RT: set PLAYWRIGHT_BROWSERS_PATH
    RT->>RT: load skill index from cache (SKILL_PACKS_DIR)
    RT->>Cloud: GET /updates/runtime-manifest (cached 24h)
    Cloud-->>RT: {version, url, sha256}
    RT->>RT: if newer version → download runtime-win.exe.next
    RT->>CD: MCP connect (StdioServerTransport)
    RT->>RT: syncSkillPacks() — 15s timeout
    RT->>Cloud: GET /skill-packs/{co}/delta?since={ver}
    Cloud-->>RT: {files: [...base64 content...]}
    RT->>RT: atomic write + SHA-256 verify each file
    RT->>RT: reload skill index
    RT->>Cloud: POST /api/v1/telemetry/runtime-start (fire-and-forget, after sync)
    RT-->>CD: ready (skill index loaded)
```

### 4.4 Skill Pack Directory Layout (Runtime)

```
~/.conxa/                       (CONXA_DIR)
├── runtime/
│   └── runtime-win.exe         (the MCP server itself)
├── chromium/                   (Playwright browser)
├── skill-packs/
│   └── {company}/
│       ├── pack.json           (manifest: sync_endpoint, tracking, version)
│       └── {skill_slug}/
│           ├── execution.json  (SkillPackage steps + selectors)
│           ├── recovery.json   (recovery blocks + anchors)
│           └── inputs.json     (input schema)
└── logs/
    ├── runtime.log             (JSONL, rotated at 10MB)
    └── recovery.log            (recovery event log, rotated at 10MB)

~/.conxa/ or %APPDATA%/Conxa/  (CONXA_DATA_DIR)
├── cache/
│   ├── sessions/
│   │   ├── {co}_state.json         (AES-256-GCM encrypted storageState)
│   │   ├── {co}_raw_state.json     (plaintext fallback)
│   │   └── {co}_auth_meta.json
│   ├── runtime-update-cache.json
│   └── runtime-update-pending.json
└── data/
    ├── executions/{id}/
    │   ├── state.json
    │   └── checkpoint.json
    └── runs/{plugin}.jsonl
```

---

## 5. Authentication & Platform Communication

### 5.1 Authentication Systems Summary

| System | Auth Mechanism | Token Storage | Identity Provider |
|---|---|---|---|
| Build Studio | Clerk PKCE OAuth | OS keyring (`keyring` lib) | Clerk (clerk.conxa.in) |
| Cloud (API) | Clerk JWT verification | N/A (stateless) | Clerk JWKS |
| Cloud (Frontend) | Clerk Next.js SDK | Clerk session cookie | Clerk |
| Runtime | Per-company opaque token | OS keychain (`keytar`) | Conxa Cloud (POST /auth/refresh) |

### 5.2 Build Studio Login Flow

```mermaid
sequenceDiagram
    participant User
    participant Studio as Build Studio (Renderer)
    participant Backend as Python Backend
    participant Browser as System Browser
    participant Clerk as clerk.conxa.in
    participant Cloud as Conxa Cloud

    User->>Studio: Click "Sign In"
    Studio->>Backend: {type: "login"}
    Backend->>Backend: generate PKCE verifier + challenge
    Backend->>Backend: start localhost HTTP server on port 52741
    Backend->>Browser: open authorize URL (Clerk PKCE)
    Browser->>Clerk: GET /oauth/authorize?code_challenge=...
    User->>Clerk: complete login in browser
    Clerk->>Browser: redirect to http://127.0.0.1:52741/cb?code=...
    Browser->>Backend: GET /cb?code=...&state=...
    Backend->>Clerk: POST /oauth/token (code + verifier)
    Clerk-->>Backend: {access_token, refresh_token, expires_in}
    Backend->>Clerk: GET /oauth/userinfo (Bearer access_token)
    Clerk-->>Backend: {sub, email, name, org_id}
    Backend->>Backend: store tokens in OS keyring (service="conxa-studio")
    Backend-->>Studio: {type: "result", result: {org_id, user_id, name, email}}
    Studio->>Studio: update AuthContext, show dashboard
```

**Token lifecycle:** Tokens are refreshed transparently in `auth_service.get_token()` when within 60 seconds of expiry using the stored `refresh_token`. Stored in OS credential manager (Windows Credential Manager / macOS Keychain / Linux Secret Service via the `keyring` Python library).

### 5.3 Cloud API Authentication

Every protected API call from the Build Studio:
1. Calls `auth_service.get_token()` — returns a valid Clerk `access_token`.
2. Sets `Authorization: Bearer <token>` header.
3. Cloud middleware (`ProductionRequestMiddleware`) verifies JWT via PyJWT + JWKS.
4. Attaches `request.state.auth` with `subject`, `org_id`, `claims`.
5. `principal_from_request()` in `saas.py` constructs a `Principal` object for RBAC.

### 5.4 Runtime Sync Token (per-company, installer-embedded)

The runtime uses an **installer-embedded sync token** for all Conxa Cloud communication (skill-pack delta fetches). End users never interact with Conxa auth — they only log into their own target platform.

#### 5.4.1 Token lifecycle

The sync token is a `secrets.token_urlsafe(32)` string minted **at publish time** and stored server-side in the `sync_tokens` KV namespace keyed by company slug. It is stable across republishes (reused if present) and can be rotated by deleting the KV entry.

**Publish → installer flow:**

```
Build Studio publishes skill pack
  → POST /api/v1/plugins/publish
  → cloud mints sync_token (publish_routes._sync_token())
  → sync_token written into cloud-side pack.json
  → publish response returns sync_token
  → Build Studio writes sync_token into local pack.json (backend.py)
  → installer_builder stages pack.json verbatim into NSIS
  → installer ships pack.json to C:\Program Files\Conxa\skill-packs\{company}\
```

`installer_builder.py` guards that `pack.json` has `sync_token` before staging — build fails fast if the pack was never published.

#### 5.4.2 Runtime sync

On every cold start, `sync.js:_doSync()` reads `pack.sync_token` directly from the on-disk `pack.json` and sends it as `Authorization: Bearer` to the delta endpoint. No keytar lookup, no user login.

```mermaid
sequenceDiagram
    participant RT as Runtime (server.js)
    participant S as sync.js
    participant Cloud as Conxa Cloud

    Note over RT: Cold start
    RT->>S: syncSkillPacks(SKILL_PACKS_DIR)
    S->>S: read pack.json → sync_token
    S->>Cloud: GET /api/v1/skill-packs/{company}/delta?since=... (Bearer: sync_token)
    Cloud->>Cloud: compare_digest(stored_sync_token, token)
    Cloud-->>S: delta files (or 200 up-to-date / 401 invalid token)
    S->>S: atomic write + SHA-256 verify updated files
```

`GET /api/v1/skill-packs/{company}/delta` is in `PUBLIC_SKILL_PACK_SYNC_PREFIXES` so middleware does not apply — the handler validates the sync token directly. In local dev (`SKILL_AUTH_REQUIRED=false`) validation is skipped.

#### 5.4.3 Session encryption (per-machine key)

When executing a skill the runtime loads the target-platform Playwright `storageState` (browser cookies/localStorage). It is encrypted at rest with AES-256-GCM using a **per-machine** key derived via HKDF (`auth_manager.js:_deriveKey()`). The key is a 32-byte random value generated on first use per company and stored in the OS keychain via keytar (service `conxa-session`).

This decouples session encryption from the sync token: a leaked installer exposes the sync token (granting read-only access to that company's skill packs) but **cannot decrypt any user's session file** since the encryption key is machine-specific.

### 5.5 Skill Publishing Flow

```mermaid
sequenceDiagram
    participant Studio as Build Studio
    participant Backend as Python Backend
    participant Cloud as Conxa Cloud

    Note over Studio: After build_installer command
    Backend->>Backend: read skill-packs/{slug}/pack.json
    Backend->>Backend: collect all files as base64
    Backend->>Cloud: POST /api/v1/plugins/publish
    Note over Backend,Cloud: Bearer Clerk JWT<br/>body: {slug, files[], skill_pack_version, skills[]}
    
    Cloud->>Cloud: _assert_owner(slug, workspace_id)
    Note over Cloud: First publish claims slug ownership.<br/>Subsequent publishes from same workspace only.
    Cloud->>Cloud: write files to data/skill-packs/{slug}/
    Cloud->>Cloud: generate tracking token (secrets.token_urlsafe(32))
    Cloud->>Cloud: store tracking_tokens[slug] in kv_store
    Cloud->>Cloud: upsert Plugin record in kv_store
    Cloud-->>Backend: {tracking: {tracking_token, tracking_url}, sync_url}
    
    Backend->>Backend: rewrite pack.json with tracking + sync_endpoint
    Backend->>Cloud: POST /api/v1/plugins/{slug}/installer/upload
    Note over Backend,Cloud: Bearer Clerk JWT<br/>body: raw .exe bytes
    Cloud->>Cloud: store to data/installers/{slug}/installer.exe
    Cloud->>Cloud: store meta.json (sha256, filename, version)
    Cloud-->>Backend: {download_url, sha256}
    Backend-->>Studio: {cloud_download_url, cloud_tracking_url}
```

### 5.6 Skill Sync Flow (Runtime → Cloud)

```mermaid
sequenceDiagram
    participant RT as Runtime
    participant Cloud as Conxa Cloud

    Note over RT: On startup (async, after MCP connect)
    RT->>RT: read all pack.json files in SKILL_PACKS_DIR
    loop for each company
        RT->>RT: getToken(company) from keytar
        RT->>Cloud: GET /api/v1/skill-packs/{co}/delta?since={version}
        Note over RT,Cloud: Bearer token<br/>Rate-limited: 1 req / 5 min per token
        Cloud->>Cloud: compare versions
        alt version unchanged
            Cloud-->>RT: {files: []} (empty delta)
        else version changed
            Cloud-->>RT: {files: [...base64 content...], current_version}
            RT->>RT: backup existing skill dirs
            RT->>RT: atomicWrite each file (SHA-256 verified)
            RT->>RT: update pack.json skill_pack_version
            RT->>RT: clean up backups
        end
    end
    RT->>RT: reload skill index from updated files
```

**CURRENT STATE gap:** The delta endpoint ships **all files** when the version differs — no per-file checksum diffing. Each delta call transfers the entire skill pack regardless of what changed. Code comment in `skillpack_update_routes.py`: `"Simplified implementation"`.

### 5.7 Telemetry Flow

```mermaid
sequenceDiagram
    participant RT as Runtime (tracker.js)
    participant Cloud as Conxa Cloud

    Note over RT: During/after skill execution
    RT->>RT: createTracker(pack.tracking)
    RT->>RT: emit events: wf_start, step_ok, step_fail, wf_ok, wf_fail
    RT->>Cloud: POST /api/tracking/{co}/events
    Note over RT,Cloud: Header: X-Tracking-Token: {token from pack.json}<br/>body: {rid, pid, pv, rv, uid, wid, evts[]}
    Cloud->>Cloud: _verify_token(company, token)
    Cloud->>Cloud: db_append("tracking/{co}", run_id, [enriched])
    Cloud-->>RT: 202 Accepted (fire-and-forget)
```

Telemetry is compact: short event codes (`wf_start`, `wf_ok`, `wf_fail`, `step_ok`, `step_fail`, `recovery_tier{1-5}`), timestamps, and step indices. The tracking token is embedded in `pack.json` at publish time and never requires the end-user to authenticate.

### 5.8 Runtime Self-Update Flow

Three files are updated atomically on every runtime release: `runtime-win.exe` (the Node pkg bundle), `keytar.node` (native module — Node-ABI-specific), and Chromium (Playwright-revision-specific). All three must stay in sync or the runtime crashes.

```mermaid
sequenceDiagram
    participant RT as Runtime
    participant Cloud as Conxa Cloud
    participant FS as Filesystem

    RT->>FS: check runtime-update-pending.json
    alt pending update exists and runtime.exe.next present
        RT->>RT: write update.bat to tmp dir
        RT->>RT: spawn cmd.exe /C update.bat (detached)
        Note over RT: bat (runs after 3s delay, detached):<br/>1. move runtime.exe.next → runtime.exe<br/>2. if keytar.node.next exists: move → keytar.node<br/>3. runtime.exe --install-playwright (idempotent)<br/>4. delete bat
        RT->>RT: continue serving (process replaced on next cold start)
    end
    
    RT->>FS: check runtime-update-cache.json (24h TTL)
    alt cache miss or expired
        RT->>Cloud: GET /api/v1/updates/runtime-manifest
        Cloud-->>RT: {version, url, sha256, keytar_url, keytar_sha256, playwright_version, chromium_revision}
        RT->>FS: write runtime-update-cache.json
    end
    
    RT->>RT: compare manifest.version vs RUNTIME_VERSION
    alt newer version available
        RT->>Cloud: GET manifest.url (download runtime-win.exe)
        RT->>RT: SHA-256 verify
        RT->>FS: write runtime.exe.next
        RT->>Cloud: GET manifest.keytar_url (download keytar.node)
        RT->>RT: SHA-256 verify
        RT->>FS: write keytar.node.next
        RT->>FS: write runtime-update-pending.json {version, ready, has_keytar}
        Note over RT: Update applied on NEXT cold start
    end
```

**`--install-playwright` behaviour:** Uses `playwright-core/cli` bundled inside the exe (no system npm/npx dependency). Playwright checks if the exact Chromium revision from `browsers.json` is already on disk; if so, exits immediately. Only downloads on a Playwright version bump (~120 MB).

### 5.9 Data Ownership Summary

| Data | Owner | Storage Location |
|---|---|---|
| Plugin metadata (local) | Build Studio | `data/plugins/{id}/plugin.json` |
| Auth session (Playwright state) | Build Studio (LOCAL ONLY) | `data/plugins/{id}/auth/auth.json` |
| Raw recorded events | Build Studio | `data/sessions/{id}/events.jsonl` |
| Compiled skills | Build Studio | `data/skills/{id}/skill.json` |
| Built skill packs | Build Studio | `data/skill-packs/{co}/` |
| Published skill packs | Conxa Cloud | `data/skill-packs/{co}/` on Render |
| Installer binaries | Conxa Cloud | `data/installers/{co}/installer.exe` |
| Tracking tokens | Conxa Cloud | `kv_store` table (tracking_tokens namespace) |
| Slug ownership | Conxa Cloud | `kv_store` table (publish_owners namespace) |
| Telemetry / run events | Conxa Cloud | `kv_store` table (tracking/{co} namespace) |
| Runtime skill packs | End-user machine | `~/.conxa/skill-packs/` |
| Runtime auth tokens | End-user machine | OS keychain (keytar) |
| Runtime browser sessions | End-user machine | `~/.conxa/cache/sessions/` |

---

## 6. Recording Pipeline

**Location:** `conxa-builder/python/conxa_compile/recorder/`

### 6.1 Capture

`session.py` — `RecorderSession` wraps a Playwright browser context:

1. Playwright launches Chromium with stored auth (`storageState`).
2. `bridge.js` is injected into every frame (including iframes) via `page.addInitScript`.
3. Bridge captures: `click`, `dblclick`, `right_click`, `type`, `fill`, `focus`, `select`, `select_option`, `set_checkbox`, `set_radio`, `date_pick`, `drag_drop`, `keyboard_shortcut`, `upload`, `navigate`, `scroll`, `tab_open`, `tab_switch`, `popup`, `frame_enter`, `frame_exit`, `dialog_appeared`, `dialog_accept`, `dialog_dismiss`.
4. Each event carries: `action`, `url`, `frame` (iframe chain), `target` (element signals), `value`, `ts`.
5. `frame_extractor.py` walks the iframe parent chain to accumulate page-level bounding box offsets.
6. Events stream to `session_events.py` which appends to `events.jsonl`.

### 6.2 Iframe Chain Preservation

Every recorded event carries a `frame` object with:
- `src` — iframe src URL
- `frame_id` — Playwright frame ID
- `parent_chain` — ordered list of parent frame IDs

This chain is preserved verbatim through compile and execution. Bounding boxes are page-level (offsets accumulated up the chain during recording).

---

## 7. Compilation Pipeline

**Location:** `conxa-builder/python/conxa_compile/`

### 7.1 Pipeline Stages

```
events.jsonl (raw RecordedEvents)
        │
        ▼  pipeline/normalize.py
        │  • Canonicalize action types
        │  • Filter noise events
        │  • Resolve frame references
        │
        ▼  pipeline/dedupe.py
        │  • Remove duplicate consecutive events
        │  • Collapse rapid-fire clicks
        │
        ▼  pipeline/enrich.py
        │  • Add DOM snapshot refs
        │  • Augment with surrounding text context
        │  • Compute visibility signals
        │
        ▼  pipeline/selectors.py
        │  • Extract raw selector candidates from recorded DOM
        │
        ▼  compiler/build.py:compile_skill_package()
           │
           ├── LLM: intent_llm.py → WorkflowIntentGraph (one call per workflow)
           │
           ├── For each step:
           │   ├── LLM: llm_selector_generator_v2.py
           │   │   → ElementFingerprint + compiled_selectors[]
           │   ├── LLM: semantic_llm.py → semantic_description
           │   ├── validation_planner.py → Assertion[]
           │   ├── recovery_policy.py → RecoveryBlock
           │   └── confidence/layered.py → confidence score
           │
           └── → SkillPackage (models/skill_spec.py)
```

### 7.2 LLM Calls Per Step

All LLM calls route through `conxa_core.llm.get_router()`. In Build Studio, the router singleton is replaced with `LLMProxyClient` which forwards to the cloud's metered proxy. The cloud proxy itself has the multi-provider pool (Groq, Google AI Studio, NVIDIA NIM, etc.).

| LLM Client | Call | Token cost (approx) |
|---|---|---|
| `intent_llm.py` | Per-workflow intent graph | High (full DOM context) |
| `llm_selector_generator_v2.py` | Per-step selector generation | Medium (DOM snippet) |
| `semantic_llm.py` | Per-step semantic description | Low (element context) |
| `recovery_llm.py` | Per-step recovery block | Medium |
| `anchor_vision_llm.py` | Per-step vision anchors (if enabled) | Medium (screenshot) |

### 7.3 SkillPackage Output Schema

```python
SkillPackage:
  meta: SkillMeta                      # id, version, title, source_session_id
  inputs: list[dict]                   # parameterizable inputs schema
  skills: list[SkillBlock]             # one block per workflow
    └── steps: list[SkillStep]
          action: str | dict            # action type + params
          intent: str                   # human-readable intent
          element_fingerprint: ElementFingerprint
            role, tag, inner_text, aria_label, name,
            placeholder, label_text, data_testid,
            input_type, css_class_tokens, anchor_phrases,
            position_hint
          compiled_selectors: list[str] # ranked CSS/XPath selectors
          validation: ValidationBlock
            assertions: list[Assertion] # url_pattern, selector_present, etc.
          recovery: RecoveryBlock
            intent, anchors, strategies, confidence_threshold
          semantic_description: str
          snapshot_ref: str             # DOM snapshot blob ref
  intent_graph: WorkflowIntentGraph    # goal, steps, decision_points
  compile_report: dict                  # status, steps_total, min_confidence
```

---

## 8. Skill Packaging Pipeline

**Location:** `conxa-builder/python/conxa_compile/plugin_builder.py`

After compilation, `build_plugin()` produces a data-only plugin folder:

```
output/skill_package/{company}-plugin/
├── plugin.json          (manifest: slug, name, target_url, skills[])
├── CLAUDE.md            (rendered from plugin_templates/plugin/Claude.md.tmpl)
├── index.md             (rendered from plugin_templates/plugin/index.md.tmpl)
├── pack.json            (version manifest)
└── skills/
    └── {skill_slug}/
        ├── execution.json   (compiled steps + selectors)
        ├── recovery.json    (recovery blocks + anchors)
        └── inputs.json      (input schema)
```

**Invariant:** Auth files (`auth.json`) are NEVER placed in the build output. The `build_installer` command explicitly checks and refuses if `auth.json` is found under the skill pack dir.

The installer (`installer_builder.py`) wraps this with NSIS to produce a `.exe` that:
1. Installs the skill pack to `~/.conxa/skill-packs/{company}/`.
2. Installs `runtime-win.exe` to `C:\Program Files\Conxa\runtime\`.
3. Installs Chromium to `C:\Program Files\Conxa\chromium\`.
4. Registers the MCP server in Claude Desktop config.

---

## 9. Execution Pipeline

**Location:** `runtime/run.js`

### 9.1 Step Execution Loop

For each step in `execution.json`:

```
1. Poll pause signal (control file: allow pause/resume via API)
2. waitForPageLoadAndPace() — adaptive timing, human-like pacing
3. waitForUrlState() — pre-step URL gate (if step.url defined)
4. executeStep() — primary action
   ├── interpolate input variables ({{variable}} substitution)
   ├── resolveElement() — find DOM element
   │   ├── Tier 1: compiled_selectors[] (try in order)
   │   ├── Tier 2: a11y tree (role + name lookup)
   │   ├── Tier 3: LLM semantic recovery (Claude via MCP)
   │   ├── Tier 4: Vision recovery (screenshot → Claude)
   │   └── Tier 5: Escalation (human review)
   └── withLocator() — perform the action
5. verifyAssertions() — check Assertion[]
   ├── required assertions → halt on failure
   └── advisory assertions → log warning
6. writeCheckpoint() — step-level recovery point
7. tracker.emit() — telemetry event
```

### 9.2 Human-Like Pacing

`CONXA_HUMAN_PACING` (default: enabled) adds randomized delays:

| Action | Delay range |
|---|---|
| click | 180–300ms |
| fill | 100–200ms |
| type | 100–200ms |
| select | 160–260ms |
| focus | 80–160ms |
| scroll | 120–220ms |

After navigation steps: waits for `domcontentloaded` + 600ms observer pause.

---

## 10. Recovery Architecture

### 10.1 Five-Tier Recovery Cascade

When `resolveElement()` fails to find the target:

| Tier | Mechanism | LLM Cost | Trigger |
|---|---|---|---|
| **T1** | Compiled selectors (CSS/XPath, ranked) | Zero | Always first |
| **T2** | Accessibility tree (role + name lookup) | Zero | T1 all fail |
| **T3** | LLM semantic recovery (current DOM → Claude) | Yes (text) | T2 fails |
| **T4** | Vision recovery (screenshot → Claude) | Yes (vision) | T3 fails |
| **T5** | Escalation (human review queue) | Zero | T4 fails / budget exceeded |

Retry budget: `RETRY_BUDGET_MAX = 3` per (skill, step_index). On exhaustion → `retry_budget_exhausted` event logged, escalate.

### 10.2 Selector Scoring

`ElementFingerprint` gives runtime a stable identity to score DOM candidates against:
- `data_testid` — highest stability signal
- `aria_label`, `role`, `name` — a11y tree signals
- `inner_text` — visible text (max 120 chars)
- `anchor_phrases` — relational context phrases
- `position_hint` — normalized x/y (0.0–1.0)

Each candidate gets a weighted score. Highest scorer is used.

### 10.3 Dialog-Scoped Recovery

If the element is expected inside a dialog, recovery first restricts the search to `[role="dialog"]`, `[role="alertdialog"]`, `[aria-modal="true"]`, `.modal`. Fuzzy fallback expands to the full page if no match.

### 10.4 No-Recovery Steps

`frame_enter` and `frame_exit` actions carry `no_recovery_block`. These are structural markers, not interactive steps, and are never retried.

---

## 11. Skill Sync & Update Architecture

### 11.1 Skill Pack Delta Sync

**Endpoint:** `GET /api/v1/skill-packs/{company}/delta?since={version}`

**CURRENT STATE (simplified):**
- If `current_version == since_version` → return `{files: []}`.
- Otherwise → return ALL files in the skill pack as base64.
- No per-file checksum comparison.
- Rate-limited: 1 request per 5 minutes per token (in-memory `_rate_cache` dict).

**FUTURE STATE:** Per-file SHA-256 comparison against a version manifest. Only changed files transferred. Redis-backed rate limiting.

### 11.2 Atomic File Updates

`sync.js` uses transactional file writes:
1. Backup existing skill dir (`skill_dir.bak`).
2. Write each file to `.tmp` suffix.
3. SHA-256 verify content matches delta entry.
4. Atomic rename `.tmp` → target.
5. On any failure → restore from backup.
6. On full success → delete backups.

### 11.3 Runtime Self-Update

Checked on every cold start via `/api/v1/updates/runtime-manifest` (24h local cache). Three interdependent files are staged and applied together:

| File | Staged as | Applied by |
|---|---|---|
| `runtime-win.exe` | `runtime.exe.next` | bat: `move /Y` |
| `keytar.node` | `keytar.node.next` | bat: `move /Y` (if present) |
| Chromium | N/A (downloaded by Playwright) | bat: `runtime.exe --install-playwright` |

The bat runs detached after a 3-second delay (giving the current process time to exit). `--install-playwright` uses `playwright-core/cli` bundled inside the exe and is idempotent — it exits immediately if the correct Chromium revision is already on disk.

The manifest includes `keytar_url` and `keytar_sha256` so the runtime knows which `keytar.node` build matches the new Node ABI. If the keytar download fails (network issue), the old file stays; the update still applies but token storage may break if the Node ABI changed.

---

## 12. Telemetry Architecture

### 12.1 Event Schema (compact)

Emitted by `runtime/tracker.js`:

| Event code | When | Fields |
|---|---|---|
| `wf_start` | Workflow begins | `ts`, `tot` (total steps) |
| `step_ok` | Step succeeds | `ts`, `si` (step index), `tier` (recovery tier used) |
| `step_fail` | Step fails | `ts`, `si`, `code` (error code) |
| `recovery_tier{N}` | Recovery attempted | `ts`, `si`, `tier` |
| `wf_ok` | Workflow succeeds | `ts`, `dur`, `tot`, `rec` (recovered steps) |
| `wf_fail` | Workflow fails | `ts`, `dur`, `fsi` (failed step index), `fc` (failure code) |

### 12.2 Batch Payload

```json
{
  "rid": "run_id",
  "pid": "plugin_id",
  "pv": "plugin_version",
  "rv": "runtime_version",
  "uid": "user_id_hash",
  "wid": "workspace_id",
  "sv": 1,
  "evts": [{"e": "wf_start", "ts": 1717000000, "tot": 5}, ...]
}
```

Header: `X-Tracking-Token: <token from pack.json>`

### 12.3 Storage & Query

- Stored in `kv_store` table under namespace `tracking/{company}`, key = `run_id`.
- `db_append()` appends batches to a JSON array.
- Queried by `tracking_routes.py` — Clerk-authenticated dashboard endpoints.
- Workspace scoping: `_batches_for_principal()` filters by `workspace_id` in batch.

---

## 13. LLM Router Architecture

**Location:** `conxa-cloud/backend/app/llm/router.py`

### 13.1 Provider Pool

The cloud maintains a flat pool of `(provider, endpoint, api_key, text_model, vision_model)` tuples. Multiple keys per provider expand to multiple entries.

Enabled providers (current defaults):
- **Groq** — `llama-3.3-70b-versatile` (text), `llama-4-scout-17b` (vision)
- **Google AI Studio** — `gemini-2.5-flash` (both)
- **NVIDIA NIM** — `llama-4-maverick-17b` (text), `llama-3.2-90b-vision` (vision)

Disabled by default (toggle via env): Cerebras, Together, OpenRouter, Mistral.

### 13.2 Router Behavior

- Round-robin with cooldown: entries that return 429 are cooled for `llm_router_cooldown_secs` (60s default).
- Failover: on error, moves to next entry.
- Max retries: `llm_router_max_retries` (3 default).
- Fast text preference: when `llm_router_prefer_fast_for_text=true`, text calls prefer low-latency providers.

### 13.3 Build Studio → Cloud Proxy

Build Studio's LLM calls go through `services/llm_proxy_client.py`:
- Target: `POST /api/v1/llm/proxy/text` or `/api/v1/llm/proxy/vision`
- Header: `Authorization: Bearer <Clerk access_token>`
- Header: `X-Conxa-Client: build-studio`
- Monthly quota enforced at cloud: `llm_proxy_monthly_token_quota` (default 5M tokens/org).
- `CloudUnreachable` and `QuotaExceeded` exceptions propagate up to the compiler, which surfaces them as `compile_error` events to the renderer.

---

## 14. Database & Storage Architecture

### 14.1 KV Store (Primary Abstraction)

`conxa_core/db.py` provides a dual-mode key-value store:

```
Mode 1: PostgreSQL (SKILL_DATABASE_URL set)
  Table: kv_store
    namespace  TEXT        PRIMARY KEY part 1
    key        TEXT        PRIMARY KEY part 2
    data       JSONB
    created_at TIMESTAMPTZ
    updated_at TIMESTAMPTZ

Mode 2: Filesystem (no SKILL_DATABASE_URL)
  data/kv/{namespace}/{sha256(key)}.json
```

Key namespaces in use:
- `plugins` — Plugin model JSON
- `publish_owners` — slug → workspace_id ownership
- `tracking_tokens` — company → {token, workspace_id, ...}
- `tracking/{company}` — run_id → [event batches]
- `runs` — plugin_id → [run records]
- `selector_cache` — DOM hash → selector candidates

### 14.2 Additional File Storage

Beyond the KV store:
- `data/sessions/{id}/events.jsonl` — raw event stream (append-only)
- `data/sessions/{id}/screenshots/` — PNG screenshots per step
- `data/skills/{id}/skill.json` — compiled SkillPackage
- `data/skill-packs/{co}/` — built plugin folder
- `data/installers/{co}/installer.exe` — uploaded installer binary

### 14.3 Production Database Requirements

In production (`SKILL_AUTH_REQUIRED=true`), the app refuses to start without `SKILL_DATABASE_URL`. The filesystem fallback is **blocked** in production.

---

## 15. Security Model

### 15.1 Current Security Boundaries

| Boundary | Mechanism |
|---|---|
| Cloud API auth | Clerk JWT (RS256, verified via JWKS) |
| Build Studio auth | Clerk PKCE (no implicit flow) |
| Runtime session encryption | AES-256-GCM, key = HKDF(company_token) |
| Telemetry ingest | Package tracking token (secrets.token_urlsafe(32)) |
| Installer download | Public (slug in URL is the only "credential") |
| Skill pack sync | Rate-limited; token optional in local dev |
| Auth file exclusion | Compiler refuses if auth.json found in build input |
| Request body limits | 1MB general; 250MB publish/upload |
| Slug ownership | First publisher claims; workspace-scoped |
| CORS | Explicit allowlist (`SKILL_CORS_ORIGINS`) + Vercel preview regex |

### 15.2 Security Gaps (Current State)

- Sync token is a shared secret across all of a company's end users — a leaked installer grants read-only access to that company's data-only skill packs. Session encryption uses a separate per-machine key so individual users' sessions remain protected.
- Skill pack delta rate limit is in-memory — not persisted across restarts.
- No device registration or runtime instance tracking.
- Installer download is fully public — anyone with the slug URL can download.
- `SKILL_TRACKING_HMAC_SECRET` is optional; without it, telemetry accepts any token.

---

## 16. Deployment Architecture

### 16.1 Cloud Backend (Render)

```
Build root:        conxa-cloud/backend/
Build command:     ./build.sh
  pip install ../../packages/conxa-core
  pip install -r requirements.txt
Start command:     ./start.sh
  uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health check:      GET /healthz (liveness)
Deploy gate:       GET /readyz (DB ping)
System deps:       Aptfile (Playwright/Chromium system packages — not used in cloud, leftover)
Environment:       SKILL_AUTH_REQUIRED=true requires:
  SKILL_DATABASE_URL, SKILL_CLERK_ISSUER, SKILL_CLERK_JWKS_URL,
  SKILL_CORS_ORIGINS, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET,
  RAZORPAY_WEBHOOK_SECRET, + at least one *_API_KEYS
```

### 16.2 Cloud Frontend (Vercel)

```
Project root:      conxa-cloud/frontend/
Build command:     npm run build
Deploy:            next start
Environment:
  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
  CLERK_SECRET_KEY
  API_ORIGIN  (points to Render backend)
```

### 16.3 Build Studio (Windows)

Distributed as a `.exe` installer built via `electron-builder` + NSIS. Ships:
- Electron app (Node.js bundled)
- PyInstaller backend bundle (`dist/backend/`)
- Does NOT ship: Chromium, NSIS, runtime-win.exe (fetched on first launch via bootstrap)

### 16.4 Runtime (End-User Machine)

Ships inside the company-specific installer produced by Build Studio. Installs to:
- Windows: `C:\Program Files\Conxa\runtime\runtime-win.exe`
- Mac: `~/.conxa/runtime/runtime` (planned; Mac support is in build scripts but Windows is the primary target)

---

## 17. Known Gaps & Tech Debt

| Gap | Location | Severity | Notes |
|---|---|---|---|
| Delta sync ships all files | `skillpack_update_routes.py` | Medium | Code comment: "simplified implementation" |
| Sync token is a shared installer secret | `sync_tokens` KV + pack.json | Low | Read-only, single-company scope; per-machine session encryption key mitigates session-file risk |
| Rate limit cache in-memory | `_rate_cache` dict | Medium | Not shared across instances |
| Stripe fields in config | `config.py:stripe_*` | Low | Orphaned; Razorpay is the wired gateway |
| No device/runtime registration | Cloud | High | No visibility into how many runtimes are active |
| No enterprise RBAC enforcement | `app/services/rbac.py` | High | Scaffolded but not wired to routes |
| Runtime auth per-company only | `auth_manager.js` | Medium | No per-user identity at runtime |
| Installer download fully public | `publish_routes.py:get_installer` | Medium | Slug guessing gives access to installer |
| `research/frontend/` is a dead prototype | `research/` dir | Low | Not deployed; delete or document |
| Aptfile has Playwright deps | `conxa-cloud/backend/Aptfile` | Low | Cloud doesn't use Playwright; leftover from old arch |
| `worker.py` scaffold | `app/worker.py` | Low | Queue scaffold, not implemented |
| No multi-region blob storage | `blob_read_write_token` config | Medium | Config field exists; not wired |
| `selector_cache_ttl_days` | Config | Low | Cache exists but no GC scheduler wired |
