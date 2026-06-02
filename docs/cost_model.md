# Conxa Cost & Revenue Model

**Last Updated:** June 3, 2026
**Status:** Living document — iterate as assumptions change

---

## What Conxa Actually Does

A company records their browser workflows in the Build Studio. Conxa compiles those recordings into a signed `.exe` installer. The company distributes that installer to their customers however they want (download page, onboarding email, their own app store).

When a customer installs it, their Claude Desktop gains the ability to run those workflows as MCP tools. Execution happens entirely on the customer's machine — Conxa is not in the execution path at all.

What does flow back to Conxa is telemetry: every run, every recovery attempt, every success or failure. Companies see this in the Conxa dashboard.

```
Company builds once               Customer runs forever
─────────────────                 ─────────────────────
Build Studio                      Customer machine
  └─ Record workflows               └─ .exe installed
  └─ Compile to plugin              └─ Claude Desktop
  └─ Generate .exe ──── distribute ──► └─ MCP runtime
  └─ Push update                          └─ executes workflow
                                          └─ telemetry ──► Conxa Dashboard
                                                            └─ Company sees it
```

**What Conxa pays for:**
- Compilation LLM (one-time per workflow compilation, plus Human Edit repair calls)
- Dashboard hosting (companies checking analytics)
- Telemetry ingestion (from customer machines worldwide)
- Signing, release management, and update-channel infrastructure
- Plugin update sync (when company ships an update, customers pull it)
- Conxa runtime and healing updates that keep installed plugins working

