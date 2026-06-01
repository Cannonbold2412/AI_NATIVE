# Implementation Plan

**Status:** Current as of 2026-06-01  
**Audience:** Engineering team

This plan is grounded in the actual codebase. Each item references the specific file or system that needs to change. Items are ordered by risk and dependency, not effort.

---

## Phase 1 — Architecture Consolidation

**Goal:** Close the gaps that make the current system unreliable in production. No new features. All changes are to correctness, reliability, and observability.

**Timeline estimate:** 4–6 weeks

---

### 1.1 Fix Runtime Auth Token Refresh (Critical)

**What's broken:** `POST /api/v1/auth/refresh` in `conxa-cloud/backend/app/api/skillpack_update_routes.py:post_auth_refresh` is a stub — it echoes the submitted token back with a 30-day expiry regardless of validity. In production, any token (valid or forged) gets refreshed indefinitely.

**Fix:**
- Validate the incoming token against Clerk JWKS before issuing a new token.
- Return HTTP 401 on invalid/expired tokens.
- The endpoint is used by `runtime/auth_manager.js:_doRefresh()`.

**Files:** `skillpack_update_routes.py`, `security.py` (can reuse `verify_clerk_jwt`)

**Risk:** Runtime installs without valid Clerk tokens will start failing sync. Need to ensure all runtime installs have a path to acquire a valid token (see 1.2).

---

### 1.2 Implement Runtime Token Acquisition Flow

**What's missing:** There is no in-product way for a newly installed runtime to acquire an auth token for a company. `auth_manager.js:getAuthChallengeUrl()` generates a challenge URL but nothing triggers the flow end-to-end.

**Fix:**
- Add an MCP tool `setup_company(company)` that:
  1. Gets the auth challenge URL.
  2. Returns it to Claude for the user to open.
  3. After the user completes auth at `app.conxa.in/auth/cli?nonce=...`, the web UI calls `POST /api/v1/auth/cli/complete`.
  4. Runtime polls `POST /api/v1/auth/cli/poll` with the nonce until it gets a token.
  5. Stores token via `auth_manager.setToken(company, token, expiresAt)`.

**Files:** `runtime/server.js` (new tool), `runtime/auth_manager.js`, `skillpack_update_routes.py` (cli/complete + cli/poll already exist), Cloud frontend (`app/auth/cli/page.tsx` needed)

**Risk:** Low — additive change. Existing installations continue to work with whatever tokens they have.

---

### 1.3 Move Nonce Store to Redis (or DB)

**What's broken:** `_auth_nonces` dict in `skillpack_update_routes.py` is in-memory. Server restarts clear all pending CLI auth sessions. Deploying a new version of the cloud backend breaks any in-flight logins.

**Fix:**
- Store nonces in the KV store (`db_set("auth_nonces", nonce, {...})`).
- Add a TTL field (nonces older than 10 minutes are ignored).
- Clean up expired nonces on read.

**Files:** `skillpack_update_routes.py`

**Risk:** Low. In-memory store is fine for small scale; this just makes it restart-safe.

---

### 1.4 Implement Real Per-File Delta Sync

**What's broken:** `skillpack_update_routes.py:_build_delta()` ships **all files** whenever the pack version differs. Every sync call transfers the entire skill pack. For a plugin with 20 skills, this could be 2MB+ per runtime cold start.

**Fix:**
- Maintain a version manifest: a JSON file listing each file's path and SHA-256.
- On delta request: compare the manifest at `since_version` against the current manifest.
- Return only files whose SHA-256 changed.
- The manifest file should be stored alongside the skill pack files.

**Files:** `skillpack_update_routes.py`, `app/api/publish_routes.py` (generate manifest at publish time)

**Risk:** Medium. Must maintain backward compatibility with runtimes that don't send a file-level `since` manifest.

---

### 1.5 Move Rate Limit Cache to Redis

**What's broken:** `_rate_cache` in `skillpack_update_routes.py` is in-memory. Multi-instance deployments (Render horizontal scaling) have no shared rate limit — each instance has its own independent limit.

**Fix:**
- Use Redis (`SKILL_REDIS_URL`) for rate limit storage.
- Fall back to in-memory if Redis is not configured.

**Files:** `skillpack_update_routes.py`, `conxa_core/config.py` (`redis_url` field already exists)

**Risk:** Low. Redis field exists in config; just needs to be wired.

---

### 1.6 Wire RBAC to API Routes

