# Conxa — Sales Blockers & Implementation Roadmap

**Date:** 2026-06-02  
**Purpose:** Define what code must ship before Conxa can close its first enterprise customer.

---

## Executive Summary

The product works. Core features ship. **You can demonstrate to customers today.**

But you cannot ask them to **deploy to production** or **sign a contract** until certain operational/security items are finished. This doc separates:

1. **Blocking Gaps** — code that must be written before signing a customer
2. **Gating Items** — code that must be working before that customer goes live
3. **Nice-to-Have** — features that differentiate but don't block deals

---

## Phase 1 Status: Architecture Consolidation

**Current state:** 3/8 items done. 5 items remain.

| Item | Status | Blocks Sales? | Est. Days |
|---|---|---|---|
| ✅ 1.1 Auth token refresh fix | DONE | No | — |
| ✅ 1.2 Token acquisition flow | DONE (superseded) | No | — |
| ✅ Installer-provisioned sync token | DONE | No | — |
| 1.3 Move nonce store to Redis | Open | No* | 2 |
| 1.4 Real per-file delta sync | Open | No* | 3 |
| 1.5 Rate limit cache to Redis | Open | No* | 1 |
| 1.6 Wire RBAC to API routes | Open | **YES** | 3 |
| 1.7 Remove Stripe fields | Open | No | 0.5 |
| 1.8 Delete research/frontend/ | Open | No | 0.5 |

**Note:** Items marked with `*` don't block **first sales**, but will cause customer complaints in production (missed updates, rate-limited, in-memory state loss on redeploy). Must ship before customer goes live.

---

## Phase 2 Status: Production Readiness

**Current state:** 0/8 items done. These are **sales gates**.

| Item | Status | Blocks Sales? | Enterprise? | Est. Days |
|---|---|---|---|---|
| 2.1 Device & Runtime Registration | Open | **YES** | Yes | 5 |
| 2.2 Drift Detection | Open | No | Yes | 3 |
| 2.3 Audit Log | Open | **YES** | Yes | 4 |
| 2.4 macOS Runtime Support | Open | No | Upsell | 7 |
| 2.5 Installer Code Signing (Windows) | Open | **YES** | Yes | 3 |
| 2.6 Selector Cache GC | Open | No | Yes | 2 |
| 2.7 Hardened Billing Integration | Open | No | Yes | 5 |
| 2.8 Error Code UX Mapping | Open | No | All | 2 |

---

## The Actual Blockers

### Critical (Block Contract Signature)

#### 2.1 Device & Runtime Registration

**Why it matters:**  
Customers need to see what's deployed. "How many of our employees have this installed?" "Which version?" "Are they still using it?" Cloud has zero visibility — just returns "ok" and forgets.

**What's needed:**
- Runtime calls `POST /api/v1/telemetry/runtime-start` with `{runtime_version, companies[], platform}` at cold start.
- Cloud stores as a `runtime_registrations` record.
- Dashboard shows active count, version distribution, stale runtimes (>30 days).

**Business impact:** Without this, you cannot answer "How many installations do we have?" — kills enterprise POC reporting.

**Effort:** 5 days (backend + dashboard). Unblocked by Phase 1.

---

#### 2.3 Audit Log

**Why it matters:**  
Enterprise security team asks: "Who published this workflow? When? From where? What changed?"

**What's needed:**
- Write `audit_log` KV entries on: publish, installer upload, plugin delete.
- Fields: `user_id`, `workspace_id`, `action`, `resource_id`, `ts`, `ip`.
- Expose `GET /api/v1/audit/events` (Clerk-authed, owner/admin only).
- Dashboard page showing audit history.

**Business impact:** Enterprise will not proceed through procurement without this. "Audit log" is boilerplate in every security checklist.

**Effort:** 4 days (backend + UI). Unblocked by Phase 1.

---

#### 2.5 Installer Code Signing (Windows)

**Why it matters:**  
Unsigned `.exe` triggers Windows SmartScreen: "Unknown Publisher — Windows protected your PC." Users click "Run anyway" — but many enterprises block unsigned executables via GPO.

**What's needed:**
- Obtain Windows EV code signing cert (cost: ~$200/yr).
- Add `signtool.exe` step to `installer_builder.py` post-NSIS build.
- Env vars: `CONXA_SIGN_CERT_PATH`, `CONXA_SIGN_PASSWORD`.

**Business impact:** Without this, large enterprises cannot deploy to their fleet. SmartScreen block = dead on arrival.

**Effort:** 3 days (cert procurement + build integration). Unblocked by Phase 1.

---

#### 1.6 Wire RBAC to API Routes

**Why it matters:**  
Currently, any workspace member can publish, delete, upload anything. Compliance requirement: role enforcement.

**What's needed:**
- Add `require_role(principal, role)` FastAPI dependency to publish, delete, upload routes.
- Return HTTP 403 on mismatch.
- Default: publish requires `owner` or `admin`; read requires any member.

**Business impact:** "Who can publish?" is a basic access control question. No answer = security review fails.