**What Conxa does NOT pay for:**
- Execution (runs on customer's machine)
- LLM recovery during execution (customer's Claude Desktop subscription)
- Customer infrastructure of any kind

---

## Cost Structure

### 1. Plugin Compilation (One-Time Per Workflow Compilation)

Every time a company records workflows and compiles them into a new plugin version, Conxa runs LLM calls per step to generate selectors, anchors, and intent.

#### LLM Calls Per Step

| Call | Prompt size | When | Count/step |
|------|-------------|------|------------|
| **Intent detection** (`generate_intent_with_llm`) | ~200 input + ~50 output tokens | Every step — but **cached** by element hash | 1 (0 on cache hit) |
| **Vision anchor generation** (`generate_anchors_for_step_or_raise`) | ~15K input + ~500 output tokens (screenshot JPEG as base64 + prompt) | Every step — but **cached** by screenshot hash | 1 (0 on cache hit) |
| **Selector self-consistency** (`generate_selector_candidates`, `num_samples=5`) | ~15K input + ~2.5K output tokens total (5 samples) | Only if heuristic selector confidence < 1.0 | 5 (0 on perfect heuristic) |

**Best case (heuristic hits — clean `data-testid` or `aria-label`):** 2 calls/step  
**Typical case (LLM selectors needed):** 7 calls/step  
**Recompilation (same DOM, cached):** 0–2 calls/step — caching absorbs most of the cost

#### Corrected Cost Per Workflow Compilation

#### LLM Provider Strategy — Two Separate Pools

**Trial plan and paid plans use completely different LLM providers.**

| Plan | Provider Pool | Rationale |
|------|--------------|-----------|
| **Trial (free)** | Groq + Google AI Studio + NVIDIA NIM (free-tier key rotation) | Zero LLM cost; rate limits acceptable at low volume |
| **Starter / Pro** | **GPT-5.4-mini + Gemma 4 31B** | Fast, low-cost paid compilation with enough burst capacity for active teams |
| **Enterprise** | **GPT-5.4 + Claude Sonnet 4.6 Vision** | Highest-quality compilation and vision handling for complex customer workflows |

**Why separate paid pools:**
Companies compile in bursts — not a constant drip all day. When someone hits compile, the job should finish in seconds. Free-tier providers have tight rate limits (30 req/min on Groq) that cause queuing under burst load.

- **Starter / Pro**: GPT-5.4-mini handles vision anchors and selector generation; Gemma 4 31B handles intent and text fallback work.
- **Enterprise**: GPT-5.4 handles the core compilation path; Claude Sonnet 4.6 Vision is reserved for the most complex screenshot and visual-anchor cases.

Paid plans still avoid free-tier queueing. Starter and Pro optimize for cost and speed; Enterprise optimizes for maximum reliability and visual reasoning quality.

**How it routes in the existing code:**  
`router.py` builds a `PoolEntry` per key. The Build Studio backend reads the workspace billing tier from the cloud API and passes `paid_tier=True` to select the appropriate pool at compile time. No router rewrite needed — just two separate pool configs loaded from env.

---

#### Current Provider Prices Used

Pricing checked against provider docs on June 3, 2026:

| Provider / model | Input | Output | Relevant limit / note | Source |
|------------------|-------|--------|-----------------------|--------|
| GPT-5.4-mini | $0.75 / 1M tokens | $4.50 / 1M tokens | Tier 4: 10M TPM; Tier 5: 180M TPM | [OpenAI GPT-5.4-mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [OpenAI pricing](https://openai.com/api/pricing/) |
| GPT-5.4 | $2.50 / 1M tokens | $15.00 / 1M tokens | Tier 4: 4M TPM; Tier 5: 40M TPM | [OpenAI GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4), [OpenAI pricing](https://openai.com/api/pricing/) |
| Together AI Gemma 4 31B | $0.39 / 1M tokens | $0.97 / 1M tokens | Serverless limits are dynamic; use dedicated endpoints for predictable bursts | [Together pricing](https://www.together.ai/pricing), [Together rate limits](https://docs.together.ai/docs/serverless/rate-limits) |
| Claude Sonnet 4.6 Vision | $3.00 / 1M tokens | $15.00 / 1M tokens | Use Priority Tier or custom Enterprise limits for bursty vision work | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Anthropic rate limits](https://platform.claude.com/docs/en/api/rate-limits) |

Claude Opus is a quality upgrade path, not the default Enterprise cost model. It is materially more expensive than Sonnet and should only be used when Sonnet 4.6 Vision cannot resolve the workflow.

#### Cost Per Compilation by Plan

**Trial plan (free-tier providers):**

Token costs at Groq (text) + Google AI Studio (vision):
- Intent: ~200 tokens → **~$0.00001** (negligible)
- Vision anchor: ~15K tokens at $0.075/1M → **~$0.001/step**
- Selectors × 5: ~3K input + 500 output each → **~$0.001/step**
- **Total/step: ~$0.002 | Per compilation (15 steps): ~$0.03**

**Starter / Pro paid plans (GPT-5.4-mini + Together AI Gemma 4 31B):**

- Intent (Gemma 4 31B, 200 input + 50 output): **~$0.00013/step**
- Vision anchor (GPT-5.4-mini, 15K input + 500 output): **~$0.0135/step**
- Selectors × 5 (GPT-5.4-mini, 15K input + 2.5K output): **~$0.0225/step**
- **Total/step: ~$0.036 | Fresh 15-step workflow: ~$0.54**
- **Cached recompilation (3 changed steps): ~$0.11**
- **Blended monthly average (20% fresh, 80% cached): ~$0.195/compilation**

**Enterprise paid plans (GPT-5.4 + Claude Sonnet 4.6 Vision):**

- Intent + selector work on GPT-5.4: **~$0.076/step**
- Vision anchor on Claude Sonnet 4.6 Vision: **~$0.0525/step**
- **Total/step: ~$0.129 | Fresh 15-step workflow: ~$1.93**
- **Cached recompilation (3 changed steps): ~$0.39**
- **Blended monthly average (20% fresh, 80% cached): ~$0.695/compilation**

| Scenario | Trial cost | Starter / Pro cost | Enterprise cost |
|----------|------------|--------------------|-----------------|
| Short workflow (5 steps) | ~$0.01 | ~$0.18 | ~$0.64 |
| Medium workflow (15 steps) | ~$0.03 | **~$0.54** | **~$1.93** |
| Long workflow (30 steps) | ~$0.06 | ~$1.08 | ~$3.86 |
| Recompilation (cached, 3 changed steps) | ~$0.003 | **~$0.11** | **~$0.39** |
| **Blended (80% recompiles, 15 steps avg)** | **~$0.008** | **~$0.195** | **~$0.695** |

**Key insight on continuous iteration:** Both intent and vision anchor calls are cached by element hash (`intent_llm.py`, `anchor_vision_llm.py`). Recompiling a workflow where only 2–3 steps changed fires LLM only for those steps — the rest are cache hits. This makes daily iteration cheap regardless of provider.

**Hidden Human Edit reserve:** Human Edit can trigger extra LLM calls after the initial compile: step repair, selector or anchor regeneration, validation, and recovery artifact updates. Budget a **10–25% LLM reserve** on Starter/Pro and a **15–40% LLM reserve** on Enterprise because visual repair paths are more likely to hit Claude Vision. These calls are compilation/recompilation cost, not execution cost, because customer-side workflow execution still runs locally.

**Example — Company on Starter (paid plan), 1 plugin, 50 workflows:**
- Initial build: 50 × $0.54 = **$27 one-time**
- Monthly iteration (recompile 10 workflows × 3 times, 3 changed steps): 30 compilations × $0.11 = **$3.30/month**
- Human Edit reserve: **~$0.33–$0.83/month** on that iteration pattern

| Component | Trial plan | Starter / Pro | Enterprise |
|-----------|------------|---------------|------------|
| LLM per compilation (first build) | ~$0.03 | ~$0.54 | ~$1.93 |
| LLM per recompilation (cached 3-step change) | ~$0.003 | ~$0.11 | ~$0.39 |
| Build infrastructure | $0.10 | $0.10 | $0.10 |
| Human Edit LLM reserve | Usage-based | 10–25% | 15–40% |
| **Blended per compilation** | **~$0.008** | **~$0.195** | **~$0.695** |

---

### 2. Burst Capacity and Throughput

Conxa does not need maximum LLM capacity all day. Compilation demand comes in bursts when teams record, edit, and publish workflows. The paid pool should therefore buy high TPM and throughput for burst windows, not idle 24/7 capacity.

| Pool | Normal configuration | Burst configuration | Why |
|------|----------------------|---------------------|-----|
| Starter / Pro OpenAI | GPT-5.4-mini Standard Tier 4 | GPT-5.4-mini Tier 5, Scale Tier, or Reserved Capacity for 100+ fresh workflow compilations/min | Tier 4 gives 10M TPM, enough for roughly 20 fresh 15-step workflow compilations/min at the current token shape; Tier 5 gives 180M TPM for much larger bursts |
| Starter / Pro Together | Gemma 4 31B serverless for low-volume intent/text fallback | Dedicated endpoint replicas during known compile bursts | Together serverless limits are dynamic and can throttle sudden spikes; dedicated endpoints provide reserved hardware and predictable latency |
| Enterprise OpenAI | GPT-5.4 Tier 4 for normal Enterprise compile traffic | GPT-5.4 Tier 5, Scale Tier, or Reserved Capacity | Tier 4 gives 4M TPM; Tier 5 gives 40M TPM for heavier Enterprise bursts |
| Enterprise Anthropic | Claude Sonnet 4.6 Vision with standard limits | Priority Tier or custom Enterprise limits | Standard Anthropic limits are caps, not guaranteed minimum throughput; bursty vision workloads should use priority or negotiated limits |

OpenAI Priority processing should be used only for latency-sensitive compile jobs. It improves speed/reliability but shares the same rate limits, so it does not replace Tier 5, Scale Tier, or Reserved Capacity for very large bursts. Together dedicated endpoints can be started for planned compilation windows and stopped afterward; billing is per-minute by hardware while the endpoint is running.

---

### 3. Dashboard Hosting (Monthly Fixed)

Companies log into the Conxa dashboard to:
- View analytics (runs, success rate, recovery rate, who used what)
- Manage plugin versions (publish, rollback, deprecate)
- Download installer artifacts (.exe per platform)
- Configure billing and team access

Traffic is low — these are **companies**, not millions of end users. A company might check the dashboard 5–10 times a day, not 5 times a second.

| Scale | Companies | Dashboard Requests/Day | Backend Cost | DB Cost | Total |
|-------|-----------|------------------------|-------------|---------|-------|
| MVP | 10 | ~500 | $20 | $15 | **$35** |
| Growth | 100 | ~5,000 | $50 | $30 | **$80** |
| Scale | 500 | ~25,000 | $150 | $80 | **$230** |
| Enterprise | 2,000 | ~100,000 | $500 | $200 | **$700** |

Dashboard is not a cost problem. It scales gracefully because it's company-facing, not end-user-facing.

---

### 4. Telemetry Ingestion (Scales With Customer Base)

Every time a customer runs a workflow anywhere in the world, a telemetry event flows back to Conxa. This is where costs actually scale — not with companies, but with the combined size of all their customer bases.

**Telemetry payload per execution:** ~1–2KB (run ID, plugin ID, step outcomes, recovery tiers reached, timestamps)

| Scale | Companies | Avg Customers/Company | Daily Runs | Monthly Telemetry Events | Ingestion Cost |
|-------|-----------|----------------------|------------|--------------------------|---------------|
| MVP | 10 | 100 | 1,000 | 30K | $5 |
| Growth | 100 | 500 | 50,000 | 1.5M | $50 |
| Scale | 500 | 2,000 | 1,000,000 | 30M | $500 |
| Enterprise | 2,000 | 5,000 | 10,000,000 | 300M | $3,000 |

**Telemetry stack:** Events hit the `/api/v1/tracking` endpoint → write to append-only log → aggregate into analytics tables daily. No real-time processing needed; companies are fine seeing yesterday's data.

**Retention policy:** Because Conxa already tracks runs, recovery attempts, success/failure outcomes, and adoption telemetry, data retention is both a product feature and a storage-control lever. Shorter retention keeps Trial/Starter storage small; longer Pro/Enterprise retention gives companies more historical analytics without changing the execution model.

---

### 5. Plugin Update Sync (Per Update Release)

When a company ships a plugin update, customers pull the new version. The `/skill-packs/*` endpoint serves the updated plugin package.

| Component | Cost | Notes |
|-----------|------|-------|
| Storage per plugin version | ~$0.01/GB | Compiled plugin packages are small (~5–50MB) |
| CDN bandwidth per update rollout | ~$0.01/GB | 100 customers × 10MB = 1GB = $0.01 |
| **Total per update** | **~$0.02–0.10** | Negligible |

---

### Total Monthly Operating Cost

Assumes blended compilation cost before Human Edit reserve: **~$0.195** for Starter/Pro traffic and **~$0.695 (~$0.70)** for Enterprise-grade traffic. Plugin packaging itself is treated as materially free.

| Scale | Companies | Workflow Compilations/Month | Compilation | Dashboard | Telemetry | Updates | **Total/Month** |
|-------|-----------|--------------|-------------|-----------|-----------|---------|-----------------|
| MVP | 10 | 20 Starter/Pro | ~$4 | $35 | $5 | $2 | **~$46** |
| Growth | 100 | 200 Starter/Pro | ~$39 | $80 | $50 | $20 | **~$189** |
| Scale | 500 | 1,000 Starter/Pro | ~$195 | $230 | $500 | $100 | **~$1,025** |
| Enterprise | 2,000 | 5,000 Enterprise-grade | ~$3,475 | $700 | $3,000 | $400 | **~$7,575** |

**Cost lever:** Increasing heuristic hit rate (better `data-testid` coverage guidance to companies) reduces compilation cost by up to 70% (7 calls/step → 2 calls/step on clean DOM).

---

## Revenue Model

Companies pay Conxa to **build and maintain** their Claude-compatible plugin. They think about it the same way they think about their mobile app on the App Store — there's a platform fee to be listed and maintained, not a per-download fee.

### Tier Design Principles

**What companies actually look like:**
- They build **1–3 plugins** — each plugin IS their product (e.g. "Gmail Automation for SalesForce users")
- Each plugin contains **many workflows** (10–100) covering different user tasks
- They **iterate continuously during the first month** — recording fixes, step adjustments, selector updates happen daily while the product is being made production-ready
- After the first month, most companies settle into **maintenance mode** — 1–2 meaningful workflow/plugin updates per month
- Plugin count is not a meaningful constraint. Compilation volume is everything.

**The right usage axis to cap is workflow compilations per month.** But Conxa is not a pay-per-compilation product. The monthly subscription also keeps the plugin operational: dashboard analytics, telemetry retention, signing and artifact availability, update delivery, team access, support, and Conxa runtime/healing updates.

---

### Build Lifecycle Economics

The highest LLM cost is usually concentrated in the first month after a company creates a plugin. That is when teams record many workflows, use Human Edit heavily, and recompile repeatedly while polishing the installer.

After that, the same company often updates only 1–2 workflows per month. At that point Conxa's direct LLM cost drops sharply, but the customer still pays the full monthly subscription because Conxa is still providing the platform surface that keeps the plugin useful.

| Phase | Typical behavior | Conxa cost pattern | Why monthly billing still applies |
|-------|------------------|--------------------|-----------------------------------|
| Initial build month | 50–300+ compilations, frequent Human Edit, repeated plugin builds | High LLM usage; full tier cap matters | Customer is creating and stabilizing the product |
| Maintenance months | 1–2 workflow updates/month, occasional plugin rebuilds | Low LLM usage; dashboard/telemetry/signing dominate | Plugin remains live, signed, tracked, updateable, and supported |
| Conxa platform updates | Conxa ships runtime, healing, recovery, or signing updates | Mostly platform engineering and update-sync cost | Customers benefit even without recompiling their workflows |

Example: a Starter customer that used the full 300-compilation allowance in month 1 costs roughly **$71–$80** at full included usage. If the same customer later makes two cached 3-step workflow updates in a month, direct compilation cost is roughly **2 × $0.11 = $0.22** before Human Edit reserve, while they still pay **$199/month** for the dashboard, signing, telemetry retention, update delivery, and healing/runtime improvements.

This is why margins improve after the first build month. The cap protects Conxa during build-heavy periods; the subscription captures the ongoing value after the plugin is live.

---

### Pricing Tiers

**Limit definitions:**
- **Plugins** — distinct products hosted on Conxa (kept high; not the real constraint)
- **Workflow compilations/month** — each time a recorded workflow runs through the compile pipeline (the cost driver; includes recompilations)
- **Plugin builds/month** — packaging compiled workflows into a distributable artifact; matched to workflow compilations because plugin packaging itself does not materially cost Conxa
- **.exe builds/month** — generating the installer binary (Windows/Mac)

| | **Trial** | **Starter** | **Pro** | **Enterprise** |
|--|-----------|-------------|---------|----------------|
| **Price** | $0 / 14 days | $199/mo | $499/mo | Custom |
| **Plugins** | 1 | 3 | 10 | Unlimited |
| **Workflow compilations/mo** | 30 | 300 | 1,500 | Unlimited |
| **Plugin builds/mo** | 30 | 300 | 1,500 | Unlimited |
| **.exe builds/mo** | 1 | 3 | 15 | Unlimited |
| **Analytics retention** | 7 days | 90 days | 1 year | Custom |
| **Team seats** | 1 | 3 | 10 | Unlimited |
| **Support** | 24/7 support | 24/7 support | 24/7 support | 24/7 support |
| **White-label .exe** | No | No | Yes | Yes |

**Why 300 compilations for Starter:**  
A company with 1 plugin × 50 workflows = 50 initial compilations. Active iteration (recompiling updated workflows daily) = ~5–10 recompilations/day = 150–300/month. 300 is comfortable for an actively developing team without being wasteful.

Importantly: **recompilations are ~10× cheaper than initial builds** because intent and vision anchor results are cached by hash. 300 recompilations ≈ 30 equivalent "fresh" builds in LLM cost.

**Why 1,500 for Pro:**  
A company with 3 plugins × 100 workflows each, iterating across multiple workflows daily. Enough room for full-scale product development.

*Overage pricing (add later when data exists):* start at **$0.50 per extra Starter/Pro compilation** and custom-price Enterprise overages by model mix; $0 per extra plugin build while packaging remains materially free; $5 per extra `.exe` build.

---

### Cost Per Tier (What Conxa Spends)

Using recalculated LLM costs from current provider pricing. Assume 80% of monthly compilations are cached recompilations and 20% are fresh full-workflow compilations.

| | **Trial** | **Starter** | **Pro** | **Enterprise (est.)** |
|--|-----------|-------------|---------|----------------------|
| LLM provider | Free-tier rotation | GPT-5.4-mini + Together Gemma 4 31B | GPT-5.4-mini + Together Gemma 4 31B | GPT-5.4 + Claude Sonnet 4.6 Vision |
| Compilations cost (blended, before Human Edit) | 30 × $0.008 = $0.24 | 300 × $0.195 = **$58.50** | 1,500 × $0.195 = **$292.50** | 15,000 × ~$0.70 = **~$10.4K** |
| Human Edit reserve | Usage-based | 10–25% = **$5.85–$14.63** | 10–25% = **$29.25–$73.13** | 15–40% = **~$1,564–$4,170** |
| Plugin builds (no material cost) | $0 | $0 | $0 | $0 |
| .exe builds (~$0.50 each) | $0.50 | $1.50 | $7.50 | $150 |
| Dashboard + telemetry share | $2 | $5 | $10 | $200 |
| **Total cost/company/month** | **~$3** | **~$71–$80** | **~$339–$383** | **~$11.8K–$14.9K** |
| **Revenue** | $0 | **$199** | **$499** | **Custom; ~$30K/mo floor for 15K included compilations** |
| **Gross Margin at full included usage** | — | **~60–64%** | **~23–32%** | **~50–61% at ~$30K/mo** |
| **Maintenance-month gross margin** | — | **~95%+** | **~95%+** | **Contract-dependent, usually much higher than build month** |

**Blended Starter/Pro compilation cost** = (20% fresh × $0.54) + (80% cached × $0.11) = ~$0.195/compilation.
**Blended Enterprise compilation cost** = (20% fresh × $1.93) + (80% cached × $0.39) = ~$0.695/compilation, rounded to **~$0.70/compilation** for tier planning.
**Blended compilation cost (free tier)** = (20% fresh × $0.03) + (80% cached × $0.003) = $0.008/compilation.

**Pricing implication:** Pro's 1,500-compilation cap is generous but margin-sensitive if a customer sits at the cap every month. That is usually a first-month or major-release behavior, not a steady-state pattern. Enterprise cannot include 15,000 GPT-5.4 + Claude Vision compilations at a $2,999 price point; that volume needs custom pricing around a ~$30K/month floor or a lower committed compilation allowance.

---

## Unit Economics

These scenarios assume a conservative build-heavy month where customers use their full included compilation allowance and include a midpoint Human Edit reserve: **17.5%** for Starter/Pro and **27.5%** for Enterprise. Maintenance months are materially cheaper because live plugins usually receive only 1–2 updates while still paying for dashboard, signing, telemetry, support, update delivery, and Conxa healing/runtime improvements.

### Scenario A: MVP (10 Companies)
Mix: 7 Starter × $199, 3 Pro × $499

| | Value |
|-|-------|
| **Monthly Revenue** | (7 × $199) + (3 × $499) = **$2,890** |
| Compilation LLM + Human Edit reserve | **~$1,512** (7×~$68.74 + 3×~$343.69) |
| Infrastructure | $126 |
| **Total Cost** | **~$1,638** |
| **Gross Margin** | **~43%** |
| **Monthly Profit** | **~+$1,252** |

**Break-even:** 2 paying companies covers all costs.

---

### Scenario B: Growth (100 Companies)
Mix: 50 Starter, 40 Pro, 10 Enterprise × $29,999 custom floor

| | Value |
|-|-------|
| **Monthly Revenue** | (50×$199) + (40×$499) + (10×$29,999) = **$329,900** |
| Compilation LLM + Human Edit reserve | **~$150,123** |
| Infrastructure | $990 |
| **Total Cost** | **~$151,113** |
| **Gross Margin** | **~54%** |
| **Monthly Profit** | **~+$178,787** (~$2.1M/year) |

---

### Scenario C: Scale (500 Companies)
Mix: 250 Starter, 200 Pro, 50 Enterprise × $29,999 custom floor

| | Value |
|-|-------|
| **Monthly Revenue** | (250×$199) + (200×$499) + (50×$29,999) = **$1,649,500** |
| Compilation LLM + Human Edit reserve | **~$750,610** |
| Infrastructure | $5,030 |
| **Total Cost** | **~$755,640** |
| **Gross Margin** | **~54%** |
| **Monthly Profit** | **~+$893,860** (~$10.7M/year) |

---

### Scenario D: Enterprise (2,000 Companies)
Mix: 800 Starter, 900 Pro, 300 Enterprise × $29,999 custom floor

| | Value |
|-|-------|
| **Monthly Revenue** | (800×$199) + (900×$499) + (300×$29,999) = **$9,608,000** |
| Compilation LLM + Human Edit reserve | **~$4,352,438** |
| Infrastructure | $25,100 |
| **Total Cost** | **~$4,377,538** |
| **Gross Margin** | **~54%** |
| **Monthly Profit** | **~+$5,230,462** (~$62.8M/year) |

---

## Growth Milestones

| Milestone | Companies | Monthly Revenue | Monthly Cost | Profit | Key Actions |
|-----------|-----------|-----------------|--------------|--------|-------------|
| **MVP live** | 10 | $2,890 | ~$1,638 | +$1,252 | Ship billing; wire paid LLM pools for Starter/Pro and Enterprise |
| **Beta** | 50 | $14,450 | ~$8,661 | +$4,789 | Analytics dashboard live; self-serve onboarding; monitor full-cap Pro usage |
| **Growth** | 100 | $329,900 | ~$151,113 | +$178,787 | Enterprise custom pricing; provider volume discounts at $10K/month spend |
| **Scale** | 500 | $1,649,500 | ~$755,640 | +$893,860 | Enterprise contracts; Pro+ white-label `.exe`; negotiate provider deals |
| **Enterprise** | 2,000 | $9,608,000 | ~$4,377,538 | +$5,230,462 | Multi-region; 24/7 support operations; reserved capacity and priority provider tiers |

---

## What Companies Actually Get

It's worth being explicit about the value proposition so pricing feels justified.

**Without Conxa:**
- Build a custom MCP server from scratch
- Write and maintain Playwright automation scripts
- Handle selector drift when websites update
- Build telemetry and analytics from scratch
- Maintain installers for Windows and Mac
- Manage distribution and updates

**With Conxa:**
- Record workflows in a browser extension
- Download a signed `.exe` to distribute to customers
- See a dashboard showing who ran what, what succeeded, what failed, how often selectors drifted
- Push updates without customers reinstalling
- Self-healing recovery cascade built in (5 tiers, no custom code)
- Keep the plugin signed, trackable, updateable, and supported after the build-heavy first month
- Receive Conxa runtime/healing improvements without rebuilding the product from scratch

**At $199/month (Starter):** That's $2,388/year to ship and maintain a Claude-compatible product — less than a single day of engineering time. The first month covers heavy building; later months keep the plugin live with dashboard, signing, telemetry retention, support, updates, and healing/runtime improvements.

**At $499/month (Pro):** 10 plugins, 1,500 compilations, 1,500 plugin builds, 24/7 support, and white-label `.exe`. The tier is strong for real product teams, but full-cap usage is margin-sensitive and should be monitored before raising limits.

---

## Cost Levers

### Biggest Impact

**1. Caching is your biggest natural lever (already built)**  
Intent and vision anchor calls are cached by element hash (`intent_llm.py`, `anchor_vision_llm.py`). A Starter/Pro recompile where 3 steps changed costs ~$0.11, not ~$0.54. Companies iterating daily are still cheap, but the GPT-5.4-mini price floor means full-cap Pro usage must be watched.

**2. Usage naturally drops after launch**
Most companies spend the first month building and polishing the plugin, then move to 1–2 updates per month. This makes ongoing LLM cost much lower than the full-cap build-month model while subscription revenue continues for dashboard, signing, telemetry retention, support, update delivery, and Conxa healing/runtime updates.

**3. Trial plan costs Conxa almost nothing**
Free-tier providers (Groq + Google AI Studio + NVIDIA NIM) handle all Trial compilations at $0. This means Trial is a genuine no-cost acquisition tool, not a loss leader that bleeds money.

**4. Heuristic hit rate**
If a company's recorded app has clean `data-testid` or `aria-label` DOM, selector confidence = 1.0 and the 5 selector LLM calls skip (2 calls/step instead of 7). Cost drops ~60% per step. Not in Conxa's control, but adding a "DOM quality score" to the build report could nudge companies toward cleaner apps.

**5. Provider volume discounts at scale**
At $10K+/month provider spend (~500 companies), negotiate committed-use pricing for GPT-5.4-mini, GPT-5.4, Gemma 4 31B, and Claude Vision. Target 20–30% reduction = saves meaningful cost at Scale stage.

**6. Telemetry storage efficiency**
At Enterprise scale (300M events/month), aggregation is important. Roll up raw events into daily summaries after 7 days. Companies rarely need to query individual run-level data older than 1 week. Reduces storage cost by 70–80%.

**7. Update CDN costs**
Already negligible. Only matters if plugins become large (>100MB). Keep plugin packages data-only (no embedded browser binaries). Currently well-controlled.

---

## Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Compilation cost spikes (provider pricing changes) | $0.54 → $3.00/workflow compilation | Diversify providers; maintain free-tier rotation as buffer |
| Telemetry volume explodes unexpectedly | $500 → $5K/month infra cost | Implement event sampling (1-in-10 for healthy runs; 100% for failures) |
| Companies expect unlimited compilations on Starter | Margin erosion from compilation and Human Edit LLM cost | Enforce workflow compilation limits; bill overages after limit |
| Enterprise customers expect 15K GPT-5.4 + Claude Vision compilations for $2,999 | Enterprise contracts become negative margin | Price Enterprise by committed compilation allowance; start around a ~$30K/month floor for 15K included compilations |
| High churn because customers don't adopt .exe | Companies cancel (no ROI) | Instrument adoption rate; alert company when <20% customers installed |
| Concurrency spikes during compilation | Build queue backs up or providers return 429 | Async compilation with job queue (`/api/v1/jobs`); use OpenAI Tier 5/Reserved Capacity, Anthropic Priority/custom limits, and Together dedicated endpoints for burst windows |

---

## What to Measure

### Company Health (Track Weekly)
- Active companies (logged in past 7 days)
- New companies added
- Churned companies (cancelled or unpaid)
- Net Revenue Retention (NRR) — are existing companies upgrading or downgrading?

### Build Pipeline (Track Per-Build)
- Compilation success/failure rate
- LLM cost per build
- Build time (p50/p95)
- Selector confidence score (quality proxy)
- First-month vs maintenance-month compilation volume

### Plugin Adoption (Track Daily)
- Installs per plugin (how many customers installed the .exe)
- Active installs (ran at least once in last 7 days)
- Adoption rate = active installs / total installs
- Plugin age and update cadence (build-heavy launch month vs 1–2 updates/month maintenance mode)

### Telemetry Quality (Track Daily)
- Total runs reported
- Success rate (Tier 1 selector hit)
- Recovery rate (needed Tier 2–5)
- Unresolved failures (Tier 5 escalation)

### Infrastructure Cost (Track Monthly)
- Compilation LLM cost vs. forecast
- Telemetry ingestion cost vs. forecast
- Dashboard hosting vs. forecast
- Total cost as % of revenue by tier (watch Pro full-cap usage and Enterprise custom contracts)
- Maintenance-month margin after the initial build period

---

## Next Steps

### Week 1–2: Pricing & Billing
- [ ] Confirm final tier limits (3 plugins / 300 compilations / 300 plugin builds / 3 .exe for Starter)
- [ ] Create Stripe products: Trial (free), Starter ($199), Pro ($499), Enterprise (custom)
- [ ] Set Stripe price IDs in `.env` (`SKILL_STRIPE_PRICE_ID` per tier)
- [ ] Build tier enforcement in `app/services/saas.py`:
  - Track `compilation_count`, `build_count`, `exe_build_count` per workspace per billing period
  - Gate compile/build endpoints when limit reached → return `402` with upgrade prompt
  - Reset counters on billing period renewal (Stripe webhook)

### Week 3–4: Instrumentation & Dashboard
- [ ] Track per-compilation cost (LLM tokens × provider rate) and store in workspace usage
- [ ] Show companies their usage vs. limits in the dashboard (progress bars)
- [ ] Build usage alert: email company at 80% of any limit
- [ ] Test billing end-to-end (Trial → Starter → limit hit → upgrade → limits reset)

### Month 2: Validation
- [ ] Onboard 5–10 pilot companies on Trial tier
- [ ] Measure P50 actual compilations/month per company
- [ ] If P50 < 150 compilations, Starter limit of 300 is very comfortable → pricing confirmed
- [ ] If P50 > 240 compilations, consider raising Starter limit or dropping Pro threshold
- [ ] Collect feedback: do companies understand what "compilation" means in the UI?

### Ongoing
- [ ] Monthly: actual cost vs. forecast per tier (is ~$71–$80/Starter accurate at full included usage?)
- [ ] Quarterly: pricing review based on cohort usage data
- [ ] At 5,000 compilations/month: review provider volume discounts and burst-capacity tier upgrades

---

## Related Documents

- `docs/architecture.md` — Technical deep-dive (compilation pipeline, runtime, recovery cascade)
- `conxa-cloud/backend/ROUTER_SETUP.md` — Multi-provider LLM setup
- `CLAUDE.md` — Repository layout and deployment instructions

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-06-03 | Kiran | v8: Recalculated paid-plan compilation costs using current GPT-5.4-mini, GPT-5.4, Together AI Gemma 4 31B, and Claude Sonnet 4.6 pricing; added burst-capacity guidance for OpenAI tiers, Anthropic Priority/custom limits, and Together dedicated endpoints |
| 2026-06-03 | Kiran | v7: Updated paid provider pools to GPT-5.4-mini + Gemma 4 31B for Starter/Pro and GPT-5.4 + Claude Vision for Enterprise; matched plugin builds to workflow compilations; added Human Edit LLM costs, retention positioning, 24/7 support, and Pro+ white-label `.exe` |
| 2026-05-30 | Kiran | v6: Two-pool LLM strategy — Trial uses free-tier rotation, paid plans use two paid keys for high TPM burst; updated blended paid-plan cost (superseded) |
| 2026-05-30 | Kiran | v5: Compilations as hero metric; 300/Starter, 1,500/Pro; plugin count not the constraint (superseded) |
| 2026-05-30 | Kiran | v4: Real tier limits (3 plugins / 100 compilations / 30 builds / 3 .exe for Starter); corrected LLM calls to per-step not per-workflow (superseded) |
| 2026-05-30 | Kiran | v3: Corrected model — Conxa builds .exe, companies distribute, execution is on customer machines |
| 2026-05-30 | Kiran | v2: B2B marketplace model (superseded) |
| 2026-05-30 | Kiran | v1: Per-user SaaS model (superseded) |
