# Conxa Build Studio — Dependency Audit

> **Purpose:** Identify every hidden dependency, external assumption, and fragmentation point
> that prevents a fresh clone from producing a working development environment or a
> self-contained end-user installer.  
> **Scope:** `conxa-builder/` (Electron + Python), `runtime/`, `packages/conxa-core/`.  
> **Cloud (`conxa-cloud/`)** is excluded — it runs on Render/Vercel and has a separate dependency story.

---

## 1. Complete Dependency Audit

### 1.1 Python — Build Studio Backend

| Dependency | Version spec | Source | Where declared |
|---|---|---|---|
| pydantic | >=2.9.0 | PyPI | `packages/conxa-core/pyproject.toml` |
| pydantic-settings | >=2.6.0 | PyPI | `pyproject.toml` |
| SQLAlchemy | >=2.0.0 | PyPI | `pyproject.toml` |
| playwright | >=1.49.0 | PyPI | `conxa-builder/python/requirements.txt` |
| Pillow | >=10.4.0 | PyPI | `requirements.txt` |
| beautifulsoup4 | >=4.12.0 | PyPI | `requirements.txt` |
| lxml | >=5.0.0 | PyPI | `requirements.txt` |
| imageio-ffmpeg | >=0.5.1 | PyPI | `requirements.txt` |
| **keyring** | **undeclared** | **PyPI** | **missing from requirements.txt** |
| PyInstaller | build-time only | PyPI | CI (`build-studio.yml`); not in requirements.txt |
| conxa-core | local package | repo | installed separately (`pip install -e packages/conxa-core`) |

**`keyring` is missing.** `auth_service.py` imports it at runtime (`import keyring`) but it is
declared nowhere. A fresh `pip install -r requirements.txt` will not install it; the first login
attempt crashes.

### 1.2 Node.js — Electron app (conxa-builder/electron)

All declared in `conxa-builder/electron/package.json`. `npm install` covers them. No hidden npm
dependencies — `node_modules/` is committed (it should be `.gitignore`d, but that is a separate
cleanup concern).

### 1.3 Node.js — Runtime (runtime/)

All declared in `runtime/package.json`. One critical native module:

| Dependency | Type | Issue |
|---|---|---|
| `keytar@^7.9.0` | native (node-gyp) | Requires C++ build toolchain + NASM at `npm install` time |
| `playwright@^1.45.0` | pure JS (Chromium downloaded separately) | OK — Chromium is managed |
| `@modelcontextprotocol/sdk` | pure JS | OK |

**keytar** compiles a native `.node` binary at `npm install` time. On a fresh Windows machine this
requires: Visual Studio Build Tools (MSVC), NASM, and `node-gyp`. The `build:win` script in
`runtime/package.json` hard-codes machine-specific paths to compensate (see §3).

The CI workflow (`build-runtime.yml`) correctly installs NASM and VS Build Tools via Chocolatey,
but `npm run build:win` as written in the repo still references a developer-machine NASM path.

### 1.4 System-level tooling

| Tool | Where used | Currently obtained from | Action needed |
|---|---|---|---|
| Python 3.11+ | Backend runtime | Developer's machine / CI `setup-python` | Declare in README; CI covers CI |
| Node.js 20+ | Electron, runtime build | Developer's machine / CI `setup-node` | Declare in README; CI covers CI |
| NSIS (makensis) | Installer build | **Three competing sources (see §3)** | Consolidate to bootstrap download |
| NASM | keytar native compile | **Hardcoded machine path** `%USERPROFILE%\tools\nasm-3.01` | Remove hardcoded path; CI uses choco |
| Visual Studio Build Tools | keytar compile | Developer's machine / CI choco | Not documented for devs |
| UPX | PyInstaller compression | `.spec` uses `upx=True` | PyInstaller silently skips if absent; OK |
| signtool.exe | Installer code signing | Windows SDK / CI | Optional, skipped if absent |

### 1.5 Playwright Chromium

