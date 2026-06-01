# Conxa — Product Requirements Document

**Version:** 1.0
**Status:** Foundational Product Definition
**Owner:** Conxa

---

## 1. Product Overview

**Product Name:** Conxa

**One-Line Description:** Conxa turns any human-performed software workflow into a precompiled, self-healing skill that AI agents can execute reliably — without writing code or touching the target application.

**Mission:** Make every software platform operable by AI, exactly as humans operate it today.

**Vision:** A world where AI agents handle repetitive software work end-to-end — not by navigating UIs from scratch on every run, but by executing precompiled, battle-tested skills that already know what to do, where to look, and how to recover when things go wrong. Conxa is the infrastructure that makes that possible.

---

## 2. The Problem

AI agents are becoming the default interface for getting work done. But the software they need to operate was built for humans — not for agents.

Today's approaches all break in predictable ways:

- **Traditional RPA** encodes brittle selectors. One UI update and everything breaks. Maintenance costs compound faster than value delivered.
- **Browser automation scripts** are developer tools, not something a SaaS company can hand to a customer.
- **Sending an AI agent to navigate live UI** works for demos. It fails at scale — token costs explode, latency is high, and reliability is inconsistent because the agent rediscovers the interface on every run.
- **Native integrations (APIs, webhooks)** require the SaaS vendor to build and maintain them — expensive, slow, and impossible for long-tail workflows that exist inside a product but don't justify a dedicated API.

The gap: there is no infrastructure layer that lets an AI agent reliably operate existing software at human-equivalent reliability, without requiring the software vendor to build anything.

Conxa fills that gap.

---

## 3. The Solution

Conxa separates the "teach" step from the "execute" step.

A human performs a workflow once in the **Build Studio**. Conxa records not just the clicks — it captures intent, UI structure, element relationships, visual fingerprints, and recovery context. This session is compiled locally into a **Skill Package**: a structured, versioned execution artifact that encodes everything the runtime needs to execute the workflow reliably.

That Skill Package is published to **Conxa Cloud**, packaged into a branded `.exe` installer, and distributed to end customers. On the customer's machine, the **Conxa Runtime** — a local MCP server — downloads the skill, exposes it as a Claude tool, and executes it with full self-healing recovery. Execution never leaves the customer's machine.

```
SaaS Vendor                   Conxa Cloud               End Customer
──────────────────            ───────────               ────────────────────────
Record workflow     →    Host + version + bill    →    Execute locally via
in Build Studio          Distribute installer          Claude Desktop (MCP)
```

The result: the SaaS vendor teaches the workflow once. Their customers get it forever, always up-to-date, always recoverable.

---

## 4. Core Value Proposition

**For SaaS companies:** Ship AI-native capabilities to your customers without touching your codebase. Record your product's workflows once in the Build Studio — Conxa compiles them into skills and distributes them to your customers as a branded installer. No API, no SDK, no new engineering headcount.

**For enterprises:** Stop relying on humans for repetitive software work. Give Claude the skills it needs to operate your tools the same way your team does — reliably, at scale, without token waste.

**For AI agents:** Execute precompiled workflow skills instead of navigating live interfaces from scratch. Lower token cost, deterministic step execution, and built-in recovery that handles UI drift automatically.

---

## 5. Why Now

Three shifts are converging:

1. **MCP is becoming the standard interface between AI agents and tools.** Claude Desktop's MCP protocol is the first widely-adopted substrate for agent-to-tool communication. Conxa is built natively on MCP — skills are exposed directly as Claude tools.

2. **AI agents are graduating from demos to production.** Enterprises are now asking how Claude handles their actual software stack — not hypothetically, but operationally. There is no good answer without execution infrastructure.

3. **SaaS companies need an AI-native distribution channel.** "How do I make my product work with Claude?" is a question every SaaS product team is now asking. Conxa answers it without requiring API investment.

---

## 6. Target Customers

### Primary: SaaS Companies

SaaS vendors who want to make their platform operable by Claude without building native AI integrations.

They record their own product's workflows in the Build Studio, publish skills to the cloud, and distribute them to their customers. Conxa handles compilation, hosting, distribution, versioning, and telemetry.

Relevant verticals:
- CRM and sales platforms
- Marketing and growth tools
- HR and people management platforms
- Customer success and support tools
- Internal business operations software

### Primary: Enterprises

Organizations with high-volume, repetitive software work that currently requires human operators.

They use the Build Studio to record their own internal workflows, deploy skills to their teams, and let Claude execute them through Claude Desktop.

