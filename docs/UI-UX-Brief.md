# UI/UX Brief

**Status:** Current as of 2026-06-01  
**Scope:** Build Studio (Electron) + Cloud Dashboard (Next.js)

---

## Table of Contents

1. [UI Systems Overview](#1-ui-systems-overview)
2. [Build Studio Screens](#2-build-studio-screens)
3. [Cloud Dashboard Screens](#3-cloud-dashboard-screens)
4. [Navigation Structure](#4-navigation-structure)
5. [User Journeys](#5-user-journeys)
6. [UX Bottlenecks & Friction Points](#6-ux-bottlenecks--friction-points)
7. [Missing Experiences](#7-missing-experiences)
8. [Enterprise UX Considerations](#8-enterprise-ux-considerations)
9. [Recommended Improvements](#9-recommended-improvements)

---

## 1. UI Systems Overview

Conxa has two distinct UIs:

| UI | Technology | Audience | Deployment |
|---|---|---|---|
| **Build Studio** | Electron + React (Vite) + TypeScript | Company engineers who build and publish skills | Windows desktop app |
| **Cloud Dashboard** | Next.js 16 + Tailwind 4 + shadcn/ui | Companies monitoring execution + managing billing | web (app.conxa.in on Vercel) |

Both use:
- Tailwind CSS for styling
- shadcn/ui components (Radix UI primitives)
- Clerk for auth (different SDK: Electron uses custom PKCE; web uses `@clerk/nextjs`)
- TanStack Query (cloud dashboard) or direct IPC calls (Build Studio)

The `research/frontend/` directory contains a prototype/research copy of both the cloud dashboard and a previous version of the Build Studio UI. This prototype is **not deployed**. The production source of truth is:
- Build Studio: `conxa-builder/electron/renderer/src/`
- Cloud Dashboard: `conxa-cloud/frontend/`

---

## 2. Build Studio Screens

### 2.1 Setup Wizard (`SetupWizard.tsx`)

**Purpose:** First-run onboarding when dependencies are not yet installed.  
**Inputs:** None (reads bootstrap state from backend).  
**Outputs:** Progress events from `cmd_bootstrap`.  
**User goal:** Get dependencies installed without manual intervention.

**UX issues:**
- No estimate of download time per dependency.
- Failures show a URL to whitelist but no retry button — user must re-launch.
- No "already installed, skip" fast path feedback.
- Progress is event-driven but the UI doesn't persist across restarts (progress resets if app is closed mid-bootstrap).

---

### 2.2 Login Overlay (`LoginOverlay.tsx`)

**Purpose:** Prompt sign-in before showing the main app.  
**Inputs:** User clicks "Sign In" button.  
**Outputs:** Auth state set in `AuthContext`.  
**User goal:** Authenticate once and be remembered.

**UX issues:**
- No visual feedback that the browser has opened and is waiting.
- No timeout indicator (5-minute wait; user may not know the window expired).
- Error messages from Clerk (e.g. `clerk_token_error`) are displayed raw without user-friendly translation.

---

### 2.3 Dashboard Page (`DashboardPage.tsx`)

**Purpose:** Overview of all plugins and recent activity.  
**Inputs:** None.  
**Outputs:** Plugin list with status, run count, last activity.  
**User goal:** See the health of all plugins at a glance.

**UX issues:**
- Metrics come from `cmd_get_metrics` — only counts skills and packs, no per-plugin run stats.
- No execution history visible in the studio (runs are in the Cloud Dashboard).
- No indication of which workflows are signed off vs. pending review.

---

### 2.4 Plugins Page (`PluginsPage.tsx`)

**Purpose:** List all plugins with their status.  
**Inputs:** None.  
**Outputs:** Plugin cards showing name, status (`needs_auth`, `ready`, `building`), workflow count.  
**User goal:** Navigate to a specific plugin to record, compile, or build.

**UX issues:**
- `needs_auth` status is cryptic — should say "Needs login recorded."
- No visual distinction between a plugin with zero workflows vs. one with 10.
- Delete plugin is irreversible with no undo.

---

### 2.5 Plugin Detail Page (`PluginDetailPage.tsx`)

**Purpose:** View and manage workflows for a single plugin.  
**Inputs:** Plugin ID from route params.  
**Outputs:** Workflow list with status, step count, last test result.  
**User goal:** See which workflows are ready to ship and which need work.

**UX issues:**
- Workflow status pipeline (`recorded → compiled → signed off → built`) is not visually represented as a pipeline.
- No bulk action (e.g. compile all workflows at once).
- `last_test_status: "never"` shows as blank — should say "Not tested."
- `signed_off: false` has no visual indicator.

---

### 2.6 Recording Feed (`RecordingFeed.tsx`)

**Purpose:** Live view of captured events during recording.  
**Inputs:** Active recording session.  
**Outputs:** Real-time event stream display.  
**User goal:** Confirm the recorder is capturing events correctly.

**UX issues:**
- Events are shown as raw JSON — not user-friendly (e.g. `{"action":"click","target":{"role":"button","inner_text":"Submit"}}`).
- No screenshot preview during recording (screenshots are captured but not shown live).
- No "pause recording" capability — only start/stop.
- No indication of iframe depth (user can't tell if the recorder is inside a frame).

---

### 2.7 Human Edit Page (`HumanEditPage.tsx`)

**Purpose:** Review and edit compiled workflow steps before signing off.  
**Inputs:** Compiled skill ID.  
**Outputs:** Patched skill document.  
**User goal:** Verify each step is correct and parameterize inputs.

**Components:**
- `WorkflowViewer.tsx` — step list with action/intent display
- `StepEditorPanel.tsx` — edit intent, selectors, assertions for a step
- `ParameterizationDrawer.tsx` — convert literal values to `{{variables}}`
- `RecordingScreenshotsPanel.tsx` — match steps to recording screenshots
- `ValidationEditor.tsx` — edit assertions
- `SuggestionsPanel.tsx` — AI-suggested improvements
- `ValidationReportPanel.tsx` — compile report summary
- `CompiledSkillsTab.tsx` — view raw compiled output

**UX issues:**
- Step editor opens in a panel but there's no visual "save" feedback — saves are implicit.
- The screenshot panel requires manual matching of recording screenshots to steps — should be auto-matched.
- Parameterization drawer is not discoverable (no affordance from the step view).
- No diff view when editing (can't see what changed from compiled original).
- Validation report is a tab, not inline — users miss compiler warnings.
- Drag-and-drop reordering (`dragConstants.ts`) exists but its discoverability is unclear.

---

### 2.8 Compile Page (`CompilePage.tsx` + `CompileProgress.tsx`)

**Purpose:** Trigger compilation and show real-time progress.  
**Inputs:** Session ID, plugin ID, workflow name.  
**Outputs:** Compiled skill ID + step count.  
**User goal:** Compile the recording into a skill and see it succeed.

**UX issues:**
- Progress steps (normalize → dedupe → enrich → selectors → assertions → recovery → package) are shown but LLM sub-steps are hidden.
- No estimate of time remaining.
- On failure, the error message is shown but there's no "retry" affordance.
- If quota is exceeded, the error `cloud_unreachable` is shown — not `quota_exceeded` — which is confusing.
- No persistent compile history (re-opening the page doesn't show previous compiles).

---

### 2.9 Build Page (`BuildPage.tsx`)

**Purpose:** Build the data-only plugin folder from compiled workflows.  
**Inputs:** Plugin ID, version string.  
**Outputs:** Build success confirmation, output path.  
**User goal:** Package all workflows into a distributable format.

**UX issues:**
- Version input is free text — no semver validation or auto-increment.
- No preview of which workflows will be included in the build.
- Unsigned-off workflows are included by default — should warn or block.

---

### 2.10 Build Installer Page (`BuildInstallerPage.tsx`)

**Purpose:** Build the NSIS installer and publish to Cloud.  
**Inputs:** Plugin ID, company slug.  
**Outputs:** Installer path, cloud download URL, tracking URL.  
**User goal:** Generate a distributable .exe for customers.

**UX issues:**
- The cloud publish step and installer build step are not visually separated — users don't understand the two-step process.
- No copy-to-clipboard for the download URL.
- `cloud_upload_error: installer_upload_too_large` shows a technical error code — should say "Installer too large for cloud hosting (max 250MB)."
- No installer history — can't see previous installer versions.

---

### 2.11 Test Plugin Page (`TestPluginPage.tsx`)

**Purpose:** Run a compiled workflow against the local runtime for validation.  
**Inputs:** Plugin ID, workflow ID, test inputs.  
**Outputs:** Pass/fail result, runtime output text.  
**User goal:** Confirm the workflow works end-to-end before shipping to customers.

**UX issues:**
- Runtime must be installed locally for testing — there's no inline message when it's not found (just `runtime_not_found` error code).
- No visual step-by-step progress during test execution.
- Inputs are a raw JSON object — no form-based input for human-readable fields.
- Test results don't persist across page navigation.

---

### 2.12 Skill Packages Page (`SkillPackagesPage.tsx`)

**Purpose:** Browse all built skill packages.  
**Inputs:** None.  
**Outputs:** Package list with skill count, bundle root path.  
**User goal:** Manage built packages.

**UX issues:**
- "Bundle root" is a filesystem path — only meaningful to the engineer.
- No connection between this page and the Plugin Detail page (disjointed mental model).
- Rename/delete with no undo.

---

### 2.13 Settings Page (`SettingsPage.tsx`)

**Purpose:** Configure Build Studio (cloud API URL, auth, proxy settings).  
**Inputs:** Form fields.  
**Outputs:** Updated environment config.  
**User goal:** Point Studio at a different cloud API (dev/staging).

**UX issues:**
- Settings are not persisted across restarts without env var changes.
- No schema validation for API URL.

---

## 3. Cloud Dashboard Screens

Source: `conxa-cloud/frontend/` (and `research/frontend/` for prototype reference)

### 3.1 Marketing/Landing Page

**Path:** `app/(marketing)/page.tsx`  
**Purpose:** Public landing page for Conxa.  
**Components:** Hero, Pipeline, RecoveryLayers, TrustedWorkflows, ObservableRuntime, AnalyticsDashboard, GovSaas, Reliability, Cta.

**Status:** Implemented with 3D Spline scene, Framer Motion animations, marketing sections.

---

### 3.2 Dashboard (`app/(protected)/dashboard/page.tsx`)

**Purpose:** Company-level overview after login.  
**Inputs:** Clerk auth context.  
**Outputs:** Plugin list, run counts, recent activity.  
**User goal:** See platform health and recent activity.

**UX issues:**
- No real-time updates — requires page refresh to see new runs.
- No summary metrics (total executions, success rate, recovery rate) at the top.
- No alerts for plugins with high failure rates.

---

### 3.3 Plugins Page (`app/(protected)/plugins/page.tsx`)

**Purpose:** List all published plugins.  
**Inputs:** Clerk auth.  
**Outputs:** Plugin cards with status and run count.  
**User goal:** Navigate to plugin detail.

---

### 3.4 Plugin Detail Page (`app/(protected)/plugins/[id]/page.tsx`)

**Purpose:** Execution history and workflow breakdown for one plugin.  
**Inputs:** Plugin ID.  
**Outputs:** Run timeline, per-skill stats.  
**User goal:** Diagnose execution problems.

**UX issues:**
- No filter by status (ok/fail).
- No drill-down from run summary to individual step events.
- No time range filter.

---

### 3.5 Compile Page (Cloud) (`app/(protected)/plugins/[id]/workflows/[workflowId]/compile/page.tsx`)

**Purpose:** Trigger re-compilation of a published workflow.  
**Status:** Listed in routes but functionality depends on cloud compilation — which is **not implemented** (cloud has no compiler). This is a future feature or a placeholder.

---

### 3.6 Billing Page (`app/(protected)/billing/page.tsx`)

**Purpose:** Subscription management via Razorpay.  
**Inputs:** Plan selection.  
**Outputs:** Subscription status, plan tier.  
**User goal:** Upgrade or manage subscription.

**UX issues:**
- Razorpay integration specifics not visible in the frontend code reviewed.
- No invoice history.

---

### 3.7 Team Page (`app/(protected)/team/page.tsx`)

**Purpose:** Manage workspace members.  
**Status:** UI exists but backend RBAC is not fully implemented (scaffolded in `app/services/rbac.py` but not wired to routes).

---

### 3.8 Settings Page (`app/(protected)/settings/page.tsx`)

**Purpose:** Workspace and account settings.  
**Status:** UI exists; specific settings not documented in code review.

---

### 3.9 Sign-In / Sign-Up

**Paths:** `app/sign-in/[[...sign-in]]/page.tsx`, `app/sign-up/[[...sign-up]]/page.tsx`  
**Purpose:** Clerk-hosted auth UI embedded in Next.js.  
**Status:** Standard Clerk Next.js integration.

---

## 4. Navigation Structure

### Build Studio

```
AppChrome (layout)
├── Sidebar
│   ├── Dashboard
│   ├── Plugins
│   │   └── [Plugin ID]
│   │       ├── Record Auth
│   │       ├── Workflows
│   │       │   └── [Workflow]
│   │       │       ├── Recording Feed (during recording)
│   │       │       ├── Compile
│   │       │       ├── HumanEdit
│   │       │       └── Test
│   │       ├── Build
│   │       └── Build Installer
│   ├── Skill Packages
│   └── Settings
└── WindowTitleBar (custom Electron title bar)
```

### Cloud Dashboard

```
(marketing)/
├── / (landing page)

(protected)/  [requires Clerk auth]
├── /dashboard
├── /plugins
│   └── /plugins/[id]
│       └── /plugins/[id]/workflows/[workflowId]/compile
├── /billing
├── /team
└── /settings

/sign-in
/sign-up
/onboarding
```

---

## 5. User Journeys

### Journey 1: First-time company engineer (Build Studio)

1. Downloads Build Studio. Runs setup wizard.
2. Signs in with Clerk (browser pop-up).
3. Creates first plugin (name + URL).
4. Records auth session (1–3 min).
5. Records first workflow (5–15 min).
6. Compiles (2–5 min — waits on LLM).
7. Reviews in HumanEdit — signs off.
8. Builds installer.
9. Distributes to first test customer.

**Time to value:** ~30 minutes from download to working installer.

**Current friction points:**
- Bootstrap progress is opaque (unclear if 2 or 20 minutes).
- Compile step has no time estimate.
- HumanEdit is the longest/hardest step — no guided review.

### Journey 2: Returning company engineer (update a workflow)

1. Opens Build Studio.
2. Navigates to existing plugin.
3. Re-records a workflow (auth is still valid).
4. Compiles new version.
5. Signs off.
6. Builds new installer version.
7. Publishes. Customers auto-update on next runtime start.

**Time to value:** ~15 minutes for a content update.

**Current friction:** No way to compare old vs. new compiled steps. Must rebuild installer even for content-only updates.

### Journey 3: Customer runs a skill

1. Installs the .exe.
2. Restarts Claude Desktop.
3. Asks Claude to run the skill.
4. Watches browser execute (headed mode default).
5. Claude confirms completion.

**Time to value:** Immediate after install.

**Current friction:** If the runtime token is not set (first-time), the skill sync silently skips. User may not know their skills need a token.

---

## 6. UX Bottlenecks & Friction Points

| Area | Friction | Impact |
|---|---|---|
| Compile step | No time estimate; LLM progress hidden | Users cancel thinking it's stuck |
| HumanEdit | No guided review checklist | Steps signed off incorrectly |
| Parameterization | Not discoverable | Workflows hardcoded; break on different users |
| Runtime token | No in-app acquisition flow | Skills don't sync without manual token setup |
| Error codes | Raw codes shown to user | Confusing (e.g. `cloud_unreachable` for quota exceeded) |
| Recording | No live screenshot preview | Can't confirm recorder is capturing correctly |
| Build → installer | Two steps not explained | Users confused about why two actions needed |
| Test workflow | Requires local runtime installed | No feedback when runtime missing |
| Compile quota | Quota exceeded shows as unreachable | Misleading error |
| Workflow status | No pipeline visualization | Unclear where workflow is in the process |

---

## 7. Missing Experiences

### 7.1 Runtime Token Acquisition (Critical Gap)

There is no in-app flow for the end customer to acquire a runtime auth token. The `auth_manager.js:getAuthChallengeUrl()` function generates a challenge URL, but the runtime's `server.js` does not expose a tool to trigger this. This means skill sync silently fails for new installations.

**Needed:** An MCP tool or installer step that prompts the user to authenticate the runtime on first launch.

### 7.2 Execution Visibility in Build Studio

The Build Studio has no view of execution history from deployed customers. Engineers must open the Cloud Dashboard separately to see telemetry. There's no "how are my customers doing?" view within the tool where the engineer lives.

### 7.3 Drift Alerts

The `structural_fingerprint` in `SkillMeta` was designed for drift detection — comparing the first 3 steps' landmark selectors before execution to detect site redesigns. This comparison is not implemented in the runtime (`run.js`) yet. No alert surfaces to engineers when their skills are likely failing due to site changes.

### 7.4 Workflow Diff / Version History

No way to see what changed between two compiled versions of a workflow. Engineers cannot review the diff before shipping an update.

### 7.5 Onboarding Progress State

The Setup Wizard has no persistent state. If the app is closed mid-bootstrap, it restarts from scratch. Should save progress and resume.

### 7.6 Installer Version History

No record of which installer versions were produced and when. No changelog.

### 7.7 Multi-Plugin Build

Companies with 5+ plugins have no batch build/publish flow. Each plugin must be built and published individually.

### 7.8 Test Results Persistence

Test results (`last_test_status`, `last_test_error`) are saved to the plugin model but not surfaced prominently in the workflow list or dashboard.

### 7.9 Claude Dashboard Integration

No way to see runtime status from within Claude Desktop (other than calling `get_runtime_status`). A user-visible status summary would help diagnose issues.

---

## 8. Enterprise UX Considerations

### 8.1 Team Publishing (Missing)

Multi-engineer teams cannot currently:
- Share draft workflows before sign-off.
- Assign review tasks.
- See who compiled or built what.

### 8.2 Audit Trail (Missing)

No UI surface for audit events: who compiled, who published, when, with what version. Required for SOC 2 and enterprise procurement.

### 8.3 Offline Mode

The Build Studio can record and partially edit offline (events are local). Compilation requires the LLM proxy (cloud). There is no offline-first messaging to tell users what they can and cannot do offline.

### 8.4 Proxy / Corporate Network

Bootstrap surfaces download URLs for IT whitelisting, which is good. However, the Clerk auth flow opens a system browser and uses a fixed port range (52741–52750). Corporate proxy environments may block this. There's no proxy configuration UI.

### 8.5 Role-Based Access in Dashboard

The Cloud Dashboard has Team and Settings pages but RBAC is not enforced. All workspace members can see all data, trigger all actions. For enterprise customers, read-only analyst roles are needed.

---

## 9. Recommended Improvements

### Priority 1: Fix critical UX gaps (blockers for reliable use)

1. **Translate error codes to human messages.** Map all `_CommandError` codes to user-friendly strings in the renderer. `quota_exceeded` should say "Monthly LLM quota reached. Contact Conxa to increase your limit." `cloud_unreachable` should say "Cannot reach Conxa Cloud. Check your internet connection."

2. **Runtime token acquisition flow.** Add an MCP tool (`setup_company`) or installer step that guides the end user through authenticating the runtime for a company on first use. Without this, skill sync silently fails for new installations.

3. **Compile time estimate.** Before compilation starts, show an estimate based on event count: `~N steps → approximately M minutes`. Update the estimate as steps complete.

4. **Recording screenshots live preview.** During recording, show the most recently captured screenshot in a sidebar panel so engineers can confirm the recorder is working.

### Priority 2: Improve workflow quality (reduce errors in production)

5. **Guided HumanEdit checklist.** Add a checklist panel in HumanEdit: "Have you verified the selector for each step? Have you parameterized all user-specific values? Have you signed off?" Require checklist completion before sign-off.

6. **Parameterization auto-suggest.** During HumanEdit, analyze step values for user-specific patterns (email addresses, names, dates) and suggest parameterization. `{{email}}`, `{{date}}` pre-populated.

7. **Workflow pipeline visualization.** Replace the status text labels with a clear pipeline diagram: `Recorded → Compiled → Reviewed → Signed Off → Built → Deployed`.

8. **Test result persistence and surface.** Show `last_test_status` prominently per workflow. Add a "Test required before publish" gate.

### Priority 3: Operational improvements (efficiency for returning users)

9. **Bulk compile.** Allow selecting multiple recorded workflows and compiling them all in sequence with a progress bar for each.

10. **Installer version history.** Store installer builds with version, date, sha256 and show them in a list on the Build Installer page.

11. **Publish without installer rebuild.** For content-only updates (no new workflows), allow publishing the updated skill pack directly without building a new installer. The runtime's delta sync handles delivery.

12. **Execution dashboard widget in Build Studio.** Embed a mini execution dashboard in the Build Studio showing the last 10 runs across all deployed plugins, fetched from the Cloud API.
