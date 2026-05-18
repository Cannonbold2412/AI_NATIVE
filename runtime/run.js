"use strict";
const fs   = require("fs");
const path = require("path");
const os   = require("os");

const CONXA_DIR = process.env.CONXA_DIR || path.join(os.homedir(), ".conxa");

// ─── Retry budget (L0) ────────────────────────────────────────────────────────

const _retryBudget     = new Map();
const RETRY_BUDGET_MAX = 5;

function checkRetryBudget(slug, stepIndex) {
  const key      = `${slug}:${stepIndex}`;
  const attempts = (_retryBudget.get(key) || 0) + 1;
  _retryBudget.set(key, attempts);
  if (attempts > RETRY_BUDGET_MAX) {
    appendRecoveryEvent({ event: "retry_budget_exhausted", slug, step_index: stepIndex });
    return false;
  }
  return true;
}

function clearRetryBudget(slug) {
  for (const key of _retryBudget.keys())
    if (key.startsWith(slug + ":")) _retryBudget.delete(key);
}

// ─── Recovery log (JSONL, 10 MB rotation) ────────────────────────────────────

const RECOVERY_LOG     = path.join(CONXA_DIR, "logs", "recovery.log");
const RECOVERY_LOG_MAX = 10 * 1024 * 1024;

function appendRecoveryEvent(event) {
  try {
    fs.mkdirSync(path.dirname(RECOVERY_LOG), { recursive: true });
    if (fs.existsSync(RECOVERY_LOG) && fs.statSync(RECOVERY_LOG).size > RECOVERY_LOG_MAX)
      fs.renameSync(RECOVERY_LOG, RECOVERY_LOG + ".1");
    fs.appendFileSync(RECOVERY_LOG, JSON.stringify({ ts: new Date().toISOString(), ...event }) + "\n");
  } catch (_) {}
}

// ─── Human-like pacing ────────────────────────────────────────────────────────
const HUMAN_DELAYS = {
  click:  [300, 500],
  fill:   [400, 700],
  type:   [400, 700],
  select: [350, 550],
  focus:  [200, 350],
  scroll: [300, 500],
};

function humanDelay(type) {
  const range = HUMAN_DELAYS[type];
  if (!range) return Promise.resolve();
  const ms = range[0] + Math.random() * (range[1] - range[0]);
  return new Promise(r => setTimeout(r, ms));
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function interpolate(value, inputs) {
  if (typeof value !== "string") return value;
  return value.replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (_, k) => String(inputs[k] ?? ""));
}

async function tryLocator(page, sel, timeout) {
  try { await page.locator(sel).waitFor({ state: "visible", timeout: timeout || 4000 }); return true; }
  catch (_) { return false; }
}

const URL_STATE_WAIT_MS = 2000;
const URL_STATE_POLL_MS = 100;

async function waitForUrlState(page, urlState) {
  if (!urlState || !urlState.url_pattern) return;
  const pattern  = new RegExp(urlState.url_pattern);
  const deadline = Date.now() + URL_STATE_WAIT_MS;
  let currentUrl = page.url();
  while (Date.now() <= deadline) {
    currentUrl = page.url();
    if (pattern.test(currentUrl)) return;
    await page.waitForTimeout(Math.min(URL_STATE_POLL_MS, Math.max(0, deadline - Date.now())));
  }
  throw new Error(`URL ${currentUrl} does not match expected pattern ${urlState.url_pattern}`);
}

// ─── Recovery embedding ───────────────────────────────────────────────────────

function enrichStepsWithRecovery(steps, recovery) {
  if (!Array.isArray(steps)) return steps;
  const recSteps = (recovery && Array.isArray(recovery.steps)) ? recovery.steps : [];
  return steps.map((step, idx) => {
    const rec = recSteps.find(r => Number(r && r.step_id) === idx + 1);
    if (!rec) return step;
    const sctx    = (rec.selector_context && typeof rec.selector_context === "object") ? rec.selector_context : {};
    const fallback = (rec.fallback && typeof rec.fallback === "object") ? rec.fallback : {};
    const textVariants = Array.isArray(fallback.text_variants)
      ? fallback.text_variants.filter(t => typeof t === "string" && t.trim()) : [];
    const recCandidates      = [sctx.primary, ...(Array.isArray(sctx.alternatives) ? sctx.alternatives : [])].filter(Boolean);
    const existingCandidates = Array.isArray(step.candidates) ? step.candidates : [];
    return {
      ...step,
      candidates: Array.from(new Set([...existingCandidates, ...recCandidates])),
      fallback_selectors: [
        ...(Array.isArray(step.fallback_selectors) ? step.fallback_selectors : []),
        ...textVariants.map(t => `text=${JSON.stringify(t.trim())}`),
      ],
      anchors:     Array.isArray(rec.anchors) ? rec.anchors.filter(a => a && typeof a.text === "string" && a.text.trim()) : [],
      _intent:     rec.intent     || "",
      _visual_ref: rec.visual_ref || "",
    };
  });
}

