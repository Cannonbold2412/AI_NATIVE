# Security Gaps

**Status:** Current as of 2026-06-14  
**Scope:** Conxa platform — Build Studio, Conxa Cloud, Runtime  
**Audience:** Internal engineering, security reviewers, auditors

This document is the detailed reference for known security gaps across all three tiers. For the high-level security model (auth mechanisms, trust boundaries, invariants) see **[`docs/TRD.md §15`](TRD.md#15-security-model)**. For general tech debt see **`docs/TRD.md §17`**.

---

## Severity Scale

| Label | Meaning |
|---|---|
| **Critical** | Exploitable without insider access; leads to auth bypass, RCE, or data breach at scale |
| **High** | Requires one additional condition (leaked secret, compromised CDN, etc.); significant blast radius |
| **Medium** | Limited blast radius or requires attacker to already have partial access |
| **Low** | Defence-in-depth weakness; no realistic exploit path in current deployment |

---

## Summary Table

| ID | Title | Tier | Severity | File(s) |
|---|---|---|---|---|
| [SG-01](#sg-01-rbac-not-enforced-on-routes) | RBAC not enforced on routes | Cloud API | High | `app/services/rbac.py`, `app/api/` |
| [SG-02](#sg-02-proxy-identity-bypass) | Proxy identity bypass via shared header secret | Cloud API | High | `app/services/saas.py` |
| [SG-03](#sg-03-x-forwarded-host-not-sanitised) | X-Forwarded-Host not sanitised in `_api_base()` | Cloud API | Medium | `app/api/publish_routes.py` |
| [SG-04](#sg-04-in-memory-rate-limit-on-delta-endpoint) | In-memory rate limit cleared on restart | Cloud API | Medium | `app/api/skillpack_update_routes.py` |
| [SG-05](#sg-05-tracking-hmac-secret-is-optional) | Tracking HMAC secret optional — fallback accepts any token | Cloud API | Medium | `app/api/tracking_routes.py` |
| [SG-06](#sg-06-telemetry-payload-unbounded) | Telemetry payload unbounded — no event count or field size cap | Cloud API | Medium | `app/api/tracking_routes.py` |
| [SG-07](#sg-07-installer-download-is-fully-public) | Installer download is fully public | Distribution | Medium | `app/api/publish_routes.py` |
| [SG-08](#sg-08-sync-token-is-a-shared-installer-secret) | Sync token is a shared installer secret | Distribution | Low | `app/api/skillpack_update_routes.py`, `runtime/sync.js` |
| [SG-09](#sg-09-no-code-signing-on-self-update-binary) | No code signing on self-update binary | Runtime | High | `runtime/server.js` |
| [SG-10](#sg-10-update-bat-uses-mathrandom-for-temp-filename) | Update `.bat` uses `Math.random()` for temp filename | Runtime | Low | `runtime/server.js` |
| [SG-11](#sg-11-plaintext-session-fallback-is-silent) | Plaintext session fallback is silent on keytar failure | Runtime | Medium | `runtime/auth_manager.js` |
| [SG-12](#sg-12-company-name-used-in-file-paths-without-re-validation) | Company name used in file paths without re-validation | Runtime | Low | `runtime/auth_manager.js`, `runtime/sync.js` |
| [SG-13](#sg-13-no-per-user-identity-at-runtime) | No per-user identity at runtime — `uid` is spoofable | Runtime | Low | `runtime/server.js`, `runtime/tracker.js` |
| [SG-14](#sg-14-read_skill_files-mcp-tool-exposes-skill-logic-to-llm-context) | `read_skill_files` MCP tool exposes skill logic to LLM context | Runtime | Low | `runtime/server.js` |

---

## SG-01 — RBAC Not Enforced on Routes

**Severity:** High  
**Component:** Cloud API — `app/services/rbac.py`, `app/api/`

### Description

`app/services/rbac.py` exposes only `require_admin()`, which checks that a `Principal`'s role is `"admin"` or `"owner"`. As of this writing, this function is called in **exactly one place**: `app/api/razorpay_routes.py` (subscription creation). Every other authenticated endpoint enforces workspace membership (`ensure_principal`) and, for mutation endpoints, workspace ownership of the target slug (`_assert_owner`), but not role-based access.

Consequence: any authenticated workspace `"member"` can publish skill packs, upload installers, read all tracking data, and consume LLM quota — all operations that should be gated to `"admin"` or `"owner"`.

### Current Mitigation

Clerk's org membership system is the outer gate. A member first needs to be invited to the org. Seat enforcement gaps (see TRD §13.4) mean seat limits are advisory only.

### Recommended Fix

Wire `require_admin()` (or a new `require_role(principal, min_role)`) into publish, installer-upload, and installer-delete endpoints. Add role checks to LLM proxy if per-role quota tiers are needed. The scaffold is in place — it just needs to be called.

---

## SG-02 — Proxy Identity Bypass

**Severity:** High  
**Component:** Cloud API — `app/services/saas.py:_trusted_proxy_identity()` (line 161)

### Description

When `SKILL_API_PROXY_SHARED_SECRET` is set and a request carries the `X-Conxa-Proxy-Secret` header with a matching value, `principal_from_request()` builds a full `Principal` from three additional headers — `X-Conxa-User-Id`, `X-Conxa-Org-Id`, `X-Conxa-Org-Role` — **without requiring a Clerk JWT**. The design intent is to let the Vercel Next.js route handler (`/app/api/v1/[...]/route.ts`) forward enriched identity claims from Clerk's server SDK.

If `SKILL_API_PROXY_SHARED_SECRET` leaks (env var exposure in Render, Vercel, or Build Studio), an attacker can impersonate any Clerk user ID with any org and role — a full authentication bypass. The secret is a single symmetric value with no rotation mechanism.

### Current Mitigation

The secret is never sent to end users or embedded in installers. Risk is limited to server-side env exposure. `secrets.compare_digest` prevents timing attacks on the comparison.

### Recommended Fix

- Rotate to a per-request HMAC signature (e.g. HMAC-SHA256 over `timestamp + user_id`) rather than a static shared secret, or
- Require a valid Clerk JWT **plus** the proxy header (the proxy path should never need to bypass JWT verification — it just needs to augment claims).
- Implement a secret rotation procedure and document it in `ROUTER_SETUP.md`.

---

## SG-03 — X-Forwarded-Host Not Sanitised in `_api_base()`

**Severity:** Medium  
**Component:** Cloud API — `app/api/publish_routes.py:_api_base()` (line 176)

### Description

`_api_base()` constructs the base URL for `sync_endpoint` and `tracking_url` — values that are written into the published `pack.json` and shipped inside installers. It reads `X-Forwarded-Proto` and `X-Forwarded-Host` from the request headers (first value before any comma), and if both are present it uses them verbatim.

If the API is ever reachable directly (without a trusted reverse proxy stripping or validating these headers), an attacker could set `X-Forwarded-Host: attacker.example.com` in a publish request. The installer's `pack.json` would then contain `sync_endpoint` and `tracking_url` pointing at the attacker's server, causing all runtimes that install this pack to exfiltrate skill-sync requests and telemetry to the attacker.

### Current Mitigation

Render's infrastructure typically forwards only its own `X-Forwarded-*` headers. In practice, the attack surface requires the attacker to also have a valid Clerk JWT to reach the publish endpoint.

### Recommended Fix

Harden `_api_base()` to only trust headers from known reverse proxies (validate against an allowlist in config), or always use a configured `SKILL_API_BASE_URL` env var and ignore forwarded host headers entirely. This is the simpler and more robust fix.

---

## SG-04 — In-Memory Rate Limit Cleared on Restart

**Severity:** Medium  
**Component:** Cloud API — `app/api/skillpack_update_routes.py:_rate_cache` (line 25)

### Description

The skill-pack delta endpoint (`GET /api/v1/skill-packs/{company}/delta`) rate-limits to 1 request per 5 minutes per token using a module-level dict `_rate_cache`. This dict is in-process memory and is cleared on every process restart. Render restarts the process on each new deploy and on crash recovery.

Consequence: an attacker with a valid sync token can drain the full skill pack on every process restart. On a busy service with frequent deploys this could be every few minutes.

### Current Mitigation

Skill packs contain only compiled automation data (selectors, intents, recovery strategies) — no credentials, no secrets, no user data. The rate limit is a bandwidth/cost control, not a confidentiality control.

### Recommended Fix

Move the rate limit state to Redis (or Render's KV) keyed by `sha256(token)[:16]`. The connection details can be injected via `SKILL_REDIS_URL`. The TRD §11.1 already notes this as the intended future state.

---

## SG-05 — Tracking HMAC Secret Is Optional

**Severity:** Medium  
**Component:** Cloud API — `app/api/tracking_routes.py:_verify_token()` (line 47)

### Description

`_verify_token(company, token)` first checks whether a per-company tracking token exists in `kv_store`. If it exists and matches, the call is accepted. If no token is stored **and** `SKILL_TRACKING_HMAC_SECRET` is not set in config, the function returns `{"workspace_id": ""}` — effectively accepting the request as a local/dev call with an empty workspace.

In production, every published pack gets a tracking token via `_tracking_token()` in `publish_routes.py`. But if the KV store loses a token (e.g. a failed migration or explicit deletion), the fallback silently accepts all telemetry from anyone who POSTs to that company's endpoint.

### Current Mitigation

Accepted telemetry is write-only from an attacker's perspective — it can inflate run counts but cannot read data. The `SKILL_TRACKING_HMAC_SECRET` env var is documented in `ROUTER_SETUP.md` as required for production.

### Recommended Fix

In production (`SKILL_AUTH_REQUIRED=true`), change the fallback to **reject** when `tracking_tokens[company]` is absent (return 401, not a synthetic workspace dict). The HMAC secret path can remain for legacy scenarios but should log a warning when used.

---

## SG-06 — Telemetry Payload Unbounded

**Severity:** Medium  
**Component:** Cloud API — `app/api/tracking_routes.py:ingest_events()` (line 647)

### Description

The ingest endpoint accepts `body.get("evts", [])` and appends it verbatim to the `tracking/{company}` KV row via `db_append`. There is no cap on the length of the `evts` array, no limit on the size of individual event fields, and no check that field names match the documented compact schema (`e`, `ts`, `si`, `tier`, etc.).

An attacker with a valid tracking token (embedded in a leaked installer) can POST arbitrarily large payloads to inflate KV storage and dashboard query times.

The 1MB general body cap in `ProductionRequestMiddleware` provides some protection, but a legitimate-looking payload can still contain many events approaching 1MB.

### Recommended Fix

- Cap `evts` array at a reasonable maximum (e.g. 200 events per batch).
- Truncate or reject individual field values that exceed a sane length (e.g. 256 chars per field).
- Consider a per-company daily ingest quota (track in KV alongside the telemetry).

---

## SG-07 — Installer Download Is Fully Public

**Severity:** Medium  
**Component:** Distribution — `app/api/publish_routes.py:get_installer()` (line 509)

### Description

`GET /api/v1/installers/{slug}` streams the installer `.exe` to anyone who knows the slug. Slugs are validated with `_validate_slug()` (alphanumeric + `-_`, max 64 chars) but not treated as secrets. They appear in dashboard URLs, in `pack.json` embedded in every installer, and potentially in marketing materials.

The installer bundles: the runtime exe, Chromium, the compiled skill pack (data-only), and `pack.json` (which contains the sync token and tracking token). Downloading the installer is therefore equivalent to obtaining the sync token.

### Current Mitigation

Skills packs contain no credentials. Session encryption uses a separate per-machine key, so obtaining the installer cannot decrypt any user's browser session. The slug is required to be known to the downloader.

### Recommended Fix

Short-term: generate a per-download signed URL (time-limited, signed with `SKILL_INSTALLER_SIGNING_KEY`) and serve the binary via redirect, so the stable slug URL becomes a meta-endpoint rather than a direct download. This removes the ability to share a permanent download link.  
Long-term: require the end user to be authenticated with the company's identity provider before receiving the installer (delivered as a first-party install flow, not a public link).

---

## SG-08 — Sync Token Is a Shared Installer Secret

**Severity:** Low  
**Component:** Distribution — `app/api/skillpack_update_routes.py:_verify_sync_token()` (line 53), `runtime/sync.js`

### Description

The sync token (`secrets.token_urlsafe(32)`) is minted at first publish and reused across all subsequent publishes and all installer copies for that company. Every end user who installs the plugin has the same token embedded in their `pack.json`. The token grants read access to the company's current skill pack delta endpoint.

Because the token is in `pack.json` inside every installer binary, it is effectively a publicly-distributable credential for anyone with access to the installer file (see SG-07).

### Current Mitigation

- The token grants **read-only** access to data-only skill pack files (selectors, intents, recovery strategies — no credentials).
- Session encryption (`AES-256-GCM`, per-machine HKDF key stored in OS keychain) is entirely separate from the sync token, so a leaked installer cannot decrypt any user's browser session.
- The token can be rotated by deleting the `sync_tokens[slug]` KV entry, which forces a new token on the next publish.

### Recommended Fix

Issue per-install tokens at installer-download time (requires solving SG-07 first), or move to short-lived tokens derived from the long-lived root token (runtime exchanges the root for a short-lived one at startup, mitigating the impact of leaked installers).

---

## SG-09 — No Code Signing on Self-Update Binary

**Severity:** High  
**Component:** Runtime — `runtime/server.js:_checkRuntimeUpdate()` (line 214)

### Description

The runtime self-update mechanism downloads `runtime-win.exe` from a URL supplied in the manifest (`GET /api/v1/updates/runtime-manifest`). It verifies the SHA-256 hash against the value in the manifest. However:

1. The manifest is fetched over HTTPS but the manifest URL and content are **not code-signed** by Conxa.
2. The downloaded binary is **not code-signed** with a Conxa Authenticode certificate.
3. If the manifest endpoint or CDN delivery is compromised (e.g. via a supply-chain attack on Render), an attacker can replace both the manifest hash and the binary — the SHA-256 check passes because the hash is from the same compromised source.

The resulting `runtime.exe.next` is then applied on the next cold start via a `.bat` file, giving the attacker persistent code execution on every end-user machine that has Conxa installed.

### Recommended Fix

- Sign `runtime-win.exe` with a Conxa Authenticode certificate and verify the signature in `_applyPendingUpdate()` before executing.
- Additionally, sign the manifest JSON with a Conxa private key and verify the signature in `_checkRuntimeUpdate()` using a Conxa public key bundled inside the current binary (so the trust anchor is in the already-installed binary, not fetched from the network).

---

## SG-10 — Update `.bat` Uses `Math.random()` for Temp Filename

**Severity:** Low  
**Component:** Runtime — `runtime/server.js:_applyPendingUpdate()` (line 182)

### Description

The update script writes a `.bat` file to `os.tmpdir()` with a suffix derived from `Math.random().toString(36).slice(2)`. `Math.random()` is not a cryptographically secure PRNG. In a targeted attack scenario, an adversary who can create files in `%TEMP%` could pre-create `conxa-update-<predicted-suffix>.bat` files to be executed when the runtime applies its update.

In practice, `Math.random()` produces ~52 bits of entropy in V8, making prediction impractical without additional information about the random state.

### Recommended Fix

Replace `Math.random().toString(36).slice(2)` with `crypto.randomBytes(12).toString("hex")` (already imported in the file) for the temp filename suffix.

---

## SG-11 — Plaintext Session Fallback Is Silent

**Severity:** Medium  
**Component:** Runtime — `runtime/auth_manager.js:saveRawSession()` (line 99)

### Description

When `_getKeytar()` fails to load the native `keytar.node` module (e.g. ABI mismatch immediately after a self-update that swaps `keytar.node`), the module falls back to a JSON file (`~/.conxa/cache/.keytar.json`) instead. More critically, within the runtime session flow, a keytar failure in `getSessionKey()` silently causes `saveEncryptedSession()` to throw, and the caller (`auth_manager.refreshSession()`) then calls `saveRawSession()` — writing the full Playwright `storageState` (cookies, localStorage, session tokens for the **target platform**) as plaintext to `{company}_raw_state.json`.

The end user sees no warning. The file mode is `0o600`, which on Windows is not meaningfully enforced.

This window is most dangerous during the keytar ABI swap in `_applyPendingUpdate()`: between moving `keytar.node.next` and the next process restart, `keytar.node` is temporarily the new ABI but the running process still has the old ABI loaded.

### Current Mitigation

The raw session file is scoped to the user's local machine at `%APPDATA%\Conxa\cache\sessions\`. An attacker needs local filesystem access to read it.

### Recommended Fix

- In `saveEncryptedSession`, if encryption fails, log a warning and return without falling back to plaintext.
- At startup in `auth_manager.js`, after successfully loading keytar, check for any existing `{company}_raw_state.json` files and re-encrypt them, then delete the plaintext originals.
- Emit a visible log event (`"warn"` level) whenever a plaintext session file is written or read.

---

## SG-12 — Company Name Used in File Paths Without Re-Validation

**Severity:** Low  
**Component:** Runtime — `runtime/auth_manager.js` (line 77, 99), `runtime/sync.js`

### Description

The runtime reads `company` from the `pack.json` files in `SKILL_PACKS_DIR` and uses it directly in `path.join(sessionsDir, `${company}_state.json`)`. The value is not re-validated against the slug allowlist (`[a-zA-Z0-9-_]`) before use.

Company slugs are validated server-side by `_validate_slug()` when published, and the `pack.json` files in `SKILL_PACKS_DIR` are written by either the installer or `sync.js` (which verifies SHA-256 integrity). However, if a user manually edits `pack.json` and sets `company` to a path-traversal value (e.g. `../../etc/passwd`), `path.join` on Node.js would resolve it relative to the session directory.

On Windows, `\` in the company field would also traverse directories.

### Current Mitigation

`path.join` normalises `..` components but does not restrict the result to stay within `sessionsDir`. Exploitation requires local file access to modify `pack.json`, which already implies significant local access.

### Recommended Fix

Add a slug validation function in `sync.js` / `auth_manager.js` and sanitise the `company` field when reading from disk:
```js
function isValidSlug(s) { return /^[a-zA-Z0-9_-]{1,64}$/.test(s); }
```
Reject packs with invalid company slugs during sync load.

---

## SG-13 — No Per-User Identity at Runtime

**Severity:** Low  
**Component:** Runtime — `runtime/server.js`, `runtime/tracker.js`

### Description

The runtime authenticates to Conxa Cloud per-company only (via the sync token in `pack.json`). There is no per-user Conxa identity on the end-user machine. Telemetry events include a `uid` field populated from `INSTALL_ID` — a random UUID generated on first run and stored in `~/.conxa/data/install_identity.json`. This UUID:

1. Is locally generated with no cryptographic binding to any user identity or machine hardware.
2. Can be copied or spoofed by anyone with filesystem access.
3. Has no association with the target-platform identity (the credentials used to log into the automated web application).

This means telemetry run counts are advisory and can be spoofed, and there is no way to distinguish between runs from two different human users on the same machine vs. the same user across reinstalls.

### Recommended Fix

This is acceptable for the current product stage where Conxa is a per-company distribution model. Document that `uid` is an installation identifier, not a user identifier, and do not surface it as a "user" metric in the dashboard.

---

## SG-14 — `read_skill_files` MCP Tool Exposes Skill Logic to LLM Context

**Severity:** Low  
**Component:** Runtime — `runtime/server.js:_toolDefinitions()` (read_skill_files tool)

### Description

The MCP tool `read_skill_files` allows Claude Desktop (and by extension, the active Claude conversation) to read the raw `execution.json` and `recovery.json` files for any installed skill. These files contain:

- Compiled CSS/XPath selectors for every interactive element in the automated workflow
- Semantic descriptions of each workflow step
- Recovery strategies and anchor phrases
- Target URLs and application-specific context

While this data is not secret (it's already installed on the end-user machine), surfacing it in the LLM context means a user asking Claude to "explain how this skill works" will receive a detailed technical breakdown of the compiled automation — including selectors that could be used to interact with the target application outside of the skill's intended scope.

### Current Mitigation

The tool is labelled `Debug` in its description. Actual exploitation requires the end user to explicitly invoke it (or Claude to decide to call it unprompted, which the MCP protocol allows).

### Recommended Fix

Consider restricting `read_skill_files` to a debug-mode flag (`CONXA_DEBUG=1`) so it is not available in standard production installs. Alternatively, strip or summarise the raw selector data before returning it to the LLM (return intent descriptions only, not raw CSS/XPath).

---

## Cross-Reference: TRD §17 (Known Gaps & Tech Debt)

The following gaps from `TRD.md §17` overlap with security concerns and are tracked there but not duplicated here:

| TRD §17 entry | Security relevance |
|---|---|
| No enterprise RBAC enforcement | Covered by SG-01 above |
| Sync token is a shared installer secret | Covered by SG-08 above |
| Rate limit cache in-memory | Covered by SG-04 above |
| Installer download fully public | Covered by SG-07 above |
| No device/runtime registration | Partially addressed by `runtime_registrations` KV (TRD §3.2); full gap is SG-13 |
| `SKILL_TRACKING_HMAC_SECRET` optional | Covered by SG-05 above |