| Context | Location | How installed |
|---|---|---|
| Build Studio dev | `%LOCALAPPDATA%\ms-playwright\` (default) | `playwright install chromium` |
| Build Studio packaged | `~/.conxa/deps/chromium/` | `bootstrap.ensure_chromium()` via PyInstaller Playwright driver |
| Runtime (test-plugin) | `CONXA_DIR/chromium/` | `ensure_chromium_installed()` uses system `npx playwright install` |
| Runtime (end-user) | `~/.conxa/chromium/` (or install dir) | Installed by runtime's NSIS installer on first run |

The dev flow works because `playwright install chromium` has been run on the developer's machine.
A new developer who skips this step will get a runtime error on first recording attempt.

### 1.6 External Services (runtime dependencies, not build)

| Service | Used by | Configured via |
|---|---|---|
| Clerk | Auth in all three systems | Env vars: `CONXA_CLERK_DOMAIN`, `CONXA_CLERK_CLIENT_ID`, `CONXA_CLERK_CLIENT_SECRET` |
| Conxa Cloud API (`apis.conxa.in`) | LLM proxy, bootstrap manifest, telemetry | Hardcoded default in `main.js` |
| LLM providers (Groq, Google, NVIDIA, etc.) | Compile-time LLM calls | `.env` with provider API keys |
| GitHub Releases | runtime-win.exe + keytar.node CDN | See §3 — inconsistent repo references |

---

## 2. Fragmentation Points

These are places where the system currently works *only because* of state on the developer's machine
that is not reproduced by cloning the repo.

### FP-1 — No unified developer setup command
**Impact:** High. CLAUDE.md documents four manual steps across three directory trees. A new
developer must know the correct sequence: install conxa-core, install builder deps, `playwright install`,
install Electron deps, install runtime deps. There is no `make setup` or `scripts/setup.ps1` to do this.

### FP-2 — `keyring` missing from requirements.txt
**Impact:** High. First login silently crashes with `ModuleNotFoundError: No module named 'keyring'`.

### FP-3 — Bootstrap is never triggered from the UI
**Impact:** Critical for end-user experience. `cmd_bootstrap` exists in `backend.py` and
`services/bootstrap.py` is fully implemented (Chromium, NSIS, runtime download). However:
- Zero renderer files call `bootstrap` or `cmd_bootstrap`.
- No first-run detection triggers it.
- The end-user installer ships without Chromium or NSIS. On first launch, nothing fetches them.
The bootstrap system exists and is correct — but it is dead code because nothing calls it.

### FP-4 — Runtime manifest key mismatch (bootstrap silently skips runtime download)
**Impact:** High. `bootstrap.py:150` reads `spec.get("url")` and `spec.get("sha256")` for the
runtime entry. `updates_routes.py:69-70` returns `win_url` and `win_sha256`. The bootstrap call
always gets `url=None` and `sha=None`, skips the download without error, and `ensure_runtime`
returns a directory that doesn't contain `runtime-win.exe`. Silently broken.

### FP-5 — Three different GitHub repos referenced
**Impact:** High. Build-time and runtime paths reference different repos:
- `installer_builder.py`: `github.com/Cannonbold2412/AI_NATIVE` (actual dev repo)
- `updates_routes.py`: `github.com/conxa-ai/runtime` and `github.com/conxa-ai/conxa-build-studio` (do not exist)
- CI workflow `build-runtime.yml`: correctly uses `$GITHUB_REPOSITORY` at runtime
Any CDN download that goes through `updates_routes.py` will 404.

### FP-6 — NSIS resolved via three competing mechanisms
**Impact:** Medium. A developer with system NSIS installed bypasses the bootstrapped copy.
`_find_makensis()` in `installer_builder.py` checks:
1. `shutil.which(MAKENSIS_PATH)` — uses whatever is on PATH
2. `C:\Program Files (x86)\NSIS\makensis.exe`
3. `C:\Program Files\NSIS\makensis.exe`
…all before considering `MAKENSIS_PATH` env var from bootstrap. The hardcoded system paths
undermine the reproducibility that bootstrap provides.

### FP-7 — Hardcoded `CONXA_CLERK_CLIENT_SECRET` in `main.js`
**Impact:** Security + reproducibility. `main.js:82` sets `CONXA_CLERK_CLIENT_SECRET` to a literal
value as a fallback default. This is a secret committed to source code. Removing it requires the
secret to be supplied at build time (env var injected by CI) or stored in a separate config file.

### FP-8 — Hardcoded machine path in `runtime/package.json` build:win
**Impact:** Medium for developers, zero for CI. `build:win` injects
`C:\Program Files\Git\usr\bin` and `%USERPROFILE%\tools\nasm-3.01` into PATH. The second path
is specific to the developer's machine (NASM installed manually to `~/tools/`). CI installs NASM
via Chocolatey and it lands on the system PATH, so CI is fine. But another developer running
`npm run build:win` locally gets `nasm not found`.

### FP-9 — `ensure_chromium_installed` requires system Node.js for test-plugin flow
**Impact:** Medium. When a SaaS vendor clicks "Test Plugin" in Build Studio, `conxa_runtime.py`
calls `shutil.which("node")` and `shutil.which("npx")`. If the developer's machine doesn't have
system Node.js on PATH, this fails. In the packaged `.exe`, the Playwright driver includes its
own Node binary, but the test path uses system Node, not the bundled one.

### FP-10 — `data_dir` default points inside the repo
**Impact:** Low. `config.py:35` defaults `data_dir` to `packages/conxa-core/data/`, which means
session data, skill packs, and plugin JSON accumulate inside the repo tree. This is fine for dev
but clutters `git status` and can inadvertently commit user data.

---

## 3. Hidden Machine Assumptions

| Assumption | Where encoded | Evidence |
|---|---|---|
| Python 3.11+ is installed and on PATH | `main.js:54` uses `"python"` / `"python3"` | Runtime error if absent |
| Node.js 20+ is installed and on PATH | `conxa_runtime.py:131` `shutil.which("node")` | test-plugin fails |
| npx is on PATH | `conxa_runtime.py:132` | test-plugin fails |
| Playwright Chromium was already installed | `recorder/session.py` | First recording crashes |
| NSIS is installed at a system path OR on PATH | `installer_builder.py:34-47` | installer build fails if bootstrap never ran |
| NASM at `%USERPROFILE%\tools\nasm-3.01` | `runtime/package.json:build:win` | local `build:win` fails for anyone else |
| VS Build Tools installed (for keytar native compile) | implicit in `npm install` in runtime/ | runtime native build fails on fresh machine |
| Clerk domain/client_id/secret match a live Clerk instance | `main.js:77-82` | auth fails with wrong values |
| `conxa-ai/runtime` and `conxa-ai/conxa-build-studio` GitHub orgs exist | `updates_routes.py` | CDN downloads 404 |
| keyring Python package is installed | `auth_service.py:59` | login crashes |

---

## 4. Required Repository Changes

| # | Change | File | Risk |
|---|---|---|---|
| R1 | Add `keyring` to `requirements.txt` | `conxa-builder/python/requirements.txt` | Zero |
| R2 | Fix runtime manifest key: `win_url` → `url` in bootstrap.py | `conxa-builder/python/services/bootstrap.py` | Zero |
| R3 | Remove hardcoded `CONXA_CLERK_CLIENT_SECRET` default from main.js | `conxa-builder/electron/main.js` | Low |
| R4 | Reverse NSIS resolution priority in installer_builder.py | `conxa-builder/python/conxa_compile/installer_builder.py` | Low |
| R5 | Fix inconsistent GitHub repo references in updates_routes.py | `conxa-cloud/backend/app/api/updates_routes.py` | Low |
| R6 | Wire `cmd_bootstrap` from renderer (first-run detection) | `conxa-builder/electron/renderer/src/` | Medium |
| R7 | Use bundled Node binary for test-plugin flow (or document Node requirement) | `conxa-builder/python/conxa_compile/conxa_runtime.py` | Medium |
| R8 | Create root developer setup script | `scripts/setup.ps1`, `scripts/setup.sh` | Zero |

---

## 5. Required Build System Changes

| # | Change | File | Notes |
|---|---|---|---|
| B1 | Remove hardcoded NASM path from `build:win` | `runtime/package.json` | Leave PATH management to CI; dev README covers local install |
| B2 | Ensure `keytar.node` is pre-built and uploaded to GitHub Releases as a CI artifact | `.github/workflows/build-runtime.yml` | Already done; ensure checksum is posted to cloud manifest |
| B3 | Ensure cloud manifest (`updates_routes.py`) returns correct repo URL for runtime CDN | `conxa-cloud/backend/app/api/updates_routes.py` | Fix with R5 |
| B4 | Populate `CONXA_NSIS_SHA256` env var on Render so the manifest returns a verified hash | Render env config | Currently empty; bootstrap accepts it but skips hash check |

---

## 6. Required Installer Changes

| # | Change | Notes |
|---|---|---|
| I1 | Trigger `cmd_bootstrap` on first launch from the UI | Chromium, NSIS, runtime must download before they are needed |
| I2 | Add a "Setup" screen that shows bootstrap progress and blocks app use until complete | Already partial: `SetupWizard.tsx` exists but handles plugin creation, not dep installation |
| I3 | Store a `first_run_complete` flag in electron-store; skip bootstrap on subsequent launches | Idempotent: bootstrap functions already check file existence before downloading |

---

## 7. Final Self-Contained State

### Developer experience target

```
git clone <repo>
cd AI_NATIVE
./scripts/setup.sh          # (or setup.ps1 on Windows)
cd conxa-builder/electron
npm run dev                 # Electron app starts; Python backend spawns; Chromium available
```

`scripts/setup.sh` must:
1. `pip install -e packages/conxa-core`
2. `pip install -r conxa-builder/python/requirements.txt`
3. `python -m playwright install chromium` (idempotent)
4. `npm install` in `conxa-builder/electron/`
5. `npm install` in `runtime/`

No manual tooling, no hidden PATH requirements.

### End-user installer target

```
Download  Conxa-Build-Studio-Setup.exe
↓
Run installer  (one click, no options needed)
↓
App launches → Bootstrap screen runs automatically
  • Downloads Chromium  (~150 MB)
  • Downloads NSIS from SourceForge
  • Downloads runtime-win.exe + keytar.node from GitHub Releases