// ─── Step executor ────────────────────────────────────────────────────────────

async function executeStep(page, step, inputs) {
  const type = step.type;
  const raw  = step.selector || step.css_selector || (step.target && step.target.css) || "";
  const sel  = interpolate(raw, inputs);

  if (type === "wait")     { await page.waitForTimeout(Number(step.ms) || 1000); return; }
  if (type === "navigate") {
    await page.goto(interpolate(step.url || "", inputs), { timeout: 30000, waitUntil: "domcontentloaded" });
    return;
  }
  if (type === "scroll") {
    if (sel) await page.locator(sel).first().scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
    else     await page.evaluate(`window.scrollBy(${Number(step.delta_x) || 0}, ${Number(step.delta_y) || 0})`);
    await humanDelay("scroll");
    return;
  }
  if (type === "fill" || type === "type") {
    await page.locator(sel).first().fill(interpolate(step.value || "", inputs), { timeout: 15000 });
    await humanDelay(type);
    return;
  }
  if (type === "click") {
    try { await page.locator(sel).first().click({ timeout: 15000 }); await humanDelay("click"); return; }
    catch (err) {
      if (String(err).includes("intercepts pointer events")) {
        try { await page.locator(sel).last().click({ timeout: 10000 }); await humanDelay("click"); return; } catch (_) {}
      }
      throw err;
    }
  }
  if (type === "select") {
    await page.locator(sel).first().selectOption(interpolate(step.value || "", inputs), { timeout: 15000 });
    await humanDelay("select");
    return;
  }
  if (type === "focus") {
    if (sel) {
      try { await page.locator(sel).first().click({ timeout: 5000 }); }
      catch (_) { await page.locator(sel).first().focus({ timeout: 10000 }).catch(() => {}); }
    }
    await humanDelay("focus");
    return;
  }
  if (type === "check") {
    const pattern = interpolate(step.pattern || step.check_pattern || "", inputs);
    if (pattern && !new RegExp(pattern).test(page.url()))
      throw new Error(`URL check failed: ${page.url()} does not match ${pattern}`);
    return;
  }
}

// ─── runPlan — 5-layer recovery cascade ──────────────────────────────────────

