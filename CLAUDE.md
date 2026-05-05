# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Conxa: AI-Driven Workflow Automation Platform

## What We're Building
A marketplace where AI agents dynamically orchestrate modular automation plugins built from real workflow recordings.

## Core Architecture

### 1. Workflow Recorder → Structured Editor
Each recording captures one real workflow → Human refines it → Creates **one skill (SKILL.md)**

### 2. Multi-Skill Aggregation
Repeat recording + editing for different workflows → Build **multiple skills**

Example for a "Render.com" plugin:
- Skill 1: Login to Render
- Skill 2: Create a new service
- Skill 3: Deploy from GitHub
- Skill 4: Monitor deployment status

### 3. Plugin Packager
Combine multiple skills + universal execution code → Package as **one plugin** that can execute any of the included skills based on user prompts.

### 4. Plugin Execution Flow
1. Agent reads plugin README.md → Understands all available skills
2. Agent receives user prompt → Plans which skills to combine and in what order
3. Agent asks user for required inputs
4. Agent executes planned workflow using universal Playwright/Puppeteer code

### 5. Self-Healing Execution
Multi-layer recovery system handles UI changes, missing elements, failures during execution
- **LLM Recovery**: If an action fails, LLM analyzes error + current screen → Suggests next steps (e.g., "The 'Submit' button is missing. Try clicking 'Save' instead.")
- **Vision Recovery**: If LLM fails to recover, vision-based system analyzes screenshots → Detects UI changes and identifies new element locations (e.g., "The 'Submit' button has moved. It's now located at the bottom right corner of the screen.")

## Output: Plugin Marketplace

Companies build automation plugins using Conxa:
- **Record** multiple workflows → Individual skills
- **Refine** each recording using structured editor → Production-ready skills
- **Package** all skills + universal execution code → One plugin
- **Publish** to GitHub with version control

We provide:
- ✅ Complete plugin files (skills + universal execution code)
- ✅ GitHub repository setup & management
- ✅ Version control & release management
- ✅ Plugin discovery mechanism (GitHub-based registry)

Other companies discover → Download plugins → Claude reads README.md → Plans skill combinations → Executes with self-healing Playwright/Puppeteer code

## Why It's Different
- **Not RPA**: AI plans dynamically, not hardcoded sequences
- **Not Templates**: Skills come from real recorded workflows
- **Not Brittle**: Self-healing with LLM + Vision recovery
- **Scalable**: One universal execution engine, infinite skill combinations

## Current Status
MVP complete:
- ✅ Workflow Recorder
- ✅ Structured Editor
- ✅ Self-Healing Execution Engine (LLM + Vision)
- ✅ Agent Orchestration Layer

## The Vision
Companies record workflows → Build multi-skill plugins → Publish to GitHub with version control → Users download → Claude reads README.md, plans skill combinations → Executes with self-healing Playwright/Puppeteer code






## Architecture Overview

AI_NATIVE is a skill recording and compilation platform with two main components:

1. **Backend (Python/FastAPI)**: Records screen interactions, processes events through a pipeline, uses LLMs for semantic enrichment and intent recovery, and compiles skill packages.
2. **Frontend (Next.js/React)**: Provides UI for recording, editing, publishing skills; uses Clerk for authentication.

### Backend Structure (`/app`)

- **`api/`**: FastAPI route handlers split by domain:
  - `routes.py` — recording, compilation, and skill APIs (legacy endpoints)
  - `skill_pack_routes.py` — skill package generation and management
  - `workflow_routes.py` — workflow recording and editing
  - `product_routes.py` — product endpoints (me, workspaces, dashboard, billing)
  - `job_routes.py` — async job tracking
  - `security.py` — Clerk authentication and CORS middleware

- **`recorder/`**: Screen capture and visual processing
  - Converts screen recordings to structured events via browser bridge
  - `visual.py` — vision-based processing

- **`pipeline/`**: Event processing and normalization
  - `normalize.py` — normalize raw events to standard format
  - `dedupe.py` — deduplication logic
  - `enrich.py` — semantic enrichment (text extraction, OCR)
  - `text.py` — text processing utilities
  - `signals.py` — event signal definitions
  - `selectors.py` — DOM selector utilities

- **`compiler/`**: Skill compilation and action semantics
  - Transforms events into structured actions with validation
  - `action_semantics.py` — action classification and destruction detection
  - `selector_score.py` — selector scoring for robustness
  - `intent_validation_rules.py` — semantic validation of intents
  - `validation_planner.py` — validation flow generation
  - `dependencies.py` — dependency resolution

- **`llm/`**: LLM integrations (Claude API calls)
  - `semantic_llm.py` — extracts semantic meaning from events
  - `vision_llm.py` — multimodal visual reasoning (timeout: `SKILL_LLM_VISION_TIMEOUT_MS`)
  - `recovery_llm.py` — assists in recovering from automation failures
  - `intent_llm.py` — intent/action classification

- **`policy/`**: Intent ontology and skill policies
  - `intent_ontology.py` — intent taxonomy and definitions
  - `bundle.py` — skill package bundling logic
  - `catalog.py` — skill catalog/registry
  - `timing.py` — wait/retry policies

- **`storage/`**: Data persistence
  - `session_events.py` — event history storage
  - `json_store.py` — JSON file-based storage

- **`confidence/`**: Confidence scoring
  - `layered.py` — multi-factor confidence scoring
  - `uncertainty.py` — uncertainty metrics

- **`models/`**: Data models (`events.py`) and shared types

### Frontend Structure (`/frontend`)