Relevant teams:
- Operations and back-office
- Finance and accounting
- Sales operations
- Customer support

### Secondary

- Automation consultants building skills for client stacks
- Agencies managing software operations at scale
- Internal IT teams standardizing software access for AI tooling
- AI-first startups that need reliable non-API software integrations

---

## 7. Product Components

### Conxa Build Studio

A Windows desktop application (Electron + Python) that runs entirely locally. The SaaS vendor or enterprise user uses it to:

- Record browser workflows using an injected capture bridge
- Review and edit captured workflows step-by-step
- Compile workflows locally into Skill Packages — no cloud involvement in this step
- Build plugin archives and NSIS installer packages
- Publish compiled skills to Conxa Cloud

Recording, compilation, and packaging are entirely local. The cloud is not in the execution path during build.

### Conxa Cloud

A thin coordination layer (FastAPI on Render, Next.js on Vercel) that handles:

- Skill package hosting and versioning
- Installer hosting and distribution
- LLM proxy for compile-time AI calls (multi-provider: Groq, Google AI Studio, NVIDIA NIM)
- Billing and subscription management (Razorpay)
- Execution telemetry and run analytics
- Team and organization management

The cloud does not record, compile, or execute workflows. It is coordination infrastructure.

### Conxa Runtime

A Node.js MCP server that ships inside the vendor's branded `.exe` installer and runs on the end customer's machine. It:

- Registers itself with Claude Desktop as an MCP server on startup
- Syncs skill packs from Conxa Cloud (delta sync, SHA-256 verified)
- Exposes skills as native Claude tools (`execute_skill`, `list_skills`, `get_skill_inputs`, etc.)
- Executes skills locally via Playwright with a 5-tier self-healing recovery cascade
- Streams execution telemetry back to Conxa Cloud
- Self-updates by polling the runtime manifest

Execution never leaves the customer's machine.

### MCP Layer

Conxa Runtime speaks the Model Context Protocol natively. Skills appear to Claude as first-class tools. Claude can discover available skills, request required inputs, execute them, monitor status, and cancel runs — all through the standard MCP interface without any custom integration.

---

## 8. Key Capabilities

### Workflow Recording

The Build Studio injects a capture bridge into the browser that records every interaction at the event level — clicks, inputs, navigation, scroll, focus, iframe transitions, and screenshots. Metadata is captured alongside each action: element role, text content, bounding box, page URL, and frame chain.

### Multi-Signal Compilation

Recorded sessions are normalized, deduplicated, and enriched through a local compilation pipeline. Each step is analyzed for:

- **Primary selectors** — multiple compiled strategies ranked by specificity and resilience
- **Semantic intent** — what the step is trying to accomplish, not just where it clicks
- **Anchors** — nearby stable text elements used as spatial landmarks
- **Visual fingerprints** — screenshot crops for vision-based recovery
- **Assertions** — expected post-step UI state to validate correct execution
- **Recovery metadata** — everything needed to re-find and re-execute if the element has moved or changed

### Self-Healing Execution — 5-Tier Recovery

When a step fails to find its target element, the runtime escalates through five recovery tiers:

| Tier | Strategy | LLM Cost |
|---|---|---|
| 1 | Compiled selectors — try each in ranked order | Zero |
| 2 | Accessibility tree — role + name lookup | Zero |
| 3 | Semantic recovery — Claude analyzes DOM to find the element | LLM call |
| 4 | Vision recovery — Claude analyzes screenshot to locate target | LLM call |
| 5 | Escalation — surface to human for review | Human |

Tiers 1 and 2 consume zero LLM tokens. The system only escalates to Claude when cheaper methods are exhausted.

### Workflow Editing

After recording, vendors can review the captured workflow step-by-step, modify individual actions, add conditional logic, annotate intent, and verify the execution plan before compilation.

### Skill Distribution

Compiled skills are packaged into a self-contained plugin archive and bundled into an NSIS Windows installer. The installer is hosted on Conxa Cloud and linked from the vendor's dashboard. End customers download and run it — the runtime installs itself, registers with Claude Desktop, and is immediately available.

### Skill Versioning and Sync

When a vendor updates a skill and republishes, the runtime on every customer machine detects the delta at next sync and atomically updates the local skill pack. No customer action required.

### Execution Telemetry

Every execution emits structured telemetry — step outcomes, recovery tiers used, latency, failure points. Vendors see this in their Conxa Cloud dashboard as run timelines and aggregate analytics.

---

## 9. Major Use Cases

**CRM operations** — Create leads, update contacts, log calls, manage pipeline stages, generate reports.

