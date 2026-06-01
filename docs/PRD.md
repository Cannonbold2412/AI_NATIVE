# Product Requirements Document (PRD)

**Status:** Current as of 2026-06-01  
**Product:** Conxa

---

## Table of Contents

1. [Vision](#1-vision)
2. [North Star](#2-north-star)
3. [Core Insight](#3-core-insight)
4. [Mission](#4-mission)
5. [Why Now](#5-why-now)
6. [Problem Statement](#6-problem-statement)
7. [Core Product Principles](#7-core-product-principles)
8. [Positioning](#8-positioning)
9. [Market Opportunity](#9-market-opportunity)
10. [Target Customers](#10-target-customers)
11. [User Personas](#11-user-personas)
12. [Core Value Propositions](#12-core-value-propositions)
13. [Product Architecture Overview](#13-product-architecture-overview)
14. [Major Use Cases](#14-major-use-cases)
15. [Competitive Advantages](#15-competitive-advantages)
16. [Success Metrics](#16-success-metrics)
17. [Long-Term Product Roadmap](#17-long-term-product-roadmap)

---

## 1. Vision

Make every software platform operable by AI.

*This vision holds regardless of which AI systems exist, which protocols emerge, or how distribution evolves. Software built for humans should also work for AI — reliably, privately, at scale.*

---

## 2. North Star

A future where humans no longer repeatedly operate software for routine tasks. Where AI systems can reliably execute software workflows on a human's behalf, and humans spend their time on work that requires judgment — not repetition.

---

## 3. Core Insight

### What traditional automation stores

Traditional automation — RPA scripts, Playwright tests, browser macros — records **actions**: CSS selectors, click coordinates, pixel positions. It captures *what was done*, not *why it was done* or *what success looks like*. When the UI changes — even slightly — the recorded actions no longer apply. The automation breaks silently. A human must fix it.

### What Conxa stores

Conxa compiles browser recordings into semantically rich skill packages that store:

- **Intent** — What was the user trying to accomplish, expressed in human terms.
- **Element identity** — A multi-signal fingerprint (role, accessible name, inner text, data attributes, anchor phrases, position hints) that survives visual redesigns and DOM reorganizations.
- **Recovery context** — Alternative strategies for locating the same element when primary selectors fail, generated at compile time by LLM reasoning over the recorded DOM.
- **Semantic meaning** — LLM-generated descriptions of each element and action in language a reasoning model can use during execution.
- **Validation logic** — Explicit assertions (URL patterns, element presence, value checks) that confirm each step succeeded before the next begins.
- **Structural fingerprint** — A baseline of page structure used to detect UI drift before execution starts, not after it fails.

### Why this enables self-healing

When a UI changes, compiled selectors may fail — but element identity rarely changes. A "Submit" button still has role `button`, accessible name "Submit", and similar surrounding context. The compiled skill contains enough semantic richness to find it through structured recovery paths: accessibility tree lookup, LLM semantic search, visual recognition.

This is not re-prompting an LLM on every step. It is structured, tiered, predictable recovery that degrades gracefully and escalates to humans only when genuinely necessary. The result: automation that maintains itself across UI changes instead of breaking.

---

## 4. Mission

Make browser workflow automation reliable enough to ship as a product — not just a demo.

By compiling recorded workflows into semantically rich skill packages with structured self-healing, Conxa closes the gap between "it works on my machine" and "it works reliably on every customer's machine."

---

## 5. Why Now

### The AI interface layer is crystallizing

For the first time, a dominant interface for AI-human interaction is establishing itself across enterprises: AI assistants (Claude Desktop, ChatGPT, Copilot) running locally on user machines, connected to external capabilities via open protocols. The Model Context Protocol (MCP) is emerging as the standard by which these assistants access tools and execute actions. This is the distribution channel Conxa is built for — and it did not exist three years ago.

### Reasoning models are now capable enough

Earlier generation models hallucinated CSS selectors, misidentified page structure, and failed at semantic element recovery at unacceptable rates. Current reasoning models can reliably locate the correct element on an unfamiliar page, interpret validation failures, and generate accurate fallback strategies. The 5-tier recovery cascade that Conxa's runtime depends on is only viable with 2024+ model capabilities.

### Enterprises are adopting AI workflows — and hitting a wall

Enterprise AI adoption has moved from experimentation to deployment. The barrier is no longer "will employees use AI?" but "can we trust AI to actually operate our software?" Organizations want AI to submit reports, extract data, trigger multi-step processes, and fill out forms — but no reliable, auditable, enterprise-safe product exists for this. Conxa is that product.

### Traditional automation cannot bridge the gap

The RPA market has existed for 15 years and never achieved the penetration analysts expected. The reason: automation requires continuous maintenance, expensive specialists, and still breaks when UIs change. AI browser agents are non-deterministic and cannot be packaged as enterprise products. There is a structural gap between what organizations need and what exists — one that is not filled by incremental improvements to Playwright or UiPath.

### The local execution moment

Enterprise security requirements have hardened. Sending credentials, browser sessions, and enterprise data to third-party cloud services is increasingly a non-starter. The shift to local AI execution — Claude Desktop running locally, MCP servers running on user machines — creates a new category of trusted automation: private by architecture, not by policy. Conxa is built for this constraint from the ground up.

### Why this didn't exist five years ago

Five years ago: LLMs were unreliable for semantic element recovery. MCP didn't exist. Claude Desktop didn't exist. Enterprise AI adoption was in early experimentation. The LLM inference costs required for compile-time semantic analysis were impractical. All five preconditions — capable models, open protocols, local AI clients, enterprise adoption, and cost viability — have converged in the last 18 months.

---

## 6. Problem Statement

### The automation reliability gap

Every SaaS company has workflows their customers must perform manually:
- Submit expense reports
- Generate compliance exports
- Update CRMs after meetings
- Pull performance reports

These workflows are repetitive, error-prone, and expensive. Companies know this. They try to solve it.

### Why existing solutions fail

**Scripted automation (Selenium, Playwright, RPA):**
- Breaks when the UI changes — and UIs change constantly.
- Requires engineering time to build and maintain each script.
- Fails silently in production; no visibility into what broke.
- Cannot adapt when elements shift, modals appear, or pages reorganize.

**AI browser agents:**
- Non-deterministic — same input produces different click paths.
- Expensive: LLM inference on every step of every execution.
- Opaque: no audit trail, no step-level observability.
- Unsafe for enterprise: credentials and session state processed by third-party servers.
- Cannot be packaged and distributed as a product.

**Traditional RPA (UiPath, Automation Anywhere):**
- Requires dedicated RPA infrastructure.
- Per-seat licensing makes customer-facing distribution impractical.
- Cannot be embedded in a vendor's product.
- No native AI integration (Claude, GPT, Copilot, etc.).

### What Conxa solves

Conxa produces **compiled, self-healing workflow skills** from real browser recordings. Skills are packaged into distributable `.exe` installers that run **entirely on the customer's machine** via Claude Desktop's MCP protocol. Execution is zero-cost to the vendor beyond the one-time compilation step.

---

## 7. Core Product Principles

These principles guide every product decision. When trade-offs arise, resolve them in this order.

### 1. Reliability over autonomy

A skill that fails predictably is better than a skill that sometimes succeeds through unpredictable AI decisions. Conxa is deterministic by design. LLM reasoning is a recovery mechanism of last resort, not the primary execution path.

### 2. Human teaches once, AI executes repeatedly

The compilation step is where human expertise is captured. A domain expert records a workflow correctly once. The compiled skill is then executable millions of times across thousands of machines — with no ongoing human involvement unless the UI fundamentally changes.

### 3. Local execution by default

Credentials, browser sessions, enterprise data, and execution state never leave the user's machine. Cloud infrastructure exists for coordination (skill distribution, telemetry aggregation, billing) — not for execution. This is a security guarantee enforced by architecture.

### 4. Self-healing before failure

When a step fails, the system exhausts every available recovery path before surfacing a failure to the user. Escalation is a last resort, not a first response. Users should never experience a failure that the system could have recovered from silently.

### 5. Enterprise visibility by design

Every execution — successful or failed — produces a structured telemetry record visible to the publishing Company on the Conxa dashboard. Observability is not bolted on after the fact; it is a first-class part of the runtime contract. Companies must know what is working across their customer base without relying on customer-reported failures.

### 6. AI-native interoperability

Skills are exposed as standard MCP tools. Today this means Claude Desktop. Tomorrow it means any AI system that speaks MCP: ChatGPT plugins, enterprise copilots, multi-agent orchestrators. Conxa does not build for one AI client — it builds for the protocol layer.

### 7. Deterministic execution whenever possible

Where a step can be executed deterministically (compiled selector succeeds), use it. Where it cannot, use the least expensive recovery tier first. Introduce non-determinism only when all deterministic paths are exhausted. This protects against cost creep, unpredictable behavior, and audit trail gaps.

---

## 8. Positioning

### What category is Conxa?

Conxa is not a browser automation tool. It is not an RPA platform. It is not an AI agent framework.

**Conxa is the operating layer between AI systems and existing software.**

Every piece of enterprise software has a web UI built for human operation. That UI was not designed for AI. There is no machine-readable API for "submit expense report" or "export compliance data" — only a browser interface optimized for human visual perception and motor interaction.

Conxa is the infrastructure that makes those interfaces operable by AI: reliably, privately, at enterprise scale, without modifying the underlying software.

### How to think about it

| Layer | Role |
|---|---|
| The software (SaaS, internal app) | Built for humans |
| **Conxa** | **Makes it operable by AI** |
| The AI system (Claude, GPT, Copilot) | Issues commands, receives results |
| The human | Defines workflows once; delegates execution |

Conxa occupies the layer that currently does not exist as a product: structured, reliable, distributable AI operability for software that was never designed to be operated programmatically.

### Why this is infrastructure, not a tool

Tools are purchased per workflow or per user. Infrastructure is purchased per platform capability. Conxa's model is closer to Stripe (payment infrastructure) or Twilio (communication infrastructure) than to UiPath (RPA tool) or Playwright (automation library). A SaaS company adopts Conxa once and uses it to distribute AI operability across their entire customer base — not to automate individual workflows in isolation.

The entry point is the first plugin. The moat is the growing library of compiled skills, the installed runtime base across customer machines, and the telemetry layer that surfaces execution health across the install base.

---

## 9. Market Opportunity

### Immediate market: B2B SaaS vendors with high-automation workflow customers

Every B2B SaaS company has customers who need to automate workflows. The vendor cannot build custom integrations for every customer. Conxa lets vendors ship an automation layer without ongoing engineering investment.

### Emerging market: AI-native automation distribution

As Claude Desktop, ChatGPT, and enterprise AI assistants become standard workplace tools, the MCP ecosystem creates a distribution channel for workflow capabilities. Conxa is positioned as the **compile + host + distribute** infrastructure for this ecosystem.

### Cost structure advantage

Per `docs/cost_model.md`: Conxa's primary cost is LLM inference at **compile time** (one-time per plugin build), not at execution time. Execution runs on the customer's machine at zero marginal cost to Conxa. Unit economics improve as customers run skills more frequently — the opposite of traditional SaaS, where usage drives cost.

### Infrastructure market dynamics

Infrastructure businesses exhibit strong retention, high switching costs, and compounding network effects. A SaaS vendor that publishes skills to Conxa has customer installers distributed, telemetry flowing, and skill packs synced. Switching means rebuilding that entire distribution stack. The more skills published and the larger the install base, the deeper the integration and the harder the switch.

---

## 10. Target Customers

### Primary: B2B SaaS companies (the "Company")

Companies that:
- Have existing SaaS products with web UIs.
- Have customers who perform repetitive workflows in those UIs.
- Want to offer automation as a product differentiator.
- Have an engineering team but cannot justify maintaining fragile automation scripts.

**Segment A: SMB SaaS (5–50 employees)**
- Need a fast path from "idea" to "working automation."
- Cannot afford to hire RPA specialists.
- Want to ship customer value without building infrastructure.

**Segment B: Mid-market SaaS (50–500 employees)**
- Multiple products / multiple workflow types.
- Need team-level access (workspace sharing, role-based publishing).
- May have compliance requirements (audit logs, execution visibility).

**Segment C: Enterprise SaaS (500+ employees)**
- Multi-tenant deployments.
- Strong security requirements (on-premise data, audit trails, SSO).
- Need SLA-backed reliability and compliance documentation.

### Secondary: End users (the "Customer")

The people who install the `.exe` and run skills via Claude Desktop. They are not Conxa customers directly — they are the customers of the Company. Conxa's product quality is judged entirely by how well their Claude experience works.

---

## 11. User Personas

### Persona 1: Priya — Product Engineer at a B2B SaaS company

**Role:** Engineer at a 30-person SaaS company. Responsible for integrations and customer success tooling.  
**Goal:** Give customers a "run this in your account" automation without building a full API integration.  
**Pain:** Spent a week on a Playwright script that broke on the third customer. No visibility into what failed.  
**Uses Conxa for:** Recording, compiling, and shipping automation skills. Relies on self-healing so she doesn't have to maintain scripts.

### Persona 2: Marcus — Technical Co-Founder

**Role:** CTO of a 10-person SaaS startup.  
**Goal:** Differentiate the product with AI-native automation before larger competitors do.  
**Pain:** Can't justify engineering time for automation infrastructure; needs it to just work.  
**Uses Conxa for:** Build Studio to record and ship; Conxa dashboard to monitor customer execution health.

### Persona 3: Sarah — Enterprise IT Automation Lead

**Role:** Automation specialist at a 1,000-person company deploying a SaaS vendor's Conxa plugin.  
**Goal:** Deploy the plugin to 200 employees reliably. Needs audit logs, must satisfy internal IT policy.  
**Pain:** Third-party automation tools process credentials on their servers — a security non-starter.  
**Values:** Local execution (no credential exfiltration), audit trail, offline execution capability.

### Persona 4: Dev — End User / Claude Desktop User

**Role:** Operations analyst using Claude Desktop daily.  
**Goal:** Run the "submit expense report" skill without thinking about it.  
**Pain:** The workflow breaks once a month and there's no clear guidance on what went wrong.  
**Values:** It just works. When it doesn't, Claude tells him clearly what happened and what to do next.

---

## 12. Core Value Propositions

### For the Company (Build Studio user)

1. **Record once, distribute to thousands.** One browser recording → compiled skill → .exe installer → any customer's Claude Desktop. No per-customer engineering.

2. **Self-healing without ongoing maintenance.** The 5-tier recovery cascade (compiled selectors → a11y tree → LLM semantic → vision → escalation) adapts when the UI shifts. Companies don't need to redeploy when their SaaS partner updates their interface.

3. **Execution visibility across the install base.** The Conxa dashboard shows every run, every recovery attempt, every failure across all customer machines — without Conxa being in the execution path at runtime.

4. **Instant versioning without re-distribution.** Publish a new skill pack version → customer runtimes pull the update on the next cold start. No re-installer distribution required.

5. **Zero marginal execution cost.** LLM inference only happens at compile time (one-time) and at Tier 3+ recovery (rare). The customer's Claude Desktop subscription covers runtime model use.

### For the Customer (end user)

1. **Works inside Claude.** Skills appear as natural tools in Claude Desktop — no new interface to learn, no separate app to open.

2. **Runs locally.** Browser automation executes on the user's own machine. Credentials never leave the device.

3. **Visible when needed.** By default, a visible browser opens so the user can watch and intervene. Background mode is opt-in.

4. **Recovers gracefully.** When a step fails, the runtime attempts recovery. When it cannot recover, Claude explains precisely what happened and what action is needed.

---

## 13. Product Architecture Overview

Three tiers, each owned by a different party:

```
Company (SaaS vendor)          Conxa                    Customer (end user)
──────────────────────         ──────────                ──────────────────────
Build Studio (Windows)    →    Cloud (Render/Vercel)  →  Runtime (Claude Desktop)
• Records workflows            • LLM proxy (metered)     • Executes skills
• Compiles locally             • Hosts skill packs       • Telemetry → Cloud
• Builds .exe installer        • Analytics dashboard     • Self-updates
• Publishes to Cloud           • Billing                 • Syncs skill updates
```

**Key architectural decision:** The compilation pipeline runs entirely in the Build Studio (locally on the Company's machine). The cloud does not record, compile, or execute browser workflows. This keeps sensitive browser sessions, DOM snapshots, and credentials on-premise and dramatically reduces cloud infrastructure cost and attack surface.

---

## 14. Major Use Cases

### UC1: Record a New Workflow

1. Company engineer opens Build Studio, selects a plugin.
2. Records browser authentication session (Playwright).
3. Records a workflow (e.g., "create expense report").
4. Build Studio captures events, screenshots, DOM snapshots.
5. Engineer stops recording. Events saved to `sessions/{id}/events.jsonl`.

### UC2: Compile and Edit

1. Engineer triggers compile on recorded session.
2. Pipeline normalizes, dedupes, enriches events.
3. Compiler generates selectors, assertions, recovery blocks via cloud LLM proxy.
4. Engineer reviews compiled steps in the HumanEdit screen.
5. Can patch steps, reorder, insert, delete, update visual bboxes.
6. Signs off workflow when satisfied.

### UC3: Build and Publish Installer

1. Engineer builds the plugin (data-only folder — auth files excluded).
2. Engineer triggers "Build Installer."
3. Build Studio:
   a. Publishes skill pack to Cloud (`POST /plugins/publish`).
   b. Receives tracking token + sync endpoint.
   c. Builds `.exe` with NSIS (embeds skill pack + tracking config).
   d. Uploads `.exe` to Cloud (available at `/installers/{slug}`).
4. Engineer distributes installer to customers via download page, email, or direct link.

### UC4: Customer Install and First Run

1. Customer downloads and runs `{Company}-Plugin-Setup.exe`.
2. Installer places skill pack at `~/.conxa/skill-packs/{company}/`.
3. Installer places `runtime-win.exe` at standard path.
4. Installer registers MCP server in Claude Desktop config.
5. Customer restarts Claude Desktop.
6. Runtime starts, syncs latest skill pack from Cloud.
7. `list_skills` tool appears in Claude.

### UC5: Skill Execution via MCP

1. User asks Claude: "Submit my expense report for last week."
2. Claude calls `get_skill_inputs` → learns required inputs.
3. Claude asks user for any missing inputs.
4. Claude calls `execute_skill` with inputs.
5. Runtime opens browser (headed or headless).
6. Executes each step with adaptive pacing + tiered recovery.
7. Reports result to Claude.
8. Claude tells user: "Done. Submitted."
9. Runtime sends telemetry batch to Cloud.

### UC6: Skill Recovery During Execution

1. Step 3 fails: compiled selector doesn't match (UI changed).
2. Tier 2: a11y tree lookup. Found → execute and continue.
3. Tier 3 (if T2 fails): LLM semantic recovery. Claude locates element by semantic description of the DOM.
4. On success: log recovery event. Continue.
5. Tier 4 (if T3 fails): vision. Screenshot → Claude locates by visual context.
6. Tier 5 (if T4 fails): escalation. Claude reports to user: "Could not find the Submit button. The page may have changed. Please click it manually."

### UC7: Skill Pack Update

1. Company engineer records + compiles a new version of a workflow.
2. Triggers "Publish" (installer rebuild not required for pack-only updates).
3. Cloud skill pack updated with new version.
4. Next time a customer's runtime cold-starts, sync detects version mismatch.
5. Delta downloaded; files atomically updated with SHA-256 verification.
6. New skill version active on next execution — no customer action required.

---

## 15. Competitive Advantages

### vs. Traditional RPA (UiPath, Automation Anywhere, Power Automate)

| Dimension | RPA | Conxa |
|---|---|---|
| Setup time | Days–weeks | Hours |
| Distribution model | Per-seat license on vendor infrastructure | Compile once → distribute .exe |
| Execution cost | Runs on vendor-managed robots | Runs on customer's machine (zero marginal cost) |
| AI recovery | None (script breaks on UI change) | 5-tier self-healing |
| AI assistant integration | None | Native MCP tools for Claude Desktop (and future clients) |
| Execution privacy | Cloud-executed (credentials leave user) | Local execution only |
| Compile cost | None (no compile step) | One-time LLM cost per workflow version |

### vs. AI Browser Agents (Operator, Browser Use, etc.)

| Dimension | AI Agent | Conxa |
|---|---|---|
| Reliability | Non-deterministic (LLM per step) | Deterministic (compiled; LLM only for recovery) |
| Per-execution cost | High (LLM on every step) | Near-zero (LLM only at Tier 3+ recovery) |
| Audit trail | Minimal | Step-level telemetry, execution log |
| Distributability | Not distributable as a product | Compile → .exe → distribute to any customer |
| Enterprise packaging | None | Signed installer, local execution |
| Recovery | Re-prompt (unreliable) | 5-tier structured recovery cascade |

### vs. Playwright / Selenium Automation

| Dimension | Playwright/Selenium | Conxa |
|---|---|---|
| Engineering cost | High (per-script coding, code maintenance) | Low (record + compile) |
| Maintenance | Manual (breaks on UI change, engineer required) | Self-healing recovery cascade |
| Distribution | Requires DevOps/CI/CD pipeline | .exe installer |
| Observability | None (script runs silently) | Cloud telemetry dashboard |
| AI integration | None | Claude Desktop native (extensible to other AI clients) |

### Why this is hard to replicate

The Conxa moat is not the recording step — others can record. It is the **semantic compilation pipeline**: the transformation of raw browser events into structured skill packages with element fingerprints, multi-tier recovery blocks, and validation assertions generated at compile time. This pipeline requires deep integration across LLM reasoning capabilities, browser accessibility internals, and iframe semantics. Building it takes years of iteration.

The resulting compiled skill packages are durable data assets. As recovery models improve, existing skills benefit without recompilation. As the install base grows, the telemetry layer provides insight into UI drift patterns across real customer machines — a feedback loop that improves compilation quality over time.

---

## 16. Success Metrics

### Business metrics

| Metric | Definition |
|---|---|
| Active plugins | Distinct slugs with ≥1 run in last 30 days |
| Monthly active companies | Companies with ≥1 successful execution |
| Skills published | Total compiled skill versions published to Cloud |
| Installs | Unique installer downloads |
| Recovery rate | % of failed steps that self-heal (Tier 2–4) without escalation |
| Escalation rate | % of executions reaching Tier 5 (human intervention required) |
| Execution success rate | % of started executions completing without error |

### Quality metrics

| Metric | Target | Source |
|---|---|---|
| Tier 1 success rate | >85% of steps resolve on first compiled selector | `tracking/{co}` events |
| Recovery without LLM | >95% of steps resolve via T1+T2 | Same |
| End-to-end compile time | <5 min for 10-step workflow | Build Studio logs |
| Sync latency | Updates live on next cold start | Sync logs |

### Platform health metrics

| Metric | Source |
|---|---|
| Cloud API p99 latency | Render metrics |
| LLM proxy token quota utilization | `/llm/proxy/usage` |
| Skill pack delta response time | `/skill-packs/{co}/delta` |
| Runtime crash rate | `runtime.log` uncaughtException events |

---

## 17. Long-Term Product Roadmap

### Phase 1 — Architecture Consolidation (Current)

*Goal: Make the current system production-reliable.*

- Real auth token validation at the runtime refresh endpoint (currently a stub).
- Per-file delta sync — stop shipping full skill packs on every version update.
- Redis-backed rate limiting and nonce store (currently in-memory; cleared on restart).
- Device and runtime registration in Cloud (currently telemetry is discarded on receipt).
- Wire RBAC to API routes (currently scaffolded but not enforced).

### Phase 2 — Production Readiness

*Goal: Ship to first enterprise customers with confidence.*

- Multi-user organization support (team publishing, role-based access).
- Execution audit log (tamper-evident, required for enterprise security review).
- macOS runtime support (build scripts exist; distribution path not tested).
- Installer code signing (Windows EV certificate — required to pass SmartScreen).
- SLA-backed uptime and public status page.
- Billing plan enforcement (Razorpay integration hardened, quota limits per plan).

### Phase 3 — Enterprise Readiness

*Goal: Pass enterprise security review and support multi-engineer team workflows.*

- SSO / SAML integration (Clerk Enterprise).
- On-premise option (self-hosted cloud backend via Docker Compose).
- Compliance exports (SOC 2 evidence, audit trails, GDPR data deletion).
- Advanced RBAC (per-skill access controls, read-only analyst role, CI/CD API keys).
- Skill marketplace (Company publishes skills; customers browse and install via dashboard).
- Workflow version history with rollback capability.

### Phase 4 — AI Agent Platform

*Goal: Become the infrastructure layer for AI-native automation products.*

- Multi-step orchestration with branching logic (conditional steps, loops).
- Dynamic input resolution (AI-powered parameter extraction from conversation context).
- Skill composition — chain skills across multiple applications in a shared browser session.
- Public skill registry (marketplace of pre-built, community-contributed workflows).
- API-first publishing SDK (companies integrate Conxa compilation into their CI/CD pipeline).

### Phase 5 — Multi-AI Distribution

*Goal: Become protocol-agnostic AI operability infrastructure.*

Claude Desktop is the first runtime host. It will not be the last.

As the AI assistant market matures, the delivery layer will fragment across:

- **ChatGPT** and OpenAI's tool-use ecosystem
- **Enterprise copilots** — Microsoft Copilot, Salesforce Einstein, ServiceNow AI
- **Internal AI systems** built on open-source models, operated without any external vendor
- **Multi-agent orchestrators** — where skills become composable components invoked by agent pipelines, not individual users
- **Future AI interfaces** that do not yet exist

Conxa's response to this fragmentation is not to chase each platform individually. The strategy is:

1. **Protocol-level adapters.** MCP is today's standard. As new interoperability protocols emerge, Conxa adds runtime adapters. The compiled skill package format is the invariant — the delivery mechanism is the variable.
2. **Skill package portability.** A skill compiled once in Build Studio is executable by any supported runtime host. The JSON skill package schema is designed to be runtime-agnostic and forward-compatible.
3. **Company-controlled distribution.** The Company decides which AI platforms their skills run on. Conxa provides the compilation, hosting, and distribution infrastructure; deployment targets are configurable.

The long-term product is not a Claude Desktop plugin manager. It is the operating layer that makes any software platform operable by any sufficiently capable AI system — regardless of which systems exist, which protocols they speak, or how the AI industry evolves.