**What's broken:** `app/services/rbac.py` exists but no route handler checks it. All workspace members have full write access to all resources.

**Fix:**
- Define role requirements per endpoint (e.g. publish requires `owner` or `admin`; read requires any member).
- Add `require_role(principal, role)` FastAPI dependency to publish, upload, delete routes.
- Return HTTP 403 with clear message on role mismatch.

**Files:** `app/services/rbac.py`, `publish_routes.py`, `tracking_routes.py`, `plugin_routes.py`

**Risk:** Medium. Changes auth behavior for existing users. Need to ensure all existing workspace owners retain full access.

---

### 1.7 Remove Stripe Config Fields

**What's present but unused:** `config.py` has `stripe_secret_key`, `stripe_webhook_secret`, `stripe_price_id`. No route handler references these. Razorpay is the wired gateway.

**Fix:**
- Remove `stripe_*` fields from `Settings`.
- Update `.env.example` to remove stripe fields.
- Remove from `_validate_production_config` (already absent, but confirm).

**Files:** `packages/conxa-core/conxa_core/config.py`, `.env.example`

**Risk:** Very low. Unused fields. Just cleanup.

---

### 1.8 Delete or Document research/frontend/

**What's present:** `research/frontend/` contains a prototype UI that is not deployed. It consumes context in code reviews and creates confusion about which files are authoritative.

**Fix (option A):** Delete the directory. The authoritative UI is in `conxa-cloud/frontend/` and `conxa-builder/electron/renderer/`.

**Fix (option B):** Move to `docs/ui-prototypes/` with a README explaining it is a research artifact.

**Files:** `research/` directory

**Risk:** Very low. Not in production.

---

## Phase 2 — Production Readiness

**Goal:** Make the platform ready for enterprise evaluation and reliable at scale. This phase adds observability, correctness, and operational controls.

**Timeline estimate:** 6–10 weeks

---

### 2.1 Device & Runtime Registration

**What's missing:** The cloud has no visibility into how many runtimes are deployed, which versions, or which companies they serve. `POST /api/v1/telemetry/runtime-start` exists but stores nothing (returns `{"ok": true}` immediately).

**Fix:**
- On runtime cold start, `POST /telemetry/runtime-start` with `{runtime_version, companies[], platform}`.
- Cloud stores this as a runtime registration record keyed by `(workspace_id, company, platform)`.
- Dashboard shows "active runtimes" count per company.
- Surface in dashboard: runtime version distribution, stale runtimes (not seen in 30 days).

**Files:** `skillpack_update_routes.py:post_telemetry_runtime_start`, Cloud dashboard, `runtime/server.js:_phonehome()`

---

### 2.2 Implement Drift Detection

**What's designed but not implemented:** `SkillMeta.structural_fingerprint` stores the hash of the first 3 steps' landmark selectors. This was designed for pre-execution drift detection.

**Fix:**
- In `runtime/run.js`, before executing step 0: check if current page's landmark selectors match `structural_fingerprint`.
- If mismatch exceeds threshold: emit `drift_detected` event and warn Claude: "This workflow may need to be recompiled. The page structure has changed."
- Do not block execution — warn only.

**Files:** `runtime/run.js`, `runtime/tracker.js`

---

### 2.3 Audit Log

**What's missing:** No record of which user took which action (publish, compile, delete). Required for enterprise security reviews.

**Fix:**
- Add `audit_log` KV namespace.
- Write entries on: publish, installer upload, plugin delete, workflow delete.
- Fields: `user_id`, `workspace_id`, `action`, `resource_type`, `resource_id`, `ts`, `ip`.
- Expose `GET /api/v1/audit/events` (Clerk-authed, owner/admin only, paginated).

**Files:** `publish_routes.py`, `plugin_routes.py`, new `audit_routes.py`

---

### 2.4 macOS Runtime Support

**What's present:** The build scripts reference macOS targets (`build:mac` in `runtime/package.json`). `CONXA_DIR` resolves to `~/.conxa` on non-Windows. The runtime code is platform-aware.

**What's missing:** No macOS installer builder in `installer_builder.py`. No tested macOS distribution path.

**Fix:**
- Add macOS installer generation (PKG or DMG) to `installer_builder.py`.
- Test runtime on macOS (auth_manager, keytar, Playwright).
- Add macOS to the `updates/runtime-manifest` response.

**Files:** `conxa-builder/python/services/installer_builder.py`, `updates_routes.py`

---