**Customer onboarding** — Provision new accounts, configure initial settings, trigger welcome sequences, set up integrations.

**Invoice and finance processing** — Upload documents, extract structured data, update accounting systems, trigger approval flows.

**HR and people ops** — Onboard new employees, provision access, run payroll inputs, generate compliance reports.

**DevOps and cloud management** — Environment setup, deployment triggers, infrastructure configuration, cloud console operations.

**Internal reporting** — Pull data from operational tools, populate dashboards, generate and distribute regular reports.

**Social and content operations** — Schedule and publish content, pull engagement reports, manage accounts across platforms.

---

## 10. Competitive Positioning

### vs. Traditional RPA (UiPath, Automation Anywhere)

RPA encodes point-in-time selectors into brittle scripts. UI changes break automations. Maintenance is continuous and expensive. These platforms are designed for IT-managed enterprise deployments — not for SaaS vendors to distribute to customers.

Conxa's advantage: multi-signal compilation means skills degrade gracefully rather than breaking hard. Self-healing recovery handles UI drift automatically. And Conxa is distribution infrastructure — skills ship with the product, not as internal IT projects.

### vs. Browser Automation Tools (Playwright, Puppeteer)

Developer tools that require code. They have no compilation model, no recovery architecture, no distribution mechanism, and no AI integration. They solve a different problem for a different audience.

Conxa's advantage: no-code skill creation, built-in recovery, and native MCP distribution. A product manager can record a workflow and ship it to customers.

### vs. AI Agents Navigating Live UI

Sending an AI agent to navigate a live interface from scratch on every run costs tokens, takes time, and produces inconsistent results because the agent must rediscover the interface continuously.

Conxa's advantage: precompiled skills encode the execution graph once. The agent executes a skill, not a navigation session. Token cost is bounded, latency is lower, and reliability is deterministic.

### vs. Native API Integrations

APIs require the software vendor to build and maintain them. They're unavailable for long-tail workflows, require developer resources, and lag behind UI-level capabilities.

Conxa's advantage: zero engineering required from the software vendor. If a human can do it in the browser, Conxa can make it a skill.

---

## 11. Success Metrics

### Product Health

- Skill compilation success rate
- Execution success rate (steps completed without Tier 3+ recovery)
- Recovery success rate (failures resolved by Tier 1–4 before escalation)
- Skill reuse rate across executions

### Business Traction

- Active vendor organizations on the platform
- Skills published and distributed
- Active runtimes (customer installs)
- Monthly skill executions
- Enterprise customers under contract

### Technical Quality

- Runtime stability (uptime, crash rate)
- Sync success rate (skill pack delivery)
- Execution latency (p50/p95 per skill)
- Self-update success rate

---

## 12. Product Principles

**Reliability over features.** A skill that works 99% of the time is worth more than ten features that work 70% of the time. Execution reliability is the core product promise — everything else is secondary.

**Teach once, run forever.** The human's time is spent once, at recording. Every execution after that should require no human involvement unless something genuinely can't be recovered automatically.

**Local execution, cloud coordination.** Customer data never transits through Conxa infrastructure during execution. The cloud coordinates — it does not execute. This is a security and trust property, not just an architecture choice.

**Zero-cost recovery by default.** Tier 1 and 2 recovery cost nothing. LLM escalation is a last resort, not a default fallback. Skills should be compiled with enough redundancy that most real-world UI drift resolves without an LLM call.

**AI-native from the protocol up.** Conxa is not bolted onto an existing automation platform. It is designed from the ground up for AI agent consumption via MCP — skills are first-class Claude tools, not wrapped scripts.

---

## 13. Long-Term Vision

Conxa's goal is to become the universal execution layer between AI agents and existing software.

Near-term, this means every SaaS vendor can ship Claude-operable skills alongside their product — turning AI compatibility into a distribution feature, not an engineering project.

Medium-term, this means enterprises running AI workforces where Claude handles entire operational domains — not occasionally, but as the primary operator — with Conxa skills as the execution substrate.

Long-term, this means a marketplace of skills covering the SaaS ecosystem: any agent, any model, any workflow — recorded once by someone, available to everyone. Conxa becomes the npm of AI-executable software operations.

---

## Final Statement

Conxa is not a browser automation tool, a macro recorder, or a traditional RPA platform.

Conxa is execution infrastructure for AI agents — the layer that turns human-performed software workflows into precompiled, self-healing, MCP-native skills that Claude can operate reliably, at scale, on any machine, without touching the target software's codebase.

The interface was already built. Conxa makes it AI-operable.
