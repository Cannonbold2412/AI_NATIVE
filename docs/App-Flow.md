# App Flow Document

**Status:** Current as of 2026-06-01  
**Scope:** All major user flows across Build Studio, Conxa Cloud, and Runtime

---

## Table of Contents

1. [User Onboarding](#1-user-onboarding)
2. [Build Studio Login](#2-build-studio-login)
3. [Create a Plugin](#3-create-a-plugin)
4. [Record Authentication Session](#4-record-authentication-session)
5. [Record a Workflow](#5-record-a-workflow)
6. [Pipeline & Compilation](#6-pipeline--compilation)
7. [Workflow Editing (HumanEdit)](#7-workflow-editing-humanedit)
8. [Build Plugin](#8-build-plugin)
9. [Build Installer & Publish](#9-build-installer--publish)
10. [End-User Installation](#10-end-user-installation)
11. [Runtime Registration & First Sync](#11-runtime-registration--first-sync)
12. [MCP Skill Execution](#12-mcp-skill-execution)
13. [Execution with Recovery](#13-execution-with-recovery)
14. [Skill Pack Update (Company Side)](#14-skill-pack-update-company-side)
15. [Skill Sync (Runtime Side)](#15-skill-sync-runtime-side)
16. [Runtime Self-Update](#16-runtime-self-update)
17. [Failure Recovery (End User)](#17-failure-recovery-end-user)

---

## 1. User Onboarding

```mermaid
flowchart TD
    A[Company signs up at app.conxa.in] --> B[Clerk sign-up flow]
    B --> C{First-time login?}
    C -->|Yes| D[Download Build Studio installer]
    C -->|No| E[Dashboard]
    D --> F[Run conxa-build-studio-setup.exe]
    F --> G[Build Studio launches]
    G --> H[First-run bootstrap starts]
    H --> I[Fetch deps-manifest from Cloud]
    I --> J[Download NSIS]
    I --> K[Download runtime-win.exe]
    I --> L[Install Playwright Chromium]
    J & K & L --> M[Bootstrap complete]
    M --> N[Build Studio login prompt]
    N --> O[User clicks Sign In]
    O --> P[Browser opens to Clerk]
    P --> Q[User authenticates]
    Q --> R[Token stored in OS keyring]
    R --> S[Build Studio shows Dashboard]
```

**Notes:**
- Bootstrap (`services/bootstrap.py`) is idempotent. Re-running skips already-present dependencies.
- All downloads are SHA-256 verified against values from the cloud manifest.
- If on a corporate network, the bootstrap surfaces the exact URLs for IT whitelisting.

---

## 2. Build Studio Login

```mermaid
sequenceDiagram
    participant User
    participant Renderer as Build Studio Renderer
    participant Backend as Python Backend
    participant Clerk as clerk.conxa.in

    User->>Renderer: Click "Sign In"
    Renderer->>Backend: {type: "login"}
    Backend->>Backend: generate PKCE verifier+challenge
    Backend->>Backend: start HTTP server on port 52741
    Backend->>User: open system browser to Clerk authorize URL
    User->>Clerk: authenticate (email+password or OAuth)
    Clerk->>Backend: GET /cb?code=...&state=...
    Backend->>Clerk: POST /oauth/token (code + verifier)
    Clerk-->>Backend: access_token + refresh_token
    Backend->>Clerk: GET /oauth/userinfo
    Clerk-->>Backend: {sub, email, name, org_id}
    Backend->>Backend: store in OS keyring
    Backend-->>Renderer: {type: "result", result: {user_id, org_id, name, email}}
    Renderer->>Renderer: set auth state → show Dashboard
```

**Refresh:** `auth_service.get_token()` checks expiry on every outbound API call. If within 60s of expiry, uses `refresh_token` to get a new `access_token` transparently.

---

## 3. Create a Plugin

```mermaid
flowchart LR
    A[User on Dashboard] --> B[Click 'New Plugin']
    B --> C[Enter plugin name + target URL]
    C --> D[Backend: cmd_create_plugin]
    D --> E[Create Plugin record in plugin_store]
    E --> F[Plugin ID assigned]
    F --> G[Plugin appears in list with status: needs_auth]
```

**Data created:** `Plugin` model with `status="needs_auth"`, `auth=null`, `workflows=[]`.  
**Storage:** `data/plugins/{id}/plugin.json`

---

## 4. Record Authentication Session

```mermaid
flowchart TD
    A[Plugin with status=needs_auth] --> B[User clicks 'Record Auth']
    B --> C[Backend: cmd_start_recording with auth_mode=true]
    C --> D[Playwright launches Chromium]
    D --> E[Opens plugin.target_url]
    E --> F[User logs into the target website]
    F --> G[User clicks 'Stop Recording' in Build Studio]
    G --> H[Backend: cmd_stop_recording with auth_mode=true]
    H --> I[Playwright saves storageState to auth/auth.json]
    I --> J[Detect final URL as protected_url]
    J --> K[Plugin status updated to 'ready']
    K --> L[Plugin shows auth captured]
```

**Key invariant:** `auth.json` lives at `data/plugins/{id}/auth/auth.json`. It is NEVER copied into the skill pack build output.

---

## 5. Record a Workflow

```mermaid
flowchart TD
    A[Plugin with status=ready] --> B[User clicks 'New Workflow']
    B --> C[Enter workflow name]
    C --> D[Backend: cmd_start_recording with plugin_id + workflow_name]
    D --> E[Load auth session from auth/auth.json]
    E --> F[Playwright launches with storageState]
    F --> G[Navigate to plugin.protected_url]
    G --> H[bridge.js injected into all frames]
    H --> I[User performs workflow steps in browser]
    I --> J[Events captured: click, fill, select, navigate, etc.]
    J --> K[User clicks 'Stop Recording']
    K --> L[Backend: cmd_stop_recording]
    L --> M[Events saved to sessions/session_id/events.jsonl]
    M --> N[PluginWorkflow created with status=recorded]
    N --> O[Workflow appears in plugin list]
```

**Event types captured by bridge.js:**
`click`, `dblclick`, `right_click`, `type`, `fill`, `focus`, `select`, `select_option`, `set_checkbox`, `set_radio`, `date_pick`, `drag_drop`, `keyboard_shortcut`, `upload`, `navigate`, `scroll`, `tab_open`, `tab_switch`, `popup`, `frame_enter`, `frame_exit`, `dialog_appeared`, `dialog_accept`, `dialog_dismiss`.

---

## 6. Pipeline & Compilation

```mermaid
flowchart TD
    A[User selects workflow, clicks Compile] --> B[Backend: cmd_compile]
    B --> C[Install LLM proxy router]
    C --> D[Load raw events from events.jsonl]
    D --> E[pipeline/normalize.py]
    E --> F[pipeline/dedupe.py]
    F --> G[pipeline/enrich.py]
    G --> H[Normalized event list]
    H --> I[compiler/build.py: compile_skill_package]
    
    I --> J[intent_llm: generate WorkflowIntentGraph]
    J --> K[For each step:]
    K --> L[llm_selector_generator_v2: ElementFingerprint + compiled_selectors]
    L --> M[semantic_llm: semantic_description]
    M --> N[validation_planner: Assertion list]
    N --> O[recovery_policy: RecoveryBlock]
    O --> P[confidence/layered: confidence score]
    P --> Q{More steps?}
    Q -->|Yes| K
    Q -->|No| R[Assemble SkillPackage]
    R --> S[Save to data/skills/skill_id/skill.json]
    S --> T[Update PluginWorkflow: status=compiled, skill_id set]
    T --> U[Compile complete — step count shown to user]
```

**LLM calls** route through `conxa_core.llm.get_router()`, which is replaced at compile time with `LLMProxyClient` forwarding to `POST /api/v1/llm/proxy/{text,vision}` with monthly quota enforcement.

**Real-time events** stream from backend to renderer during compilation:
- `pipeline_start`, `pipeline_done`
- `compile_step` with `step` and `status` fields
- `compiler_start`, `compiler_done`
- `api_call` — each LLM call
- `compile_error` — on failure

---

## 7. Workflow Editing (HumanEdit)

```mermaid
flowchart TD
    A[Compiled workflow in Build Studio] --> B[User opens HumanEdit screen]
    B --> C[Load workflow via cmd_get_workflow]
    C --> D[Render step list with thumbnails]
    D --> E{User action}
    E --> F[Edit step field] --> G[cmd_patch_step → update + revalidate]
    E --> H[Reorder steps] --> I[cmd_reorder_steps]
    E --> J[Insert step] --> K[cmd_insert_step]
    E --> L[Delete step] --> M[cmd_delete_step]
    E --> N[Update input variables] --> O[cmd_update_workflow_inputs]
    E --> P[Replace literal with variable] --> Q[cmd_replace_literals]
    E --> R[Apply recording screenshot to step] --> S[cmd_apply_recording_visual]
    E --> T[Update visual bounding box] --> U[cmd_update_visual_bbox → regenerate anchors]
    E --> V[Sign off workflow] --> W[cmd_sign_off_workflow → signed_off=true]
```

**Patch gate:** Each edit increments the skill version. `revalidate_step()` checks that selector and intent remain coherent after the patch.

---

## 8. Build Plugin

```mermaid
flowchart TD
    A[User clicks Build Plugin] --> B[Backend: cmd_build_plugin]
    B --> C[Read all compiled skills for plugin]
    C --> D[plugin_builder.build_plugin]
    D --> E[Create output/{company}-plugin/ folder]
    E --> F[Write plugin.json manifest]
    E --> G[Render CLAUDE.md from template]
    E --> H[Render index.md from template]
    E --> I[For each workflow:]
    I --> J[Write skills/{slug}/execution.json]
    I --> K[Write skills/{slug}/recovery.json]
    I --> L[Write skills/{slug}/inputs.json]
    J & K & L --> M[Copy to data/skill-packs/{company}/]
    M --> N[Write pack.json with version + skills list]
    N --> O[Plugin build record saved: PluginBuild]
    O --> P[Build complete — version shown]
```

**Security check:** Build output directory is scanned for `auth.json`. If found, the build is **refused** with `auth_file_in_build_input` error.

---

## 9. Build Installer & Publish

```mermaid
flowchart TD
    A[User clicks Build Installer] --> B[Backend: cmd_build_installer]
    B --> C[Validate skill pack dir exists]
    C --> D[Check no auth.json in build input]
    D --> E[_publish_skill_pack_for_installer]
    
    E --> F[Read all files from data/skill-packs/{company}/]
    F --> G[POST /api/v1/plugins/publish to Cloud]
    G --> H[Cloud: claim slug ownership]
    H --> I[Cloud: write skill pack files]
    I --> J[Cloud: generate tracking token]
    J --> K[Cloud: return {tracking_token, sync_url}]
    K --> L[Rewrite pack.json with tracking + sync_endpoint]
    
    L --> M[build_installer via NSIS]
    M --> N[.exe created at output/{company}-Plugin-Setup.exe]
    
    N --> O[_upload_installer_for_download]
    O --> P[POST /api/v1/plugins/{slug}/installer/upload]
    P --> Q[Cloud stores installer.exe + meta.json]
    Q --> R[Cloud returns download_url]
    
    R --> S[Show installer path + cloud download URL to user]
```

**Installer contents:**
- `skill-packs/{company}/` (pack.json with tracking config embedded)
- `runtime.exe` + `keytar.node`
- Chromium browser (fetched at install time, not bundled)
- `conxa.mcpb` Desktop Extension (handles MCP registration via Claude's official mechanism)

---

## 10. End-User Installation

```mermaid
flowchart TD
    A[Customer receives Company-Claude-Setup.exe] --> B[Run installer - no UAC]
    B --> C[NSIS installs runtime.exe to %LOCALAPPDATA%\Conxa\runtime\]
    C --> D[NSIS runs runtime.exe --install-playwright]
    D --> E[NSIS installs skill-packs to %LOCALAPPDATA%\Conxa\skill-packs\company\]
    E --> F[NSIS copies conxa.mcpb to %LOCALAPPDATA%\Conxa\]
    F --> G{Claude Desktop installed?}
    G -->|.mcpb association found| H[ExecShell opens conxa.mcpb in Claude]
    G -->|Not found| I[Show: install Claude then double-click conxa.mcpb]
    H --> J[Claude shows extension install dialog]
    J --> K[Customer clicks Install - one confirm]
    K --> L[Customer restarts Claude Desktop]
    L --> M[Claude Desktop starts runtime.exe via MCP stdio]
    M --> N[Runtime sets CONXA_DIR from manifest env var]
    N --> O[Runtime finds Chromium + skill packs via CONXA_DIR]
    O --> P[list_skills tool available in Claude]
```

**Install scope:** Per-user (`RequestExecutionLevel user`), installs to `%LOCALAPPDATA%\Conxa`. No admin elevation required. Correctly resolves to the logged-in user's profile (avoids the elevated-admin-wrong-profile bug).

**MCP registration:** Via official `.mcpb` Desktop Extension mechanism. Claude Desktop owns `claude_desktop_config.json` — we never write to it. This is robust to MSIX filesystem virtualization (Claude Desktop MSIX reads config from `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\`, not `%APPDATA%\Claude\`).

**CONXA_DIR wiring:** The `manifest.json` inside `conxa.mcpb` sets `env.CONXA_DIR = ${HOME}\AppData\Local\Conxa`. `server.js` derives `PLAYWRIGHT_BROWSERS_PATH` and `SKILL_PACKS_DIR` from `CONXA_DIR`, so the `.mcpb`-launched runtime always finds the `.exe`-installed Chromium and skill packs.

**Uninstall asymmetry:** The `.exe` uninstaller removes `%LOCALAPPDATA%\Conxa` and the HKCU deep-link key. The Claude-managed extension (`mcpServers.conxa` in Claude's config) must be removed in-app: Claude Desktop → Settings → Extensions → Conxa → Remove.

---

## 11. Runtime Registration & First Sync

```mermaid
flowchart TD
    A[runtime-win.exe starts] --> B[Resolve CONXA_DIR + CONXA_DATA_DIR]
    B --> C[Load skill index from skill-packs/ cache]
    C --> D[Check runtime-update-pending.json]
    D -->|Pending update| E[Apply update via update.bat]
    D -->|No pending| F[Connect MCP to Claude Desktop]
    F --> G[Async: POST /telemetry/runtime-start fire-and-forget]
    F --> H[Async: check runtime-manifest — 24h cached]
    F --> I[Async: syncSkillPacks — 15s timeout]
    I --> J[For each company in skill-packs/:]
    J --> K[getToken from OS keychain]
    K -->|No token| L[Skip — log warning]
    K -->|Has token| M[GET /skill-packs/{co}/delta?since=version]
    M -->|Empty delta| N[Up to date]
    M -->|Files delta| O[Backup skills → atomic write + SHA-256 verify]
    O --> P[Update pack.json version]
    P --> Q[Reload skill index]
    Q --> R[Sync complete]
```

**First-time token:** The `auth.json` (Playwright storageState) is staged into `cache/sessions/` by the installer. On first sync, if no keytar token exists for the company, the runtime cannot sync. Token acquisition for the runtime is the **current gap** — the `getAuthChallengeUrl()` function generates a challenge URL but there is no in-app flow to complete this yet.

---

## 12. MCP Skill Execution

```mermaid
sequenceDiagram
    participant User
    participant Claude as Claude Desktop
    participant RT as Runtime (MCP)
    participant Browser as Playwright Browser
    participant Cloud as Conxa Cloud

    User->>Claude: "Submit my expense report for last week"
    Claude->>RT: list_skills
    RT-->>Claude: [{company: "acme", slug: "submit_expense", inputs: [...]}]
    Claude->>RT: get_skill_inputs(skill="submit_expense", company="acme")
    RT-->>Claude: {inputs: [{name: "period", type: "string", required: true}]}
    Claude->>User: "What period? (e.g. 'last week', '2025-05')"
    User->>Claude: "last week"
    Claude->>RT: execute_skill(skill="submit_expense", company="acme", inputs={period: "last week"})
    RT->>RT: load execution.json + recovery.json
    RT->>RT: load storageState from cache/sessions/
    RT->>Browser: launch Chromium (headed by default)
    loop For each step
        RT->>Browser: executeStep() with resolveElement()
        Browser-->>RT: success or failure
        RT->>RT: verifyAssertions()
        RT->>RT: writeCheckpoint()
        RT->>Cloud: POST /tracking/{co}/events (async)
    end
    Browser-->>RT: workflow complete
    RT->>Browser: close
    RT-->>Claude: {content: [{type: "text", text: "Done. Expense report submitted."}]}
    Claude-->>User: "Done. Expense report submitted."
```

---

## 13. Execution with Recovery

```mermaid
flowchart TD
    A[executeStep for step N] --> B[resolveElement]
    B --> C{Tier 1: compiled_selectors}
    C -->|Found| D[withLocator: perform action]
    C -->|Not found| E{Tier 2: a11y tree role+name}
    E -->|Found| D
    E -->|Not found| F{Retry budget remaining?}
    F -->|No| G[Tier 5: Escalation]
    F -->|Yes| H{Tier 3: LLM semantic recovery}
    H --> I[Current DOM → Claude: find element by description]
    I -->|Found| D
    I -->|Not found| J{Tier 4: Vision recovery}
    J --> K[Screenshot → Claude: locate element visually]
    K -->|Found| D
    K -->|Not found| G
    D --> L[verifyAssertions]
    L -->|All pass| M[writeCheckpoint]
    L -->|Required fails| N[Halt execution: report failure]
    L -->|Advisory fails| O[Log warning, continue]
    M --> P[tracker.emit step_ok + tier used]
    G --> Q[Report to Claude: action required]
    Q --> R[User intervenes or cancels]
```

---

## 14. Skill Pack Update (Company Side)

```mermaid
flowchart TD
    A[Company re-records or edits a workflow] --> B[Compile new version]
    B --> C[Build plugin with new version string]
    C --> D[Build installer — OR — publish only]
    D --> E[POST /api/v1/plugins/publish]
    E --> F[Cloud writes new files to skill-packs/{co}/]
    F --> G[Cloud updates pack.json skill_pack_version]
    G --> H[Customer runtimes detect version change on next sync]
    H --> I[Delta delivered, files updated atomically]
    I --> J[New skill version active on next execution]
```

**No re-installer needed** for content-only updates. The runtime's delta sync handles delivery automatically.

---

## 15. Skill Sync (Runtime Side)

```mermaid
flowchart TD
    A[Runtime cold start or refresh_skills tool call] --> B[Iterate skill-packs/ directories]
    B --> C[Read pack.json — get sync_endpoint + current version]
    C --> D[Get company token from keytar]
    D --> E[GET {sync_endpoint}?since={version}]
    E --> F{Delta response}
    F -->|files empty| G[Up to date — skip]
    F -->|files non-empty| H[Backup all affected skill dirs]
    H --> I[For each file in delta:]
    I --> J[Decode base64 content]
    J --> K[atomicWrite: write .tmp, SHA-256 verify, rename]
    K --> L{All files OK?}
    L -->|Yes| M[Update pack.json version + last_synced]
    L -->|No| N[Restore all backups from .bak dirs]
    M --> O[Delete .bak dirs]
    O --> P[Reload skill index]
```

---

## 16. Runtime Self-Update

```mermaid
flowchart TD
    A[Runtime cold start] --> B[Check runtime-update-pending.json]
    B -->|ready=true AND runtime.exe.next exists| C[Write update.bat to %TMP%]
    C --> D[Spawn cmd.exe /C update.bat - detached]
    D --> E[Continue serving normally]
    E --> F[bat: wait 3s → move exe.next to runtime.exe → delete bat]

    B -->|No pending| G[Check runtime-update-cache.json - 24h TTL]
    G -->|Cache valid| H[Use cached manifest]
    G -->|Cache expired| I[GET /api/v1/updates/runtime-manifest]
    I --> J[Save to cache + compare version]
    J -->|Current version OK| K[No update needed]
    J -->|Newer available| L[Download runtime-win.exe in background]
    L --> M[SHA-256 verify]
    M --> N[Write runtime.exe.next]
    N --> O[Write runtime-update-pending.json: ready=true]
    O --> P[Update applied on NEXT cold start]
```

---

## 17. Failure Recovery (End User)

```mermaid
flowchart TD
    A[Skill execution fails at step N] --> B{Recovery tiers exhausted?}
    B -->|No| C[Recovery attempted - see §13]
    B -->|Yes| D[Runtime sends wf_fail telemetry event]
    D --> E[Cloud records failure: fsi=step N, fc=error code]
    E --> F[Runtime returns failure result to Claude]
    F --> G[Claude reports to user: what failed + why]
    G --> H{User action}
    H --> I[Fix manually then say continue] --> J[execute_skill with resume_from=N]
    H --> K[Cancel] --> L[Execution state cleared]
    H --> M[Ask Claude for help] --> N[Claude diagnoses + suggests action]
```

**Execution state:** `data/executions/{id}/checkpoint.json` records the last successfully completed step. On resume, execution starts from `resume_from` step index with the same browser session if still open.

---

## Flow Summary

| Flow | Trigger | Systems Involved | Duration |
|---|---|---|---|
| Onboarding | First Build Studio launch | Build Studio, Cloud | ~5 min |
| Login | User clicks Sign In | Build Studio, Clerk | <30s |
| Record auth | Plugin setup | Build Studio, Target website | 2–5 min |
| Record workflow | Plugin setup | Build Studio, Target website | 5–30 min |
| Compile | After recording | Build Studio, Cloud LLM proxy | 1–10 min |
| Build installer | After compile | Build Studio, Cloud | 1–5 min |
| Customer install | .exe runs | Runtime, Claude Desktop | 2–5 min |
| Skill execution | Claude tool call | Runtime, Target website | 10s–5 min |
| Recovery | Step failure | Runtime, Cloud (LLM at T3+) | +2–30s |
| Skill update | Company publishes | Cloud, Runtime (next start) | <15s sync |
| Runtime update | Cold start check | Runtime, Cloud | Background |
