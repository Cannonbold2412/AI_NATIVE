# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Working Principles

### 1. Think Before Coding
- State assumptions explicitly. If unsure, ask.
- If multiple interpretations exist, present them — don't silently pick one.
- If a simpler approach exists, call it out.

### 2. Simplicity First
Write the minimum code needed. No extra features, no speculative abstractions, no configurability for single-use code, no handling for impossible scenarios. If you wrote 200 lines and 50 would do, rewrite it.

### 3. Surgical Changes
Touch only what the task requires. Don't refactor unrelated code, don't fix unrelated issues (mention them instead), match existing style. Every changed line must trace to the task.

### 4. Goal-Driven Execution
Define success → implement → verify. For bugs: reproduce → fix → verify. For refactors: ensure no behavior change.

### Token & File Constraints
- DO NOT read files larger than 25KB completely into context.
- For large files/logs use `offset` and `limit`. Prefer `grep`/`tail` to locate the relevant chunk first.

---

## Repo Layout

```
app/              FastAPI backend (Python)
  api/            HTTP routes — all mounted under /api/v1 (see app/main.py)
  recorder/       Phase 1: Playwright capture + in-page bridge.js
  pipeline/       Phase 2: normalize / dedupe / enrich recorded events
  compiler/       Phase 3: events → SkillPackage (selectors, assertions, recovery)
  execution/      Lifecycle state machine, checkpoint, drift, trace
  llm/            LLM clients + multi-provider router (see ROUTER_SETUP.md)
  services/       plugin_builder.py (compile → data-only plugin folder), jobs, executor
  storage/        Plugin templates incl. runtime/ shipped to ~/.conxa/runtime/
  models/         Pydantic schemas: SkillPackage, RecordedEvent, etc.
  auth/           Plugin auth session manager
  main.py         FastAPI entrypoint — routers registered here

runtime/          Node.js MCP runtime (ships to ~/.conxa/runtime/)
  server.js       MCP server (Claude Code integration)
  run.js          Step executor + fingerprint-scored recovery
  skill_loader.js, browser.js, auth_manager.js, sync.js, tracker.js

frontend/         Next.js App Router UI (Clerk auth, TanStack Query)
  src/            Pages: Dashboard, Plugins, SkillPackBuilder, TestPlugin, etc.
  proxy.ts        Clerk middleware

scripts/          Operational scripts
  test_plugin.py        End-to-end plugin validator (5 phases — see PLUGIN_TEST_README.md)
  recompile_session.py  Recompile a recorded session, dump compile report
  plugin_test/          Phase implementations used by test_plugin.py

tests/            pytest suite (unit + integration + e2e)
data/             Runtime state: sessions/, plugins/, skills/, saas/, cache/
docs/architecture.md  Authoritative deep-dive on phases, iframe pipeline, recovery cascade
```

---

## Common Commands

### Backend (Python / FastAPI)
```bash
# Install deps + Playwright Chromium
./build.sh                                       # or: pip install -r requirements.txt && python -m playwright install chromium

# Run the API locally
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# All tests
pytest -q tests

# Single test file / single test
pytest -q tests/test_pipeline_gates.py
pytest -q tests/test_pipeline_gates.py::test_specific_case -x

# Recompile a recorded session (dumps compile report to stdout)
python scripts/recompile_session.py <session_id>

# Build a plugin from a session
python rebuild_plugin.py        # edits the session id inline; see app/services/plugin_builder.py

# End-to-end plugin validation (phases 1/3/4 are fast & deterministic)
python scripts/test_plugin.py <plugin-slug> --skip-phase2 --skip-phase5
```

### Frontend (Next.js)
```bash
cd frontend
npm install
npm run dev                # local dev (Next.js App Router)
npm run build              # production build (Vercel)
npm run lint               # eslint
```

### Runtime (Node.js MCP server)
```bash
cd runtime
npm install
npm start                  # node server.js — MCP stdio server
npm run build:win          # bundle for Windows via @yao-pkg/pkg
npm run build:mac
```