### 2.5 Installer Code Signing

**What's missing:** The Windows `.exe` installer is not code-signed. Windows SmartScreen will block it with an "Unknown Publisher" warning for end users.

**Fix:**
- Obtain Windows EV code signing certificate.
- Add `signtool.exe` step to `installer_builder.py` after NSIS build.
- Configurable via env var (`CONXA_SIGN_TOOL_PATH`, `CONXA_SIGN_CERT_PATH`).

**Files:** `conxa-builder/python/services/installer_builder.py`

---

### 2.6 Selector Cache GC

**What's present:** Selector cache (`conxa_core/storage/selector_cache.py`) has a `ttl_days` config (30 days). GC function exists (`snapshots_gc.py`).

**What's missing:** No scheduled job runs the GC. The cache grows without bound.

**Fix:**
- Add a startup task (or Render cron job) to run selector cache GC on schedule.
- Log items evicted and cache size.

**Files:** `conxa_cloud/backend/app/main.py` (lifespan), `selector_cache.py`, `snapshots_gc.py`

---

### 2.7 Hardened Billing Integration

**What's present:** Razorpay routes exist (`razorpay_routes.py`). Config fields are wired. Webhook handling is present.

**What's missing (assumed — not fully reviewed):** Plan enforcement (quota, feature limits) based on subscription status.

**Fix:**
- Define plan tiers (Free, Starter, Pro, Enterprise) with limits (max workflows, max token quota, max installs).
- Enforce limits at publish and compile time.
- Surface plan status in Build Studio and Dashboard.

**Files:** `app/services/saas.py`, `razorpay_routes.py`, `llm_proxy_routes.py`

---

### 2.8 Error Code User-Friendly Mapping (UI)

**What's broken:** Raw error codes (`cloud_unreachable`, `quota_exceeded`, `auth_file_in_build_input`) are shown to users in the Build Studio renderer.

**Fix:**
- Create an error code → human message map in `conxa-builder/electron/renderer/src/lib/`.
- Every error displayed to the user goes through this map.
- Unknown codes show: "Unexpected error: {code}. Contact support."

**Files:** `conxa-builder/electron/renderer/src/lib/errorMessages.ts` (new)

---

## Phase 3 — Enterprise Readiness

**Goal:** Pass enterprise security review and support multi-engineer team workflows.

**Timeline estimate:** 8–12 weeks

---

### 3.1 SSO / SAML

- Enable Clerk Enterprise with SAML support.
- Configure per-organization SSO.
- Map SAML groups to Conxa workspace roles.
- Session management: enforce SSO session timeout policy.

**Dependencies:** Clerk Enterprise plan.

---

### 3.2 Multi-User Workspace Publishing

**Current state:** Only the slug owner can publish updates.

**Fix:**
- Any workspace member with `admin` or `owner` role can publish to a workspace-owned slug.
- Add workspace transfer for slug ownership.
- Implement invitation flow (currently UI exists in Team page but backend not fully wired).

**Files:** `publish_routes.py`, `app/services/saas.py`, `app/services/rbac.py`

---

### 3.3 On-Premise Option

- Package the FastAPI backend as a self-hosted option (Docker Compose).
- Replace Render-specific dependencies with configurable alternatives.
- Document self-hosted configuration.
- Build Studio points to customer's own cloud backend via Settings.

**Files:** `conxa-cloud/backend/Dockerfile` (already exists), `docker-compose.yml` (new)

---

### 3.4 Workflow Version History & Rollback

- Store previous SkillPackage versions (not just the latest).
- Allow publishing a previous version via the dashboard.
- Delta sync serves whichever version the company selects.
- UI shows version timeline.

**Files:** `publish_routes.py`, `skillpack_update_routes.py`, Cloud dashboard

---

### 3.5 Advanced RBAC

- Per-skill access controls (who can read vs. publish specific skills).
- Read-only analyst role (can view telemetry but not trigger builds or publish).
- API key support for CI/CD publishing (Build Studio not required for publishing).

**Files:** `app/services/rbac.py`, `publish_routes.py`

---

### 3.6 Compliance Package

- SOC 2 evidence export (audit log, access controls documentation).
- Data residency option (EU storage).
- Data deletion API (GDPR: delete all telemetry for a run_id or workspace).
- Privacy policy compliance for telemetry (opt-out flag in pack.json).

---

## Phase 4 — AI Agent Platform

**Goal:** Evolve from a packaging/distribution layer into the foundation for AI-native automation products.

