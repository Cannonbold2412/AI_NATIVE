# Authentication and Auto-Updater — How They Work

This document explains exactly how authentication and automatic updates flow across all three Conxa systems: **Build Studio**, **Conxa Cloud**, and **Runtime/MCP**.

---

## Part 1 — Authentication

There are two completely separate authentication systems in Conxa. They share no tokens and exist for different purposes.

| System | Who authenticates | Protocol | Token storage |
|---|---|---|---|
| Build Studio → Cloud | SaaS vendor (developer) | Clerk PKCE OAuth | OS keyring (`keyring` Python lib) |
| Runtime → Target website | End-user's browser session | Playwright `storageState` | Encrypted file on disk (AES-256-GCM) |

---

### 1.1 Build Studio Authentication (Clerk PKCE)

The Build Studio authenticates the SaaS vendor against Clerk so it can call the Conxa Cloud API for LLM proxying, publishing, and billing.

#### Login flow

```
Build Studio (renderer)          Build Studio (Python backend)       Clerk (clerk.conxa.in)
─────────────────────────        ──────────────────────────────      ──────────────────────
User clicks "Sign in"
  │
  └─→ cmd('login')
                                  1. Generate PKCE pair
                                     verifier = random 48 bytes
                                     challenge = SHA-256(verifier), base64url
                                  2. Generate random `state` token
                                  3. Bind HTTP server on 127.0.0.1:52741–52750
                                     (fixed port range so redirect_uri can be
                                      pre-registered in Clerk — random ports can't)
                                  4. Build authorize URL:
                                     GET /oauth/authorize
                                       ?response_type=code
                                       &client_id=Z7O8UdIVowd3Aegx
                                       &redirect_uri=http://127.0.0.1:{port}/cb
                                       &scope=profile email offline_access user:org:read
                                       &code_challenge={challenge}
                                       &code_challenge_method=S256
                                       &state={state}
                                  5. webbrowser.open(authorize_url)
                                                                      User logs in via browser
                                                                      Clerk redirects to:
                                                                      http://127.0.0.1:{port}/cb
                                                                        ?code=XYZ&state=ABC
                                  6. Local HTTP server catches redirect
                                     Verifies state matches
                                  7. POST /oauth/token
                                       grant_type=authorization_code
                                       code=XYZ
                                       code_verifier={verifier}
                                       client_id=...
                                       redirect_uri=...
                                     (no client_secret — this is a public PKCE client)
                                                                      Returns:
                                                                        access_token
                                                                        refresh_token
                                                                        expires_in
                                  8. GET /oauth/userinfo (Bearer access_token)
                                     Extracts: sub, email, org_id, name
                                  9. Saves JSON to OS keyring:
                                     service="conxa-studio", account="session"
                                     { access_token, refresh_token, exp, userinfo }
  ←─ identity { org_id, user_id, email, name }
```

**Key design decisions:**

- **No client secret.** Clerk is configured as a public OAuth app. The `CONXA_CLERK_CLIENT_SECRET` env var is optional; `auth_service.py` only sends it if present. Never commit a default value.
- **Fixed port range (52741–52750)** for the local callback server. Clerk requires exact redirect URI pre-registration; random ports cannot be registered.
- **Cloudflare workaround.** The token endpoint at `clerk.conxa.in` is behind Cloudflare, which blocks Python's default user-agent. The code sends a Chrome-style `User-Agent` header.
- **Userinfo size limit.** Windows Credential Manager has a ~2500-byte limit. Only 5 fields are kept from `/oauth/userinfo`: `sub`, `email`, `name`, `full_name`, `org_id`.

#### Token refresh

On every `get_token()` call (which happens before every LLM proxy request), the service checks if the access token expires within 60 seconds. If so, it silently calls `POST /oauth/token` with `grant_type=refresh_token` and saves the new token set to the keyring. The app never shows a re-login prompt unless the refresh token itself has expired.

#### How the token is used

Every LLM compile call in Build Studio goes through `LLMProxyClient`:

```
Build Studio (Python compiler)          Conxa Cloud API
──────────────────────────────          ───────────────
POST /api/v1/llm/proxy/text
  Authorization: Bearer {access_token}
  X-Conxa-Client: build-studio
  Body: { task, payload, timeout_ms }
                                         Middleware verifies Clerk JWT (RS256)
                                         Extracts org_id → applies quota
                                         Forwards to LLM provider pool
                                         Returns LLM response
```