async function runPlan(page, steps, inputs, startFrom, slug, { onStep, cancelCheck } = {}) {
  const INTERACTIVE = new Set(["click", "type", "fill", "focus", "select"]);

  for (let i = startFrom; i < steps.length; i++) {
    if (cancelCheck && cancelCheck()) throw Object.assign(new Error("Execution cancelled"), { cancelled: true });

    const step = steps[i];
    if (onStep) onStep(i);

    await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
    await page.waitForLoadState("networkidle",      { timeout: 3000 }).catch(() => {});

    const isInteractive = INTERACTIVE.has(step.type);
    const preShot = isInteractive
      ? await page.screenshot({ type: "png", timeout: 3000 }).catch(() => null)
      : null;

    const primarySel = interpolate(
      step.selector || step.css_selector || (step.target && step.target.css) || "", inputs
    );

    let primaryErr = null;
    try {
      if (step.url_state?.before?.url_pattern) await waitForUrlState(page, step.url_state.before);
      await executeStep(page, step, inputs);
      if (step.url_state?.after?.url_pattern)  await waitForUrlState(page, step.url_state.after);
      continue;
    } catch (e) { primaryErr = e; }

    let recovered = false;

    // L1: Transient retry
    try {
      await page.waitForTimeout(1500);
      if (primarySel && await tryLocator(page, primarySel, 3500)) {
        if (step.url_state?.before?.url_pattern) await waitForUrlState(page, step.url_state.before);
        await executeStep(page, step, inputs);
        if (step.url_state?.after?.url_pattern)  await waitForUrlState(page, step.url_state.after);
        recovered = true;
        appendRecoveryEvent({ event: "transient_recovered", slug, step_index: i });
      }
    } catch (_) {}

    // L2: Predefined alternatives
    if (!recovered) {
      const l2 = Array.from(new Set([
        ...(Array.isArray(step.candidates)         ? step.candidates         : []),
        ...(Array.isArray(step.fallback_selectors) ? step.fallback_selectors : []),
        ...(Array.isArray(step.fallback_text_variants)
          ? step.fallback_text_variants.map(t => `text=${JSON.stringify(String(t).trim())}`) : []),
        ...[step.value, step.label, step.aria_label]
          .filter(v => v && typeof v === "string" && v.length < 60)
          .map(v => `text=${JSON.stringify(v.trim())}`),
        ...(Array.isArray(step.anchors)
          ? step.anchors.filter(a => a && typeof a.text === "string" && a.text.trim())
                        .map(a => `text=${JSON.stringify(a.text.trim())}`) : []),
      ].filter(Boolean)));

      for (const cand of l2) {
        if (await tryLocator(page, cand, 3000)) {
          try {
            await executeStep(page, { ...step, selector: cand }, inputs);
            if (step.url_state?.after?.url_pattern) await waitForUrlState(page, step.url_state.after);
            recovered = true;
            appendRecoveryEvent({ event: "layer_recovered", layer: 2, slug, step_index: i, recovery_selector: cand });
            break;
          } catch (_) {}
        }
      }
    }

    // L3a: Dialog-scoped
    if (!recovered && step.type === "click" && primarySel) {
      for (const container of ['[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]', ".modal"]) {
        const scoped = `${container} ${primarySel}`;
        if (await tryLocator(page, scoped, 2000)) {
          try {
            await executeStep(page, { ...step, selector: scoped }, inputs);
            if (step.url_state?.after?.url_pattern) await waitForUrlState(page, step.url_state.after);
            recovered = true;
            appendRecoveryEvent({ event: "layer_recovered", layer: 3, slug, step_index: i, mode: "dialog" });
            break;
          } catch (_) {}
        }
        if (recovered) break;
      }
    }

    // L3b: Fuzzy tag+text DOM match
    if (!recovered) {
      const intent  = [step.value, step.label, step.aria_label, step._intent]
        .filter(v => v && typeof v === "string" && v.trim()).map(v => v.trim())[0];
      const tagMatch = primarySel.match(/^(button|a|input|select|textarea)/i);
      const tagHint  = tagMatch ? tagMatch[1].toLowerCase() : null;

      if (intent && tagHint) {
        try {
          const fuzzyIdx = await page.evaluate(([tag, needle]) => {
            const lneedle = needle.toLowerCase();
            return Array.from(document.querySelectorAll(tag)).findIndex(el => {
              const text = (el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().toLowerCase();
              return text && (text === lneedle || text.includes(lneedle) || lneedle.includes(text));
            });
          }, [tagHint, intent]);

          if (fuzzyIdx >= 0) {
            const fuzzySel = `${tagHint} >> nth=${fuzzyIdx}`;
            if (await tryLocator(page, fuzzySel, 2000)) {
              try {
                await executeStep(page, { ...step, selector: fuzzySel }, inputs);
                if (step.url_state?.after?.url_pattern) await waitForUrlState(page, step.url_state.after);
                recovered = true;
                appendRecoveryEvent({ event: "layer_recovered", layer: 3, slug, step_index: i, mode: "fuzzy" });
              } catch (_) {}
            }
          }
        } catch (_) {}
      }
    }

    if (!recovered) {
      const e = new Error(`Step ${i + 1} (${step.type}) failed: ${primaryErr.message}`);
      e.failedAt   = i;
      e.failedStep = step;
      e.preShot    = preShot;
      throw e;
    }
  }
}

module.exports = {
  appendRecoveryEvent,
  interpolate,
  tryLocator,
  waitForUrlState,
  enrichStepsWithRecovery,
  executeStep,
  runPlan,
  checkRetryBudget,
  clearRetryBudget,
};