↓
Sign in via browser
↓
Full functionality available — no manual steps
```

All large downloads deferred to first run behind the bootstrap screen. `bootstrap.ensure_all()`
implements this correctly; it only needs to be **called** from the renderer on first launch.

### What ships in the installer (electron-builder output)
- Electron app + renderer bundle
- PyInstaller backend (includes Python runtime, conxa_compile, playwright Node driver)
- `build/icon.ico`, `build/installer.nsh`

### What is fetched on first run (bootstrap)
- Chromium browser (~150 MB) → `~/.conxa/deps/chromium/`
- NSIS from SourceForge → `~/.conxa/deps/nsis/`
- `runtime-win.exe` from GitHub Releases → `~/.conxa/deps/runtime/<version>/`
- `keytar.node` from GitHub Releases → `~/.conxa/deps/runtime/<version>/`

### What is never needed by the end user
- Python, Node.js, npm, npx, NASM, VS Build Tools, Git — all handled internally

---

## 8. Issue Severity Summary

| Issue | Severity | Status after fixes |
|---|---|---|
| `keyring` missing from requirements.txt | **Critical** (blocks login) | Fixed by R1 |
| Bootstrap never called from UI | **Critical** (NSIS/runtime never download) | Fixed by R6 + I1 |
| Runtime manifest key mismatch | **Critical** (runtime download silently skipped) | Fixed by R2 |
| Non-existent GitHub repos in updates_routes | **High** (CDN downloads 404) | Fixed by R5 |
| Hardcoded CLERK_CLIENT_SECRET | **High** (secret in source) | Fixed by R3 |
| No developer setup script | **High** (new dev experience broken) | Fixed by R8 |
| Hardcoded NASM path in build:win | **Medium** (local runtime build fails) | Fixed by B1 |
| NSIS resolution priority | **Medium** (bypasses managed copy) | Fixed by R4 |
| Node.js required for test-plugin | **Medium** (hidden system dep for vendors) | Addressed by R7 |
| data_dir inside repo | **Low** (dev clutter, no breakage) | Acceptable; document in README |