On HTTP 401, `LLMProxyClient` retries once after triggering token refresh. On HTTP 429, it raises `QuotaExceeded`.

---

### 1.2 Cloud API Authentication (Clerk JWT verification)

All Conxa Cloud API endpoints except a small public allowlist require a valid Clerk JWT.

**Public (no auth required):**
- `GET /healthz`, `GET /readyz`
- `GET /api/v1/updates/*` — manifest endpoints (fetched before login)
- `GET /api/v1/installers/*` — installer downloads (no Clerk account needed)
- `GET /api/v1/skill-packs/*` — skill pack delta sync (runtime has its own token)
- `POST /api/v1/tracking/{co}/events` — telemetry ingestion (package token, not Clerk)

**Protected (Clerk JWT required):**
Everything else — LLM proxy, plugin publishing, billing, dashboard.

Verification (`app/api/security.py`):
1. Extract `Authorization: Bearer {token}` header
2. Fetch Clerk JWKS from `settings.clerk_jwks_url` (cached by PyJWKClient)
3. Verify RS256 signature, issuer, and optionally audience
4. Optionally check `azp` (authorized party) against an allowlist
5. Attach `request.state.auth = { subject, org_id, claims }` for downstream handlers

---

### 1.3 Runtime Authentication (Per-Company Token + Session Encryption)

The Runtime is a different system entirely. It authenticates against the Conxa Cloud on behalf of the end customer (to sync skill packs and submit telemetry) and manages Playwright browser sessions on the customer's target websites.

#### Per-company Conxa token (keytar)

Each installed skill pack belongs to a company. The runtime stores one Conxa-issued token per company in the OS credential manager via `keytar` (native Node.js module):

```
keytar service = "conxa"
keytar account = "{company_id}"
value = JSON { token, expires_at }
```