Configuration: copy `.env.example` → `.env`. Required for LLM features: provider keys (see `ROUTER_SETUP.md` for the multi-provider router config — Groq / Google AI Studio / NVIDIA NIM enabled by default).

---

## Architecture: The Big Picture

Conxa records real browser workflows, compiles them into structured skills, and replays them via an MCP runtime with self-healing recovery.

### Pipeline (offline, deterministic)
```
Browser → recorder/bridge.js → events.jsonl
  → pipeline/run.py (normalize/dedupe/enrich)
  → compiler/build.py (compile_skill_package)
      ├─ ElementFingerprint per step (durable element identity)
      ├─ Assertion[] per step (outcome verification)
      ├─ RecoveryBlock (anchors, fallback selectors)
      └─ SkillMeta.structural_fingerprint (drift baseline)
  → services/plugin_builder.py (data-only plugin folder under output/skill_package/)
```

### Runtime (production, on user machine)
- Plugin folder: `~/.conxa/plugins/{slug}/` (data only — no JS shipped)
- Shared runtime: `~/.conxa/runtime/` (Node.js MCP server, installed once)
- Auth state: `~/.conxa/plugins/{slug}/auth/auth.json` (Playwright storageState; never in git)
- Execution state: `~/.conxa/data/executions/{id}/` (state.json, checkpoint.json, trace.jsonl)
- Recovery log: `~/.conxa/recovery.log` (JSONL, rotated at 10MB)

### Self-Healing Recovery Cascade (run.js)
For every action, runtime tries tiers in order; LLM only fires on Tier 3+:
1. **compiled selectors** — generated at compile time from recorded DOM (fast, free)
2. **a11y tree** — role + name lookup (DOM-shift tolerant, free)
3. **LLM recovery** — Claude locates element semantically on current DOM
4. **vision** — Claude vision model locates by screenshot
5. **escalation** — human review queue (no silent guessing)