**Timeline estimate:** 12–24 weeks (in parallel with Phase 3)

---

### 4.1 Conditional Steps & Branching Logic

**What's needed:** Skills currently execute linearly. Enterprise workflows have conditional paths (e.g. "if the user exists, update them; otherwise create them").

**Design:**
- Add `condition` field to `SkillStep` with a `condition_type` (e.g. `selector_present`, `url_matches`, `assertion_result`).
- Add `branch` field pointing to an alternative skill block.
- Runtime evaluates conditions and branches accordingly.

**Files:** `conxa_core/models/skill_spec.py`, `runtime/run.js`, `conxa-builder/python/conxa_compile/compiler/build.py`

---

### 4.2 Dynamic Input Resolution

**What's needed:** Currently, all inputs must be explicitly provided by the user or Claude before execution starts. Future: Claude derives inputs from conversation context automatically.

**Design:**
- Add `resolve_from_context: bool` flag per input.
- MCP execution tool passes `conversation_context` alongside explicit inputs.
- Runtime uses context for `{{variable}}` substitution when the input is not explicitly set.

**Files:** `runtime/server.js`, `runtime/run.js`, `conxa_core/models/skill_spec.py`

---

### 4.3 Multi-App Skill Sequences

**What's needed:** `execute_sequence` tool already exists and runs skills in a shared browser session. But sequences are ad-hoc (Claude orchestrates). Persistent, named sequences would allow companies to publish "orchestrated workflows" as products.

**Design:**
- Add `SequencePackage` to the skill package schema.
- Publisher defines a sequence: `[{skill: "login"}, {skill: "export_report"}, {skill: "email_report"}]`.
- Runtime `execute_sequence` tool accepts a sequence slug alongside individual skill slugs.

**Files:** `conxa_core/models/`, `runtime/server.js`, `plugin_builder.py`

---

### 4.4 Public Skill Registry / Marketplace

**What's needed:** A searchable directory of published skill packages that any user can browse and install.

**Design:**
- `GET /api/v1/registry/search?q=...&category=...` returns public packages.
- Companies opt-in to public listing at publish time.
- End users install via `install_plugin(slug)` MCP tool (already exists in server.js).
- Marketplace UI in cloud dashboard.

**Files:** Cloud backend new route, Cloud frontend new page, `runtime/server.js` (`install_plugin` tool)

---

### 4.5 API-First Publishing SDK

**What's needed:** Companies want to integrate Conxa publishing into their CI/CD pipeline. Currently requires Build Studio (Windows only).

**Design:**
- Python SDK that wraps the Build Studio compilation pipeline.
- CLI: `conxa compile --session-id ... --output ./dist`.
- CI integration: GitHub Action that compiles + publishes on merge.
- The Build Studio Python backend (`conxa_compile`) is already a self-contained package — the SDK is a thin wrapper.

**Files:** New package in `packages/conxa-sdk/`, GitHub Actions workflow template

---

## Dependency Map

```
Phase 1 (must complete before Phase 2):
  1.1 (auth fix) → 1.2 (token flow) → blocks 2.1 (device registration)
  1.4 (real delta) → blocks 2.2 (drift detection reads manifest)
  1.6 (RBAC wired) → blocks 3.2 (multi-user publishing)

Phase 2 (must complete before Phase 3):
  2.1 (device registration) → blocks 3.3 (on-premise, needs registration model)
  2.3 (audit log) → blocks 3.6 (compliance package)
  2.7 (billing hardened) → blocks Phase 3 (enterprise plans)

Phase 3 and 4 can proceed in parallel.
```

---

## Risk Summary

| Risk | Phase | Severity | Mitigation |
|---|---|---|---|
| Runtime installations without valid tokens break after 1.1 | 1 | High | 1.2 (token acquisition flow) must ship simultaneously with 1.1 |
| RBAC enforcement breaks existing admin workflows | 1 | Medium | Roll out in audit-only mode first; log violations before enforcing |
| Delta sync format change breaks older runtimes | 1 | Medium | Support both manifest-diff and full-pack responses based on request params |
| macOS Playwright + keytar compatibility unknown | 2 | Medium | Test on macOS before committing to timeline |
| Stripe fields removed breaks env that had them set | 1 | Low | Only removing from config schema; env vars with SKILL_STRIPE_ prefix just get ignored |
| Slug claim race condition | 3 | Low | First publish claims; enforce idempotency within same workspace |