**In the packaged exe:** `keytar.node` is placed as a sibling file next to `runtime-win.exe`. The runtime uses `process.dlopen()` to load it directly (pkg bundles can't include native modules inline).

**Fallback (dev/testing only):** If keytar is unavailable, tokens are stored in a plaintext JSON file at `~/.conxa/cache/.keytar.json`. This is never used in production.

**Token refresh:** If `expires_at` is within 5 minutes, the runtime calls `POST https://apis.conxa.in/auth/refresh` with the old token. A per-company mutex (`_refreshLocks`) prevents concurrent refresh races.

#### Playwright session encryption (AES-256-GCM)

When a skill executes in Playwright, the browser's session state (cookies, localStorage) is saved encrypted to disk:

```
Key derivation: HKDF-SHA-256(Conxa token, salt=32-byte zero, info="conxa-session-v1") → 32-byte key
Encryption: AES-256-GCM, random 12-byte IV per save
File: ~/.conxa/data/sessions/{company}_state.json
     { iv, tag, data } — all base64
```

The session is only decryptable with the same Conxa token used to encrypt it. If the token changes (re-auth), the old session file is unreadable and a fresh session starts — this is intentional.

#### Target website re-login

If the target website's session expires mid-execution, the runtime's `refreshSession()` function:
1. Opens a new Playwright page at the site's login URL
2. Waits up to 3 minutes for the user to complete login
3. Saves the refreshed `storageState` to disk (unencrypted `_raw_state.json` at this stage — Conxa token may not be available yet)
4. Tracks attempts: after 3 failures, escalates to Tier 5 (human review)

On headless Linux (no `DISPLAY`), it returns an error immediately rather than hanging.

---

## Part 2 — Auto-Updater

There are two independent auto-update mechanisms: one for **Build Studio** (the Electron app itself) and one for **Runtime** (the MCP server on the customer machine).

---

### 2.1 Build Studio Auto-Updater (Cloud manifest)

The Build Studio uses a **Cloud `studio-manifest`** for app-level updates. Updates are **mandatory and blocking** — the app does not start until the user applies any available update.

**Installer:** per-user NSIS (`oneClick: true`, `perMachine: false`). No wizard, no UAC prompt on update. Installs under `%LOCALAPPDATA%`.

**Version discovery:** `GET /api/v1/updates/studio-manifest` (public endpoint, no auth). The Render env vars `CONXA_STUDIO_VERSION`, `CONXA_STUDIO_WIN_URL`, and `CONXA_STUDIO_WIN_SHA256` control what version is advertised. The version string may carry a `studio-v` or `v` prefix — this is stripped before semver comparison.

```
App.tsx (renderer gate)              main.js (IPC)                           Cloud manifest
───────────────────────              ─────────────                           ──────────────
On cold start (packaged only):
  update:check IPC call
                                       GET /api/v1/updates/studio-manifest
                                       (8 s timeout; fail-open on error)
                                       stripVersion(manifest.version)
                                       vs. app.getVersion() (semver)
  available=true → block app
  show UpdateRequiredScreen
  user clicks "Update now"
  update:start IPC call
                                       https.get(manifest.win_url)
                                       follow redirects (GitHub → CDN 302)
                                         → "update:status" download-progress events
  live progress bar in UI              SHA-256 verify (if win_sha256 non-empty)
                                         → "update:status" downloaded
  update:install IPC call
                                       spawn(installer, ["--updated","/S","--force-run"])
                                       app.quit()
  (app relaunches as new version)

  available=false (or check error)
  → proceed to identity check
```

**Fail-open:** if the manifest fetch fails (offline, timeout, HTTP error), `update:check` returns `{ available: false, error: <message> }`. The startup gate treats any `error` result the same as "no update" and lets the user through. The Settings "Check for Updates" button surfaces the error message instead of silently reporting "up to date."

**In dev (`IS_DEV = !app.isPackaged`):** `update:check` returns `{ available: false }` immediately — the cloud is not contacted, so dev loops are never blocked. Override with `CONXA_FORCE_UPDATE_SCREEN=1` to preview the mandatory-update UI without a packaged build.

**SHA-256 verification:** if `CONXA_STUDIO_WIN_SHA256` is set on Render, the downloaded installer is SHA-256 checked before `update:install` is allowed. Mismatch deletes the download and emits an error. If the env var is empty, verification is skipped (emit a console warning). **Strongly recommended:** populate `CONXA_STUDIO_WIN_SHA256` for every release.

**NSIS install args** (match electron-builder's `NsisUpdater.doInstall` exactly):
- `--updated` — tells the NSIS script this is an update install
- `/S` — silent mode (no wizard)
- `--force-run` — relaunch the app after installation

**Settings — manual update:** the Settings page includes a "Software Update" card showing the current version and a "Check for Updates" button. On finding a new version it shows "Update now" which drives the same download→install flow. On error it shows the error message.

**Key code locations:**
- `main.js` — `update:check / update:start / update:install / app:version` IPC handlers; `semverGt()`, `stripVersion()`, `pendingUpdate` module state
- `renderer/src/pages/UpdateRequiredScreen.tsx` — mandatory blocking gate (early-return from App)
- `renderer/src/hooks/useUpdater.ts` — shared download state hook used by both the gate and Settings
- `renderer/src/App.tsx` — gate ordering: deps → update check → identity
- `renderer/src/pages/SettingsPage.tsx` — `SoftwareUpdateCard` component

---

### 2.2 Runtime Self-Updater (server.js + updates_routes.py)

The runtime updates itself on every cold start. Three interdependent files are staged and applied together — they must stay in sync or the runtime crashes:

| File | Why it must match | Staged as |
|---|---|---|
| `runtime-win.exe` | The Node pkg bundle itself | `runtime.exe.next` |
| `keytar.node` | Native module compiled against a specific Node ABI | `keytar.node.next` |
| Chromium | Playwright expects a specific revision baked in `browsers.json` | Downloaded by `--install-playwright` |

**Full update sequence on cold start:**

```
1. Check runtime-update-pending.json
   └─ If ready + runtime.exe.next exists:
        Write update.bat (random suffix, tmpdir)
        Spawn detached cmd.exe /C update.bat → exit process

        update.bat (runs after 3s, detached):
          move /Y runtime.exe.next   → runtime.exe
          move /Y keytar.node.next   → keytar.node   (if present)
          runtime.exe --install-playwright             (idempotent)
          del update.bat

2. Check runtime-update-cache.json (24h TTL)
   └─ Cache miss: GET /api/v1/updates/runtime-manifest → cache result

3. Compare manifest.version vs RUNTIME_VERSION
   └─ If newer:
        GET manifest.url           → SHA-256 verify → write runtime.exe.next
        GET manifest.keytar_url    → SHA-256 verify → write keytar.node.next
        Write runtime-update-pending.json {version, ready, has_keytar}
        (applied on NEXT cold start)
```

`--install-playwright` uses `playwright-core/cli` bundled inside the exe — no system npm/npx required. Playwright checks whether the exact Chromium revision from `browsers.json` is already on disk; if so, exits immediately. Only downloads (~120 MB) when the Playwright version actually bumped.

#### How the manifest works

The Cloud API exposes `GET /api/v1/updates/runtime-manifest` (public, no auth). This returns:

```json
{
  "version": "runtime-v1.0.0",
  "url": "https://github.com/Cannonbold2412/AI_NATIVE/releases/download/runtime-v1.0.0/runtime-win.exe",
  "sha256": "<hex>",
  "keytar_url": "https://github.com/Cannonbold2412/AI_NATIVE/releases/download/runtime-v1.0.0/keytar.node",
  "keytar_sha256": "<hex>",
  "min_skill_pack_version": "0.3.0",
  "playwright_version": "1.49.0",
  "chromium_revision": "1148460"
}
```

`keytar_url` and `keytar_sha256` are required so the runtime can update `keytar.node` (a native module compiled against a specific Node ABI) alongside the exe. All values are driven by Render environment variables. To release a new runtime version:
1. CI runs `build-runtime` workflow → publishes `runtime-win.exe` + `keytar.node` to GitHub Releases
2. CI calls `POST /api/v1/updates/runtime-manifest-admin` with new version/url/sha256/keytar fields
3. Render env vars (`CONXA_RUNTIME_VERSION`, `CONXA_RUNTIME_WIN_URL`, `CONXA_KEYTAR_WIN_URL`, etc.) update automatically

#### Skill pack delta sync

On every cold start the runtime also syncs skill packs:

```
runtime/sync.js                           Conxa Cloud API
───────────────                           ────────────────
For each company in ~/.conxa/data/skill-packs/:
  Read pack.json → get sync_endpoint + skill_pack_version
  GET {sync_endpoint}?since={skill_pack_version}
    Authorization: Bearer {company_token}
                                           Returns delta:
                                           { files: [{path, sha256, content_base64|content_url}],
                                             current_version }
  For each file in delta:
    Download content (base64 inline or URL)
    Write to .tmp
    Verify SHA-256
    Atomic rename to final path
  Bump pack.json → skill_pack_version = current_version

  If any file fails: restore all backups, skip this company
```

**Integrity guarantee:** Every file write goes through `atomicWrite()` — write to `.tmp`, verify SHA-256, then `rename()`. If verification fails the temp file is deleted and the old backup is restored. The runtime never runs from a partially-written skill pack.

---

### 2.3 Build Studio Dependency Bootstrap (first launch)

The Build Studio installer is small (Electron + PyInstaller backend only). On first launch it downloads three large dependencies that are not bundled:

| Dep | Location | How versioned |
|---|---|---|
| Chromium | `~/.conxa/deps/chromium/` | Playwright `install chromium` |
| NSIS (makensis.exe) | `~/.conxa/deps/nsis/` | `CONXA_NSIS_URL` on Render |
| runtime-win.exe + keytar.node | `~/.conxa/deps/runtime/{version}/` | `CONXA_RUNTIME_VERSION` on Render |

The manifest is fetched from `GET /api/v1/updates/deps-manifest` (public — called before user logs in).

**Download flow:**
1. App checks `check_status()` — fast offline check of canonical paths
2. If `all_ready = true`: skip bootstrap entirely, go straight to login
3. If any dep missing: show `BootstrapScreen` UI with per-dep progress bars
4. `cmd('bootstrap')` → Python `ensure_all()` → `ensure_chromium()`, `ensure_nsis()`, `ensure_runtime()`
5. Each `ensure_*` is idempotent — safe to re-run if interrupted

**SHA-256 verification:** Both NSIS zip and `runtime-win.exe` are SHA-256 verified against the manifest after download. Mismatch → file deleted, error surfaced with the download URL so IT teams can whitelist on corporate networks.

**Dev mode:** The bootstrap gate is skipped entirely when `window.conxa.isPackaged === false` (i.e. `process.defaultApp` is truthy in Electron dev). Developers manage deps via `scripts/setup.ps1`.

---

## Summary: Which token goes where

```
Token                   Lives in                  Used for
─────────────────────   ──────────────────────    ────────────────────────────────────────
Clerk access token      OS keyring (Python)       Cloud LLM proxy, plugin publish, billing
Clerk refresh token     OS keyring (Python)       Refreshing the access token silently
Conxa company token     OS keyring (Node/keytar)  Skill pack sync, telemetry ingestion
Playwright storageState AES-GCM file on disk      Target website session (cookies/localStorage)
```

No token ever leaves the machine it was issued for. The cloud does not hold Playwright sessions. The runtime does not hold Clerk tokens.