**Effort:** 3 days (routing + testing). Depends on Phase 1.

---

### High Priority (Go-Live Gates)

These don't block the first demo/POC, but customer won't go live in production without them.

#### 1.3 Move Nonce Store to Redis

**Why it matters:**  
In-memory nonce dict is lost on deploy. If you redeploy during a CLI auth flow, that login breaks.

**Business impact:** Low-frequency customer issue during go-live.

**Effort:** 2 days.

---

#### 1.4 Real Per-File Delta Sync

**Why it matters:**  
Every skill pack sync downloads the entire pack, even if just one file changed. For a 20-skill plugin (2MB), cold start downloads 2MB on every update check.

**Business impact:** Poor UX on customer machines. Bandwidth overhead.

**Effort:** 3 days. Medium risk (backward compat required).

---

#### 1.5 Rate Limit Cache to Redis

**Why it matters:**  
Multi-instance cloud deployments (Render scaling) have independent rate limits. One instance can rate-limit while another accepts requests.

**Business impact:** Inconsistent rate limiting in production.

**Effort:** 1 day.

---

#### 2.2 Drift Detection

**Why it matters:**  
If the target app's UI changes dramatically, skills fail silently. Drift detection warns the user: "Page structure changed. You may need to recompile."

**Business impact:** Better UX. Fewer angry support tickets.

**Effort:** 3 days.

---

#### 2.6 Selector Cache GC

**Why it matters:**  
Compiled selector cache grows without bound. Eventually runs out of disk/memory.

**Business impact:** Data center ops issue (not customer-facing, but requires your intervention).

**Effort:** 2 days.

---

#### 2.7 Billing Enforcement

**Why it matters:**  
Free tier customers can currently publish unlimited skills. No quota enforcement.

**Business impact:** You need to know if this is a problem (test manually). Assume it needs fixing.

**Effort:** 5 days (define tiers + enforce).

---

### Optional (Ship Later, Upsell)

These are valuable but not required to close a deal.

- **2.4 macOS Support** — Upsell to Mac teams. Do after Windows launch.
- **2.8 Error Code UX** — Polish. Easy win, do late.
- **3.1 SSO/SAML** — Enterprise feature. Ship after you have 1–2 enterprise customers who ask for it.
- **3.2 Multi-User Publishing** — Team feature. Upsell to larger accounts.

---

## Path to First Sale

### Minimum Viable Sales Package (MVSP)

**Code that must ship to close the first enterprise deal:**

| Item | Phase | Effort | Timeline |
|---|---|---|---|
| 1.6 RBAC wired | 1 | 3d | **Critical Path** |
| 2.1 Device registration | 2 | 5d | **Critical Path** |
| 2.3 Audit log | 2 | 4d | **Critical Path** |
| 2.5 Code signing | 2 | 3d | **Critical Path** |
| 1.3 Nonce to Redis | 1 | 2d | Before go-live |
| 1.4 Delta sync | 1 | 3d | Before go-live |
| 1.5 Rate limit Redis | 1 | 1d | Before go-live |

**Total:** 15 days (critical path) + 6 days (before go-live) = **~3 weeks of engineering to signature**.

---

### Deployment Readiness Checklist

Before you ask a customer to sign:

- [ ] RBAC enforced on all write routes
- [ ] Audit log visible in dashboard (last 30 days)
- [ ] Windows `.exe` is code-signed (SmartScreen trusted)
- [ ] Device registration working (dashboard shows "active runtimes")
- [ ] Error messages are user-friendly (no raw codes)
- [ ] Nonce store survives cloud redeploy
- [ ] Rate limits consistent across cloud instances

---

## Revenue Impact

| Gap | Blocks... | Workaround | Cost |
|---|---|---|---|
| No audit log | Security review | Manual customer explanations | 4 hours per deal |
| No code signing | Enterprise GPO policy | Customer whitelists manually | Not viable at scale |
| No device registration | Usage reporting | Manual polling/screenshots | 2 hours per deal |
| No RBAC | Role enforcement | Trust model (risky) | Security review fails |

---

## Recommended Sequence

**Week 1:** 1.6 (RBAC) + 2.5 (code signing) — both enable the conversation legally/operationally.

**Week 2:** 2.1 (device reg) + 2.3 (audit log) — both required for enterprise contract.

**Week 3:** 1.3, 1.4, 1.5 (Redis items) — before first customer goes live.

This gets you to "first customer in production" in ~3 weeks. Parallel some Phase 2 items to save a week if your team is large enough.

---

## What to Sell Before This Is Done

- **Demos** — show the workflow working. No code signing needed for a demo.
- **POCs** — limited use on a dev machine. No audit log needed yet.
- **Evaluations** — Build Studio + Runtime working locally. Code signing helps but not critical.

**What you cannot sell:**
- Production fleet deployment (needs code signing + audit log + RBAC)
- Enterprise contracts with SLAs (needs device registration + audit)
- Billing tiers / multi-user workflows (comes later in Phase 3)