Iframe context flows through every stage — see `docs/architecture.md` § "Iframe Pipeline" for the full chain (`bridge.js` → `session.py` → `compiler/build.py` → `run.js`'s `rootCandidates`).

### API Surface
- Backend exposes everything under `/api/v1/*` (see `app/main.py` for router list).
- Frontend talks to it via the Next.js proxy route handler (`API_ORIGIN` env var in production).
- Execution lifecycle endpoints: `GET/POST /api/v1/executions/{id}{,/pause,/resume,/cancel,/trace}`.
- MCP tools (runtime/server.js): `execute_plan`, `get_execution_status`, `pause_execution`, `resume_execution`, `cancel_execution`, `list_skills`, `read_skill_files`, `install_plugin`, `search_registry`.

---

## Where to Look First

- **Adding/changing a recorder event type**: `app/recorder/bridge.js` (capture) → `app/pipeline/` (normalize) → `app/compiler/build.py` (compile) → `runtime/run.js` (execute).
- **Selector/recovery logic**: compile side in `app/compiler/llm_selector_generator_v2.py` + `selector_score.py`; runtime side in `runtime/run.js` (`resolveElement`, `withLocator`).
- **Execution lifecycle / pause-resume**: `app/execution/lifecycle.py`, `checkpoint.py`, `runtime/run.js` pause-signal polling.
- **Plugin packaging**: `app/services/plugin_builder.py` writes the data-only plugin folder. Auth files (`auth/auth.json`, credentials) are NEVER placed in build output.
- **LLM calls**: `app/llm/client.py` — transparently routes through `app/llm/router.py` multi-provider pool when configured.
- **Deep architecture reference**: `docs/architecture.md` (data contracts, iframe pipeline, observability, migration phases).

---

## Production Deployment

- Backend + worker on Render via `render.yaml` (services: `ai-native-api`, `ai-native-worker`). Build with `build.sh`, start with `start.sh`.
- Frontend on Vercel with project root `frontend`, build `npm run build`. The Next route handler `/api/v1/*` proxies to `API_ORIGIN`.
- Required env vars in prod: `SKILL_AUTH_REQUIRED=true`, Clerk issuer/JWKS, allowed CORS origins, DB, Redis, Blob, Razorpay, app URL, LLM provider keys.


---

## 1. Think Before Coding

**Don’t assume. Don’t hide confusion. Surface tradeoffs.**

Before implementing:

- Explicitly state assumptions. If unsure, ask.
- If multiple interpretations exist, present them — don’t silently choose one.
- If a simpler approach exists, call it out.
- If something is unclear, stop and ask.

---

## 2. Simplicity First

**Write the minimum code needed. Nothing speculative.**

- No extra features beyond the requirement  
- No abstractions for single-use code  
- No unnecessary configurability  
- No handling for impossible scenarios  

> If you wrote 200 lines but it could be 50 → rewrite it.

Ask yourself:  
**“Would a senior engineer say this is overcomplicated?”**

---

## 3. Surgical Changes

**Touch only what’s necessary.**

When editing:

- Don’t modify unrelated code
- Don’t refactor unless asked
- Match existing style
- Mention issues, don’t fix them unless required

If your changes create unused code:
- Remove only what *you* introduced

> Every changed line must trace directly to the task.

---

## 4. Goal-Driven Execution

**Define success → implement → verify**

Example:

```
1. Add feature → verify via test
2. Fix bug → reproduce → fix → verify
3. Refactor → ensure no behavior change
```

---

## Token & File Constraints
- DO NOT read files larger than 25KB completely into context.
- When inspecting large files, logs, or databases, ALWAYS use `offset` and `limit` parameters to look at relevant chunks.
- Prioritize using terminal utilities (like `grep`, `awk`, or `tail`) to locate lines before attempting to read a file chunk.

---


# Conxa: AI-Driven Workflow Automation Platform

## Overview

Conxa is a **marketplace for AI-native automation plugins**, built from real workflow recordings and executed by AI agents.

---

## What We’re Building

A system where:

1. Users record real workflows  
2. Convert them into structured skills  
3. Package them into reusable plugins  
4. Let AI dynamically execute them  

---

## Core Architecture

### 1. Workflow Recorder → Structured Editor

- Record real workflows  
- Convert each into **one skill (`SKILL.md`)**  
- Human refines into production-ready logic  

---

### 2. Multi-Skill Aggregation

Multiple recordings → multiple skills

**Example (Render plugin):**
- Login  
- Create service  
- Deploy from GitHub  
- Monitor deployment  

---

### 3. Plugin Packager

- Combine skills + execution engine  
- Output: **One plugin capable of multiple tasks**

---

### 4. Execution Flow

1. Agent reads `CLAUDE.md`  
2. Plans required skills  
3. Requests inputs  
4. Executes using automation engine  

---

### 5. Deterministic Execution with Self-Healing Fallbacks

Runtime tries selectors in order; only Claude LLM fires on Tier 3+ fallback:

- **Tier 1 (compiled)**: Use `step.compiled_selectors` generated at compile time from recorded DOM. Fast, reliable, no LLM cost.
- **Tier 2 (a11y)**: Query a11y tree by role + name. Works when DOM shifts slightly. No LLM.
- **Tier 3 (LLM recovery)**: Claude LLM locates element on current DOM given semantic description. Expensive, used only when Tiers 1-2 fail.
- **Tier 4 (vision)**: Claude vision model locates by screenshot. Last resort; used when text-based recovery fails.
- **Escalation**: All 4 tiers fail → human review queue. No silent fallback or guessing.

Each recording session produces a DOM snapshot (SHA256 hash). Selectors are cached by (dom_hash, bbox, model). When the page layout changes, the next tier activates automatically.

---

## Output: Plugin Marketplace

### For Companies

- Record workflows  
- Convert into skills  
- Package into plugins  
- Publish on GitHub  

### We Provide

- Plugin generation  
- Execution engine  
- Version control

### For Users

- Download plugins  
- AI reads capabilities  
- Plans workflows  
- Executes autonomously relaibely  

---

## Why This Is Different

- ❌ Not RPA → no rigid scripts  
- ❌ Not templates → real workflows  
- ❌ Not brittle → self-healing system  

- ✅ AI-native planning  
- ✅ Dynamic execution  
- ✅ Scalable architecture  

---

## Vision

> Turn every real workflow into an executable AI capability.

---
