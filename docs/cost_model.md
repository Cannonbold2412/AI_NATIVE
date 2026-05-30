# Conxa Cost & Revenue Model

**Last Updated:** May 30, 2026  
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
- Compilation LLM (one-time per plugin)
- Dashboard hosting (companies checking analytics)
- Telemetry ingestion (from customer machines worldwide)
- Plugin update sync (when company ships an update, customers pull it)

**What Conxa does NOT pay for:**
- Execution (runs on customer's machine)
- LLM recovery during execution (customer's Claude Desktop subscription)
- Customer infrastructure of any kind

---

## Cost Structure

### 1. Plugin Compilation (One-Time Per Plugin Build)

Every time a company records workflows and compiles them into a new plugin version, Conxa runs LLM calls per step to generate selectors, anchors, and intent.

#### LLM Calls Per Step

| Call | Prompt size | When | Count/step |
|------|-------------|------|------------|
| **Intent detection** (`generate_intent_with_llm`) | ~200 input tokens (6 text fields) | Every step — but **cached** by element hash | 1 (0 on cache hit) |
| **Vision anchor generation** (`generate_anchors_for_step_or_raise`) | ~10–20K tokens (screenshot JPEG as base64 + prompt) | Every step — but **cached** by screenshot hash | 1 (0 on cache hit) |
| **Selector self-consistency** (`generate_selector_candidates`, `num_samples=5`) | ~3K input + ~500 output per call | Only if heuristic selector confidence < 1.0 | 5 (0 on perfect heuristic) |

**Best case (heuristic hits — clean `data-testid` or `aria-label`):** 2 calls/step  
**Typical case (LLM selectors needed):** 7 calls/step  
**Recompilation (same DOM, cached):** 0–2 calls/step — caching absorbs most of the cost

#### Corrected Cost Per Workflow Compilation

#### LLM Provider Strategy — Two Separate Pools

**Trial plan and paid plans use completely different LLM providers.**

| Plan | Provider Pool | Rationale |
|------|--------------|-----------|
| **Trial (free)** | Groq + Google AI Studio + NVIDIA NIM (free-tier key rotation) | Zero LLM cost; rate limits acceptable at low volume |
| **Starter / Pro / Enterprise** | **2 paid keys only: OpenAI (GPT-4o-mini) + Anthropic (Claude Haiku)** | High TPM burst when compilations happen; no rate-limit queuing |

**Why only 2 keys for paid plans:**  
Companies compile in bursts — not a constant drip all day. When someone hits compile, the job should finish in seconds. Free-tier providers have tight rate limits (30 req/min on Groq) that cause queuing under burst load.

- **OpenAI Tier 2**: 2M TPM on GPT-4o-mini — handles 100 concurrent compilations without breaking a sweat
- **Anthropic Tier 2**: 400K TPM on Claude Haiku — fast text fallback

Paid plans get GPT-4o-mini for vision anchors + selectors, Claude Haiku for intent. Two keys, no pool juggling, high reliability.

**How it routes in the existing code:**  
`router.py` builds a `PoolEntry` per key. The Build Studio backend reads the workspace billing tier from the cloud API and passes `paid_tier=True` to select the appropriate pool at compile time. No router rewrite needed — just two separate pool configs loaded from env.

---

#### Cost Per Compilation by Plan

**Trial plan (free-tier providers):**

Token costs at Groq (text) + Google AI Studio (vision):
- Intent: ~200 tokens → **~$0.00001** (negligible)
- Vision anchor: ~15K tokens at $0.075/1M → **~$0.001/step**
- Selectors × 5: ~3K input + 500 output each → **~$0.001/step**
- **Total/step: ~$0.002 | Per compilation (15 steps): ~$0.03**

**Paid plans (GPT-4o-mini + Claude Haiku):**

- Intent (Claude Haiku, 200 tokens): **~$0.00016/step**
- Vision anchor (GPT-4o-mini vision, 15K tokens): **~$0.00225/step**
- Selectors × 5 (GPT-4o-mini text): **~$0.00375/step**
- **Total/step: ~$0.006 | Per compilation (15 steps): ~$0.09**

| Scenario | Trial cost | Paid plan cost |
|----------|------------|---------------|
| Short workflow (5 steps) | ~$0.01 | ~$0.03 |
| Medium workflow (15 steps) | ~$0.03 | **~$0.09** |
| Long workflow (30 steps) | ~$0.06 | ~$0.18 |
| Recompilation (cached, 3 changed steps) | ~$0.003 | **~$0.018** |
| **Blended (80% recompiles, 15 steps avg)** | **~$0.008** | **~$0.033** |

**Key insight on continuous iteration:** Both intent and vision anchor calls are cached by element hash (`intent_llm.py`, `anchor_vision_llm.py`). Recompiling a workflow where only 2–3 steps changed fires LLM only for those steps — the rest are cache hits. This makes daily iteration cheap regardless of provider.

**Example — Company on Starter (paid plan), 1 plugin, 50 workflows:**
- Initial build: 50 × $0.09 = **$4.50 one-time**
- Monthly iteration (recompile 10 workflows × 3 times, 3 changed steps): 30 compilations × $0.018 = **$0.54/month**
- Total monthly LLM cost for this company: **~$0.54** (vs $0.18 on free-tier) — still negligible

| Component | Trial plan | Paid plans |
|-----------|------------|-----------|
| LLM per compilation (first build) | ~$0.03 | ~$0.09 |
| LLM per recompilation (cached) | ~$0.003 | ~$0.018 |
| Build infrastructure | $0.10 | $0.10 |
| **Blended per compilation** | **~$0.008** | **~$0.033** |

---

### 2. Dashboard Hosting (Monthly Fixed)

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

### 3. Telemetry Ingestion (Scales With Customer Base)

Every time a customer runs a workflow anywhere in the world, a telemetry event flows back to Conxa. This is where costs actually scale — not with companies, but with the combined size of all their customer bases.

**Telemetry payload per execution:** ~1–2KB (run ID, plugin ID, step outcomes, recovery tiers reached, timestamps)

| Scale | Companies | Avg Customers/Company | Daily Runs | Monthly Telemetry Events | Ingestion Cost |
|-------|-----------|----------------------|------------|--------------------------|---------------|
| MVP | 10 | 100 | 1,000 | 30K | $5 |
| Growth | 100 | 500 | 50,000 | 1.5M | $50 |
| Scale | 500 | 2,000 | 1,000,000 | 30M | $500 |
| Enterprise | 2,000 | 5,000 | 10,000,000 | 300M | $3,000 |

**Telemetry stack:** Events hit the `/api/v1/tracking` endpoint → write to append-only log → aggregate into analytics tables daily. No real-time processing needed; companies are fine seeing yesterday's data.

---

### 4. Plugin Update Sync (Per Update Release)

When a company ships a plugin update, customers pull the new version. The `/skill-packs/*` endpoint serves the updated plugin package.

| Component | Cost | Notes |
|-----------|------|-------|
| Storage per plugin version | ~$0.01/GB | Compiled plugin packages are small (~5–50MB) |
| CDN bandwidth per update rollout | ~$0.01/GB | 100 customers × 10MB = 1GB = $0.01 |
| **Total per update** | **~$0.02–0.10** | Negligible |

---

### Total Monthly Operating Cost

Assumes typical plugin: 10 workflows × 15 steps × mostly LLM selectors = **$4.20/plugin build**.

| Scale | Companies | Builds/Month | Compilation | Dashboard | Telemetry | Updates | **Total/Month** |
|-------|-----------|--------------|-------------|-----------|-----------|---------|-----------------|
| MVP | 10 | 20 | $84 | $35 | $5 | $2 | **$126** |
| Growth | 100 | 200 | $840 | $80 | $50 | $20 | **$990** |
| Scale | 500 | 1,000 | $4,200 | $230 | $500 | $100 | **$5,030** |
| Enterprise | 2,000 | 5,000 | $21,000 | $700 | $3,000 | $400 | **$25,100** |

**Cost lever:** Increasing heuristic hit rate (better `data-testid` coverage guidance to companies) reduces compilation cost by up to 70% (7 calls/step → 2 calls/step on clean DOM).

---

## Revenue Model

Companies pay Conxa to **build and maintain** their Claude-compatible plugin. They think about it the same way they think about their mobile app on the App Store — there's a platform fee to be listed and maintained, not a per-download fee.

### Tier Design Principles

**What companies actually look like:**
- They build **1–3 plugins** — each plugin IS their product (e.g. "Gmail Automation for SalesForce users")
- Each plugin contains **many workflows** (10–100) covering different user tasks
- They **iterate continuously** — recording fixes, step adjustments, selector updates happen daily
- Plugin count is not a meaningful constraint. Compilation volume is everything.

**The right axis to charge on: workflow compilations per month.**

---

### Pricing Tiers

**Limit definitions:**
- **Plugins** — distinct products hosted on Conxa (kept high; not the real constraint)
- **Workflow compilations/month** — each time a recorded workflow runs through the compile pipeline (the cost driver; includes recompilations)
- **Plugin builds/month** — packaging compiled workflows into a distributable artifact
- **.exe builds/month** — generating the installer binary (Windows/Mac)

| | **Trial** | **Starter** | **Pro** | **Enterprise** |
|--|-----------|-------------|---------|----------------|
| **Price** | $0 / 14 days | $199/mo | $499/mo | Custom |
| **Plugins** | 1 | 3 | 10 | Unlimited |
| **Workflow compilations/mo** | 30 | 300 | 1,500 | Unlimited |
| **Plugin builds/mo** | 3 | 30 | 150 | Unlimited |
| **.exe builds/mo** | 1 | 3 | 15 | Unlimited |
| **Analytics retention** | 7 days | 90 days | 1 year | Custom |
| **Team seats** | 1 | 3 | 10 | Unlimited |
| **Support** | None | Email (48h) | Priority (24h) | Dedicated SLA |
| **White-label .exe** | No | No | No | Yes |

**Why 300 compilations for Starter:**  
A company with 1 plugin × 50 workflows = 50 initial compilations. Active iteration (recompiling updated workflows daily) = ~5–10 recompilations/day = 150–300/month. 300 is comfortable for an actively developing team without being wasteful.

Importantly: **recompilations are ~10× cheaper than initial builds** because intent and vision anchor results are cached by hash. 300 recompilations ≈ 30 equivalent "fresh" builds in LLM cost.

**Why 1,500 for Pro:**  
A company with 3 plugins × 100 workflows each, iterating across multiple workflows daily. Enough room for full-scale product development.

*Overage pricing (add later when data exists):* ~$0.10 per extra compilation, $1 per extra plugin build, $5 per extra `.exe` build.

---

### Cost Per Tier (What Conxa Spends)

Using corrected LLM costs: ~$0.03/first compilation, ~$0.003/recompilation. Assume 80% of monthly compilations are recompilations.

| | **Trial** | **Starter** | **Pro** | **Enterprise (est.)** |
|--|-----------|-------------|---------|----------------------|
| LLM provider | Free-tier rotation | GPT-4o-mini + Claude Haiku | GPT-4o-mini + Claude Haiku | GPT-4o-mini + Claude Haiku |
| Compilations cost (blended) | 30 × $0.008 = $0.24 | 300 × $0.033 = **$9.90** | 1,500 × $0.033 = **$49.50** | 15,000 × $0.033 = **$495** |
| Plugin builds (~$0.10 each) | $0.30 | $3 | $15 | $500 |
| .exe builds (~$0.50 each) | $0.50 | $1.50 | $7.50 | $150 |
| Dashboard + telemetry share | $2 | $5 | $10 | $200 |
| **Total cost/company/month** | **~$3** | **~$19** | **~$82** | **~$1,345** |
| **Revenue** | $0 | **$199** | **$499** | **~$3,000+** |
| **Gross Margin** | — | **90.5%** | **83.6%** | **55%+** |

**Blended compilation cost (paid plans)** = (20% fresh × $0.09) + (80% cached × $0.018) = $0.033/compilation.  
**Blended compilation cost (free tier)** = (20% fresh × $0.03) + (80% cached × $0.003) = $0.008/compilation.

---

## Unit Economics

### Scenario A: MVP (10 Companies)
Mix: 7 Starter × $199, 3 Pro × $499

| | Value |
|-|-------|
| **Monthly Revenue** | (7 × $199) + (3 × $499) = **$2,890** |
| Compilation LLM (paid providers) | $133 (7×$9.90 + 3×$49.50) |
| Infrastructure | $126 |
| **Total Cost** | **$259** |
| **Gross Margin** | **91%** |
| **Monthly Profit** | **+$2,631** |

**Break-even:** 2 paying companies covers all costs.

---

### Scenario B: Growth (100 Companies)
Mix: 50 Starter, 40 Pro, 10 Enterprise × $2,999

| | Value |
|-|-------|
| **Monthly Revenue** | (50��$199) + (40×$499) + (10×$2,999) = **$59,930** |
| Compilation LLM | $2,475 (50×$9.90 + 40×$49.50 + 10×$495) |
| Infrastructure | $990 |
| **Total Cost** | **$3,465** |
| **Gross Margin** | **94.2%** |
| **Monthly Profit** | **+$56,465** (~$677K/year) |

---

### Scenario C: Scale (500 Companies)
Mix: 250 Starter, 200 Pro, 50 Enterprise × $2,999

| | Value |
|-|-------|
| **Monthly Revenue** | (250×$199) + (200×$499) + (50×$2,999) = **$299,650** |
| Compilation LLM | $12,375 |
| Infrastructure | $5,030 |
| **Total Cost** | **$17,405** |
| **Gross Margin** | **94.2%** |
| **Monthly Profit** | **+$282,245** (~$3.4M/year) |

---

### Scenario D: Enterprise (2,000 Companies)
Mix: 800 Starter, 900 Pro, 300 Enterprise × $2,999

| | Value |
|-|-------|
| **Monthly Revenue** | (800×$199) + (900×$499) + (300×$2,999) = **$1,208,300** |
| Compilation LLM | $49,500 |
| Infrastructure | $25,100 |
| **Total Cost** | **$74,600** |
| **Gross Margin** | **93.8%** |
| **Monthly Profit** | **+$1,133,700** (~$13.6M/year) |

---

## Growth Milestones

| Milestone | Companies | Monthly Revenue | Monthly Cost | Profit | Key Actions |
|-----------|-----------|-----------------|--------------|--------|-------------|
| **MVP live** | 10 | $2,890 | $259 | +$2,631 | Ship billing; wire paid LLM pool (2 keys) for paid plans |
| **Beta** | 50 | $14,450 | $1,100 | +$13,350 | Analytics dashboard live; self-serve onboarding |
| **Growth** | 100 | $59,930 | $3,465 | +$56,465 | Overage billing; OpenAI volume discount at $10K/month spend |
| **Scale** | 500 | $299,650 | $17,405 | +$282,245 | Enterprise contracts; white-label `.exe`; negotiate Anthropic deal |
| **Enterprise** | 2,000 | $1,208,300 | $74,600 | +$1,133,700 | Multi-region; dedicated support; negotiate bulk LLM pricing |

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

**At $199/month (Starter):** That's $2,388/year to ship and maintain a Claude-compatible product — less than a single day of engineering time. Justifiable at first customer.

**At $499/month (Pro):** 10 plugins, 500 compilations, dedicated support. Less than a junior developer's daily rate. The right tier for any company with real paying customers using the plugin.

---

## Cost Levers

### Biggest Impact

**1. Caching is your biggest natural lever (already built)**  
Intent and vision anchor calls are cached by element hash (`intent_llm.py`, `anchor_vision_llm.py`). A recompile where 3 steps changed costs ~$0.054 (3 steps × $0.018), not $0.09. Companies iterating daily are cheap — 300 recompiles/month with good cache hit rate costs ~$5, not $9.90.

**2. Trial plan costs Conxa almost nothing**  
Free-tier providers (Groq + Google AI Studio + NVIDIA NIM) handle all Trial compilations at $0. This means Trial is a genuine no-cost acquisition tool, not a loss leader that bleeds money.

**3. Heuristic hit rate**  
If a company's recorded app has clean `data-testid` or `aria-label` DOM, selector confidence = 1.0 and the 5 selector LLM calls skip (2 calls/step instead of 7). Cost drops ~60% per step. Not in Conxa's control, but adding a "DOM quality score" to the build report could nudge companies toward cleaner apps.

**4. OpenAI/Anthropic volume discounts at scale**  
At $10K+/month OpenAI spend (~500 companies), negotiate committed-use pricing. Target 20–30% reduction = saves ~$10K/month at Scale stage. Similar deal available with Anthropic.

**2. Telemetry storage efficiency**  
At Enterprise scale (300M events/month), aggregation is important. Roll up raw events into daily summaries after 7 days. Companies rarely need to query individual run-level data older than 1 week. Reduces storage cost by 70–80%.

**3. Update CDN costs**  
Already negligible. Only matters if plugins become large (>100MB). Keep plugin packages data-only (no embedded browser binaries). Currently well-controlled.

---

## Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Compilation cost spikes (provider pricing changes) | $0.80 → $3.00/build | Diversify providers; maintain free-tier rotation as buffer |
| Telemetry volume explodes unexpectedly | $500 → $5K/month infra cost | Implement event sampling (1-in-10 for healthy runs; 100% for failures) |
| Companies expect unlimited builds on Starter | Margin erosion from compilation cost | Enforce tier limits; bill overages at $2/build after limit |
| High churn because customers don't adopt .exe | Companies cancel (no ROI) | Instrument adoption rate; alert company when <20% customers installed |
| Concurrency spikes during compilation | Build queue backs up | Async compilation with job queue (`/api/v1/jobs`); already scaffolded |

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

### Plugin Adoption (Track Daily)
- Installs per plugin (how many customers installed the .exe)
- Active installs (ran at least once in last 7 days)
- Adoption rate = active installs / total installs

### Telemetry Quality (Track Daily)
- Total runs reported
- Success rate (Tier 1 selector hit)
- Recovery rate (needed Tier 2–5)
- Unresolved failures (Tier 5 escalation)

### Infrastructure Cost (Track Monthly)
- Compilation LLM cost vs. forecast
- Telemetry ingestion cost vs. forecast
- Dashboard hosting vs. forecast
- Total cost as % of revenue (should stay under 2%)

---

## Next Steps

### Week 1–2: Pricing & Billing
- [ ] Confirm final tier limits (3 plugins / 100 compilations / 30 builds / 3 .exe for Starter)
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
- [ ] If P50 < 40 compilations, Starter limit of 100 is very comfortable → pricing confirmed
- [ ] If P50 > 80 compilations, consider raising Starter limit or dropping Pro threshold
- [ ] Collect feedback: do companies understand what "compilation" means in the UI?

### Ongoing
- [ ] Monthly: actual cost vs. forecast per tier (is $42/Starter accurate?)
- [ ] Quarterly: pricing review based on cohort usage data
- [ ] At 5,000 compilations/month: open Groq volume discount negotiation

---

## Related Documents

- `docs/architecture.md` — Technical deep-dive (compilation pipeline, runtime, recovery cascade)
- `conxa-cloud/backend/ROUTER_SETUP.md` — Multi-provider LLM setup
- `CLAUDE.md` — Repository layout and deployment instructions

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-05-30 | Kiran | v6: Two-pool LLM strategy — Trial uses free-tier rotation, paid plans use 2 keys only (GPT-4o-mini + Claude Haiku) for high TPM burst; updated cost to $0.033/compilation for paid plans |
| 2026-05-30 | Kiran | v5: Compilations as hero metric; 300/Starter, 1,500/Pro; plugin count not the constraint (superseded) |
| 2026-05-30 | Kiran | v4: Real tier limits (3 plugins / 100 compilations / 30 builds / 3 .exe for Starter); corrected LLM calls to per-step not per-workflow (superseded) |
| 2026-05-30 | Kiran | v3: Corrected model — Conxa builds .exe, companies distribute, execution is on customer machines |
| 2026-05-30 | Kiran | v2: B2B marketplace model (superseded) |
| 2026-05-30 | Kiran | v1: Per-user SaaS model (superseded) |