- **`app/`**: Next.js App Router (13+) with Clerk auth
  - `(protected)/` — authenticated routes (requires `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`)
  - `api/` — Next.js route handlers (proxy to backend via `API_ORIGIN`)
  - `sign-in/` and `sign-up/` — Clerk auth pages
  - `workflows/` — workflow editing interface
  - `package/` and `pakage/` — skill package management

- **`src/`**: Shared React code
  - **Pages**: Dashboard, Skills Library, Recording Editor, Package Builder, Jobs, Billing, Settings
  - **Components**: Reusable UI (buttons, cards, inputs via shadcn)
    - `StepEditorPanel.tsx` — edit recorded steps
    - `WorkflowViewer.tsx` — visualize workflow DAG
    - `ValidationReportPanel.tsx` — show validation results
  - **Hooks**: Custom React hooks for API calls (`useWorkflow`, etc.)
  - **Services**: Axios-based API wrappers
  - **lib/**: Utility functions

## Common Development Tasks

### Backend Setup

```bash
# Install dependencies (Python 3.13+)
pip install -r requirements.txt
playwright install chromium  # Browser automation

# Run locally (port 8000)
uvicorn app.main:app --reload

# Or via FastAPI CLI (installs with fastapi)
fastapi run app/main.py
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Dev server (port 3000 by default)
npm run dev

# Build for production
npm run build

# Check linting
npm run lint
```

### Testing

```bash
# Run all backend tests
pytest -q tests

# Run specific test file
pytest tests/test_skill_pack_builder.py

# Run single test
pytest tests/test_skill_pack_builder.py::test_specific_test_name

# With coverage
pytest --cov=app tests
```

## Key Configuration

Environment variables (set in `.env` or deployment):

**Backend** (prefix `SKILL_`):
- `SKILL_ENVIRONMENT` — "local" or "production"
- `SKILL_LLM_API_KEY`, `SKILL_LLM_API_KEYS` — Claude API credentials
- `SKILL_LLM_VISION_MODEL` — defaults to "google/gemma-4-31b-it" (vision requests)
- `SKILL_LLM_VISION_TIMEOUT_MS` — defaults to 120000ms (vision LLM timeout)
- `SKILL_LLM_TIMEOUT_MS` — defaults to 2000ms (text LLM timeout)
- `SKILL_DATABASE_URL` — SQLAlchemy connection string
- `SKILL_REDIS_URL` — Redis for job queue (optional, worker keeps-alive loop if unset)
- `SKILL_BLOB_READ_WRITE_TOKEN` — Blob storage token
- `SKILL_CLERK_ISSUER`, `SKILL_CLERK_JWKS_URL` — Clerk OIDC config
- `SKILL_CORS_ALLOWED_ORIGINS` — comma-separated origins (e.g., "http://localhost:5173")

**Frontend** (`.env.local`):
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` — Clerk public key (required for auth UI)
- `CLERK_SECRET_KEY` — Clerk secret key (server-side only)
- `API_ORIGIN` — Backend URL (e.g., "http://localhost:8000")

## API Routes

**Legacy** (remain available locally):
- `POST /recordings` — start recording
- `POST /recordings/{id}/compile` — compile steps to skill
- `POST /packages` — create skill package

**Production** (`/api/v1`):
- `POST /api/v1/recordings` — recording APIs
- `POST /api/v1/workflows` — workflow/session management
- `POST /api/v1/packages` — skill package CRUD
- `POST /api/v1/jobs/{job_id}/wait` — poll async job status
- `GET /api/v1/me` — current user (Clerk)
- `GET /api/v1/workspaces/current` — user's workspace
- `GET /api/v1/dashboard` — dashboard metrics
- `GET /api/v1/usage` — billing usage
- `POST /api/v1/packages/bundles/{bundle}/publish` — publish to registry
- `POST /api/v1/packages/bundles/{bundle}/release` — create release

## Critical Details

- **Windows Event Loop**: FastAPI backend auto-sets `asyncio.WindowsProactorEventLoopPolicy()` on Windows for Playwright subprocess support (see `app/__init__.py`).
- **Vision Timeouts**: Vision LLM calls (image + text) use longer timeout (`SKILL_LLM_VISION_TIMEOUT_MS`) due to large multimodal payloads; separate from text timeout.
- **Skill Package Root**: Directory name for generated bundles controlled by `SKILL_PACKAGE_BUNDLE_ROOT` (default: "skill_package").
- **Parallel Vision Fanout**: When multiple LLM keys are set, anchor vision fires requests in parallel (`SKILL_LLM_PARALLEL_FANOUT_ANCHOR_VISION`).
- **Frontend Proxy**: Next.js `/api/*` handlers proxy to backend via `API_ORIGIN`; set this in `.env.local` locally and environment variables in Vercel.
- **Clerk Routes**: Sign-in/sign-up protected by Clerk; redirects handled automatically if `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is set.

## Development Workflow

1. **Recording**: User captures screen interaction in browser
2. **Normalization**: Raw events (clicks, text input, navigation) are normalized via `pipeline/`
3. **Enrichment**: LLM extracts semantic meaning and DOM selectors via `llm/semantic_llm.py`
4. **Compilation**: Events transformed into Actions with validation rules via `compiler/`
5. **Skill Generation**: Validated steps packaged into executable skill via `policy/bundle.py`
6. **Publishing**: Skill published to registry (Stripe verification if needed)

## Testing Notes

- Use `pytest -q tests` for quick validation before commits
- Test files mirror component names (e.g., `test_skill_pack_builder.py` for skill pack logic)
- Integration tests hit real LLM endpoints; mock or skip if API keys unavailable
- Frontend tests via Jest/React Testing Library (if added to package.json)
