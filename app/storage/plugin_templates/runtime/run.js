"use strict";
const fs   = require("fs");
const path = require("path");
const { CONXA_HOME } = require("./config");

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

const RECOVERY_LOG     = path.join(CONXA_HOME, "recovery.log");
const RECOVERY_LOG_MAX = 10 * 1024 * 1024;

function appendRecoveryEvent(event) {
  try {
    if (fs.existsSync(RECOVERY_LOG) && fs.statSync(RECOVERY_LOG).size > RECOVERY_LOG_MAX)
      fs.renameSync(RECOVERY_LOG, RECOVERY_LOG + ".1");
    fs.appendFileSync(RECOVERY_LOG, JSON.stringify({ ts: new Date().toISOString(), ...event }) + "\n");
  } catch (_) {}
}

// ─── Adaptive timing (replaces fixed waitForTimeout calls) ───────────────────
// Waits for the page to be stable by watching: network activity, DOM mutations,
// and readyState — no arbitrary fixed sleeps.

async function waitForStable(page, options) {
  const { timeout = 5000, networkIdle = false } = options || {};
  try {
    await page.waitForLoadState("domcontentloaded", { timeout: Math.min(timeout, 3000) });
  } catch (_) {}
  if (networkIdle) {
    try {
      await page.waitForLoadState("networkidle", { timeout: Math.min(timeout, 4000) });
    } catch (_) {}
  } else {
    // Lightweight DOM-settle: poll readyState and wait for a quiet mutation window
    try {
      await page.waitForFunction(
        () => document.readyState === "complete",
        { timeout: Math.min(timeout, 2000) }
      );
    } catch (_) {}
  }
}

// ─── Human-like pacing (unchanged — matches real operator cadence) ────────────
const HUMAN_DELAYS = {
  click:       [300, 500],
  fill:        [400, 700],
  type:        [400, 700],
  date_pick:   [400, 700],
  select:      [350, 550],
  select_option:[350, 550],
  focus:       [200, 350],
  scroll:      [300, 500],
  hover:       [200, 350],
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

function frameChain(step) {
  const frame = step && step.frame && typeof step.frame === "object" ? step.frame : {};
  return Array.isArray(frame.chain) ? frame.chain.filter(f => f && typeof f === "object") : [];
}

function frameSelectors(spec, inputs) {
  return Array.from(new Set([
    spec.selector,
    ...(Array.isArray(spec.fallback_selectors) ? spec.fallback_selectors : []),
  ].map(s => interpolate(String(s || ""), inputs)).filter(Boolean)));
}

function rootCandidates(page, step, inputs) {
  const chain = frameChain(step);
  if (!chain.length) return [page];
  let roots = [page];
  for (const spec of chain) {
    const selectors = frameSelectors(spec, inputs);
    const next = [];
    for (const root of roots) {
      for (const selector of selectors) {
        if (root && typeof root.frameLocator === "function") {
          next.push(root.frameLocator(selector));
        }
      }
    }
    if (next.length === 0) {
      appendRecoveryEvent({ event: "frame_not_found", selector: spec.selector,
                            fallbacks: spec.fallback_selectors });
    }
    roots = next;
    if (!roots.length) break;
  }
  return roots.length ? roots : [page];
}

function locatorCandidates(page, step, inputs, selector) {
  const sel = interpolate(selector || "", inputs);
  if (!sel) return [];
  return rootCandidates(page, step, inputs).map(root => root.locator(sel));
}

async function withLocator(page, step, inputs, selector, timeout, fn) {
  const candidates = locatorCandidates(page, step, inputs, selector);
  if (!candidates.length) throw new Error("Missing selector");
  let lastErr = null;
  for (const loc of candidates) {
    try {
      if (timeout) await loc.first().waitFor({ state: "visible", timeout });
      return await fn(loc);
    } catch (err) {
      lastErr = err;
    }
  }
  if (frameChain(step).length > 0) {
    appendRecoveryEvent({ event: "frame_context_failed", selector,
                          frame_depth: frameChain(step).length, error: String(lastErr) });
  }
  throw lastErr || new Error(`Locator not found: ${selector}`);
}

async function withLocatorPair(page, step, inputs, srcSelector, dstSelector, timeout, fn) {
  const src = interpolate(srcSelector || "", inputs);
  const dst = interpolate(dstSelector || "", inputs);
  if (!src || !dst) throw new Error("Missing selector");
  let lastErr = null;
  for (const root of rootCandidates(page, step, inputs)) {
    try {
      const srcLoc = root.locator(src);
      const dstLoc = root.locator(dst);
      if (timeout) {
        await srcLoc.first().waitFor({ state: "visible", timeout });
        await dstLoc.first().waitFor({ state: "visible", timeout });
      }
      return await fn(srcLoc, dstLoc);
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error(`Locator pair not found: ${src} -> ${dst}`);
}

async function locatorEvaluateAll(page, step, inputs, selector, arg, fn) {
  let lastErr = null;
  for (const loc of locatorCandidates(page, step, inputs, selector)) {
    try {
      return await loc.evaluateAll(fn, arg);
    } catch (err) {
      lastErr = err;
    }
  }
  if (lastErr) throw lastErr;
  return -1;
}

async function tryLocator(page, sel, timeout, step = {}, inputs = {}) {
  try {
    await withLocator(page, step, inputs, sel, timeout || 4000, async loc => loc.first());
    return true;
  } catch (_) {
    return false;
  }
}

const URL_STATE_WAIT_MS = 3000;
const URL_STATE_POLL_MS = 100;

async function waitForUrlState(page, urlState) {
  if (!urlState || !urlState.url_pattern) return;
  const pattern  = new RegExp(urlState.url_pattern);
  const deadline = Date.now() + URL_STATE_WAIT_MS;
  let currentUrl = page.url();
  while (Date.now() <= deadline) {
    currentUrl = page.url();
    if (pattern.test(currentUrl)) return;
    await new Promise(r => setTimeout(r, Math.min(URL_STATE_POLL_MS, Math.max(0, deadline - Date.now()))));
  }
  throw new Error(`URL ${currentUrl} does not match expected pattern ${urlState.url_pattern}`);
}

// ─── Fingerprint-based element scoring ───────────────────────────────────────
// Scores a DOM element against the recorded ElementFingerprint.
// Returns 0.0 (no match) to 1.0 (perfect match). Score >= 0.5 is usable.

const FINGERPRINT_SCORE_THRESHOLD = 0.45;

async function scoreElementAgainstFingerprint(page, selector, step, inputs, fp) {
  if (!fp || typeof fp !== "object") return 0;
  try {
    const scores = await page.evaluate(([sel, fingerprint]) => {
      let el;
      try { el = document.querySelector(sel); } catch (_) { return 0; }
      if (!el) return 0;

      const tag        = (el.tagName || "").toLowerCase();
      const role       = (el.getAttribute("role") || tag).toLowerCase();
      const ariaLabel  = (el.getAttribute("aria-label") || "").trim().toLowerCase();
      const name       = (el.getAttribute("name") || "").trim().toLowerCase();
      const placeholder= (el.getAttribute("placeholder") || "").trim().toLowerCase();
      const testId     = el.getAttribute("data-testid") || el.getAttribute("data-test") || "";
      const inputType  = (el.getAttribute("type") || "").toLowerCase();
      const innerText  = ((el.innerText || el.textContent || "").trim().slice(0, 120)).toLowerCase();

      let score = 0;
      // data-testid exact match is the most reliable signal
      if (fingerprint.data_testid && testId && fingerprint.data_testid === testId) score += 0.95;
      // aria-label exact match
      if (fingerprint.aria_label && ariaLabel && fingerprint.aria_label.toLowerCase() === ariaLabel) score += 0.80;
      // name attribute
      if (fingerprint.name && name && fingerprint.name.toLowerCase() === name) score += 0.65;
      // placeholder
      if (fingerprint.placeholder && placeholder && fingerprint.placeholder.toLowerCase() === placeholder) score += 0.60;
      // inner_text exact
      if (fingerprint.inner_text && innerText) {
        const fpText = fingerprint.inner_text.toLowerCase();
        if (fpText === innerText) score += 0.75;
        else if (innerText.includes(fpText) || fpText.includes(innerText)) score += 0.45;
      }
      // role + tag
      if (fingerprint.role && role && fingerprint.role.toLowerCase() === role) score += 0.25;
      if (fingerprint.tag && tag && fingerprint.tag.toLowerCase() === tag) score += 0.15;
      // input_type
      if (fingerprint.input_type && inputType && fingerprint.input_type.toLowerCase() === inputType) score += 0.20;

      return Math.min(1.0, score);
    }, [interpolate(selector, inputs), fp]);
    return typeof scores === "number" ? scores : 0;
  } catch (_) {
    return 0;
  }
}

// ─── Scoring-based element resolver ──────────────────────────────────────────
// Collects all candidate selectors, scores each against the fingerprint,
// and returns the best match above threshold — no arbitrary sequential fallback.

async function resolveElement(page, step, inputs) {
  const fp = step.element_fingerprint || {};
  const primarySel = interpolate(
    step.selector || step.css_selector || (step.target && step.target.css) || "", inputs
  );

  // 1. Try primary selector with a short visibility check
  if (primarySel) {
    if (await tryLocator(page, primarySel, 2000, step, inputs)) {
      return { selector: primarySel, via: "primary", score: 1.0 };
    }
  }

  // 2. Build candidate pool from all compiled selectors
  const pool = Array.from(new Set([
    ...(Array.isArray(step.fallback_selectors) ? step.fallback_selectors : []),
    ...(Array.isArray(step.candidates) ? step.candidates : []),
    ...(Array.isArray(step.fallback_text_variants)
      ? step.fallback_text_variants.map(t => `text=${JSON.stringify(String(t).trim())}`) : []),
    // Anchor text selectors
    ...(Array.isArray(step.anchors)
      ? step.anchors
          .filter(a => a && typeof a.text === "string" && a.text.trim())
          .map(a => `text=${JSON.stringify(a.text.trim())}`) : []),
    // Value/label/aria text selectors
    ...[step.value, step.label, step.aria_label]
      .filter(v => v && typeof v === "string" && v.length < 80)
      .map(v => `text=${JSON.stringify(v.trim())}`),
    // Fingerprint-derived stable selectors
    ...(fp.data_testid ? [`[data-testid="${fp.data_testid}"]`, `[data-test="${fp.data_testid}"]`] : []),
    ...(fp.aria_label  ? [`[aria-label="${fp.aria_label}"]`] : []),
    ...(fp.name        ? [`[name="${fp.name}"]`] : []),
    ...(fp.placeholder ? [`[placeholder="${fp.placeholder}"]`] : []),
  ].filter(Boolean)));

  if (!pool.length) return null;

  // 3. Score all candidates in parallel against fingerprint
  const scored = await Promise.all(pool.map(async sel => {
    const visible = await tryLocator(page, sel, 1500, step, inputs);
    if (!visible) return { selector: sel, score: 0 };
    const score = await scoreElementAgainstFingerprint(page, sel, step, inputs, fp);
    return { selector: sel, score };
  }));

  // 4. Pick highest-scoring candidate
  scored.sort((a, b) => b.score - a.score);
  const best = scored[0];
  if (best && best.score >= FINGERPRINT_SCORE_THRESHOLD) {
    return { selector: best.selector, via: "fingerprint_scored", score: best.score };
  }

  // 5. Dialog-scoped: click steps may target content inside a modal
  if (step.type === "click" && primarySel) {
    for (const container of ['[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]', ".modal"]) {
      const scoped = `${container} ${primarySel}`;
      if (await tryLocator(page, scoped, 1500, step, inputs)) {
        return { selector: scoped, via: "dialog_scoped", score: 0.5 };
      }
    }
  }

  // 6. Fuzzy tag+text DOM scan (last resort before LLM)
  const intent = [step.value, step.label, step.aria_label, step._intent, fp && fp.inner_text]
    .filter(v => v && typeof v === "string" && v.trim()).map(v => v.trim())[0];
  const tagHint = primarySel && primarySel.match(/^(button|a|input|select|textarea)/i)
    ? primarySel.match(/^(button|a|input|select|textarea)/i)[1].toLowerCase()
    : (fp && fp.tag ? fp.tag : null);

  if (intent && tagHint) {
    try {
      const fuzzyIdx = await locatorEvaluateAll(page, step, inputs, tagHint, intent, (els, needle) => {
        const lneedle = needle.toLowerCase();
        return Array.from(els).findIndex(el => {
          const text = (el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().toLowerCase();
          return text && (text === lneedle || text.includes(lneedle) || lneedle.includes(text));
        });
      });
      if (fuzzyIdx >= 0) {
        const fuzzySel = `${tagHint} >> nth=${fuzzyIdx}`;
        if (await tryLocator(page, fuzzySel, 1500, step, inputs)) {
          return { selector: fuzzySel, via: "fuzzy_text", score: 0.4 };
        }
      }
    } catch (_) {}
  }

  return null;
}

// ─── Multi-assertion outcome verification ────────────────────────────────────
// Verifies all compiled assertions after an action completes.
// Required assertions halt execution on failure; advisory ones log warnings.

async function verifyAssertions(page, step, inputs) {
  const assertions = Array.isArray(step.assertions) ? step.assertions
    : ((step.validation && Array.isArray(step.validation.assertions)) ? step.validation.assertions : []);
  if (!assertions.length) return { passed: true, warnings: [] };

  const warnings = [];
  for (const assertion of assertions) {
    const type    = String(assertion.type || "").toLowerCase();
    const target  = interpolate(String(assertion.target || ""), inputs);
    const timeout = Number(assertion.timeout_ms || assertion.timeout || 5000);
    const required = assertion.required !== false;

    try {
      if (type === "url_pattern") {
        const deadline = Date.now() + timeout;
        let matched = false;
        while (Date.now() < deadline) {
          if (new RegExp(target).test(page.url())) { matched = true; break; }
          await new Promise(r => setTimeout(r, 150));
        }
        if (!matched) throw new Error(`URL ${page.url()} does not match ${target}`);

      } else if (type === "url_changed") {
        const baseline = target; // the before_pattern
        const deadline = Date.now() + timeout;
        let changed = false;
        while (Date.now() < deadline) {
          const url = page.url();
          if (!baseline || !new RegExp(baseline).test(url)) { changed = true; break; }
          await new Promise(r => setTimeout(r, 150));
        }
        if (!changed) throw new Error(`URL did not change from pattern ${baseline}`);

      } else if (type === "selector_present") {
        await page.waitForSelector(target, { state: "attached", timeout });

      } else if (type === "selector_absent") {
        await page.waitForSelector(target, { state: "detached", timeout });

      } else if (type === "text_present") {
        await page.waitForFunction(
          (text) => document.body && document.body.innerText.toLowerCase().includes(text.toLowerCase()),
          target,
          { timeout }
        );

      } else if (type === "text_absent") {
        await page.waitForFunction(
          (text) => !document.body || !document.body.innerText.toLowerCase().includes(text.toLowerCase()),
          target,
          { timeout }
        );
      }
    } catch (err) {
      if (required) {
        throw Object.assign(new Error(`Outcome assertion failed [${type}:${target}]: ${err.message}`), {
          assertionFailed: true, assertionType: type, assertionTarget: target,
        });
      }
      warnings.push({ type, target, warning: err.message });
    }
  }
  return { passed: true, warnings };
}

// ─── Recovery embedding ───────────────────────────────────────────────────────

function enrichStepsWithRecovery(steps, recovery) {
  if (!Array.isArray(steps)) return steps;
  const recSteps = (recovery && Array.isArray(recovery.steps)) ? recovery.steps : [];
  return steps.map((step, idx) => {
    const rec = recSteps.find(r => Number(r && r.step_id) === idx + 1);
    if (!rec) return step;
    const sctx       = (rec.selector_context && typeof rec.selector_context === "object") ? rec.selector_context : {};
    const fallback   = (rec.fallback && typeof rec.fallback === "object") ? rec.fallback : {};
    const textVariants = Array.isArray(fallback.text_variants)
      ? fallback.text_variants.filter(t => typeof t === "string" && t.trim()) : [];
    const recCandidates      = [sctx.primary, ...(Array.isArray(sctx.alternatives) ? sctx.alternatives : [])].filter(Boolean);
    const existingCandidates = Array.isArray(step.candidates) ? step.candidates : [];
    return {
      ...step,
      candidates:        Array.from(new Set([...existingCandidates, ...recCandidates])),
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

const RECORDING_MARKER_TYPES = new Set([
  "tab_open", "tab_switch", "popup",
  "download_observed", "dialog_appeared", "dialog_accept", "dialog_dismiss",
  "file_chooser_opened", "clipboard_copy", "clipboard_paste",
]);

function selectorFor(step, inputs) {
  return interpolate(step.selector || step.css_selector || (step.target && step.target.css) || "", inputs);
}

function parseJsonObject(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
}

function shortcutCombo(value, inputs) {
  const raw = interpolate(value || "", inputs);
  const obj = parseJsonObject(raw);
  if (!obj.key && raw) return raw;
  const mods = obj.modifiers && typeof obj.modifiers === "object" ? obj.modifiers : {};
  const parts = [];
  if (mods.ctrl)  parts.push("Control");
  if (mods.meta)  parts.push("Meta");
  if (mods.alt)   parts.push("Alt");
  if (mods.shift) parts.push("Shift");
  parts.push(obj.key || "Enter");
  return parts.join("+");
}

async function assertStep(page, step, inputs) {
  const kind = String(step.kind || "url").toLowerCase();
  if (kind === "url" || kind === "url_exact" || kind === "url_must_be") {
    const expected = interpolate(step.url || step.pattern || step.check_pattern || "", inputs);
    if (!expected) return;
    if (kind === "url") {
      if (!new RegExp(expected).test(page.url()))
        throw new Error(`URL check failed: ${page.url()} does not match ${expected}`);
    } else if (page.url() !== expected) {
      throw new Error(`URL check failed: ${page.url()} is not ${expected}`);
    }
    return;
  }
  if (kind === "selector") {
    await withLocator(page, step, inputs, step.selector || step.check_selector || "", 10000, async loc => loc.first());
    return;
  }
  if (kind === "text") {
    const text = interpolate(step.text || step.check_text || "", inputs);
    await withLocator(page, step, inputs, `text=${JSON.stringify(text)}`, 10000, async loc => loc.first());
    return;
  }
  if (kind === "snapshot") return;
  throw new Error(`Unsupported check kind: ${kind}`);
}

async function executeStep(page, step, inputs) {
  const type = String(step.type || "").toLowerCase();
  const sel  = selectorFor(step, inputs);

  if (RECORDING_MARKER_TYPES.has(type)) return;
  if (type === "frame_enter") {
    const roots = rootCandidates(page, step, inputs);
    if (roots.length === 0 || roots[0] === page) {
      const firstSelector = (frameChain(step)[0] || {}).selector || "unknown";
      appendRecoveryEvent({ event: "frame_enter_failed", step_index: step._seq, selector: firstSelector });
      throw new Error(`frame_enter: iframe not found — ${firstSelector}`);
    }
    appendRecoveryEvent({ event: "frame_entered", depth: frameChain(step).length });
    return;
  }
  if (type === "frame_exit") {
    appendRecoveryEvent({ event: "frame_exited" });
    return;
  }
  if (type === "wait") { await new Promise(r => setTimeout(r, Number(step.ms || step.value) || 1000)); return; }
  if (type === "navigate") {
    await page.goto(interpolate(step.url || "", inputs), { timeout: 30000, waitUntil: "domcontentloaded" });
    return;
  }
  if (type === "scroll") {
    if (sel) await withLocator(page, step, inputs, sel, 0, async loc => loc.first().scrollIntoViewIfNeeded({ timeout: 5000 })).catch(() => {});
    else     await page.evaluate(`window.scrollBy(${Number(step.delta_x)||0}, ${Number(step.delta_y)||0})`);
    await humanDelay("scroll");
    return;
  }
  if (type === "fill" || type === "type" || type === "date_pick") {
    await withLocator(page, step, inputs, sel, 0, async loc => loc.first().fill(interpolate(step.value || "", inputs), { timeout: 15000 }));
    await humanDelay(type);
    return;
  }
  if (type === "click") {
    try {
      await withLocator(page, step, inputs, sel, 0, async loc => {
        try { return await loc.first().click({ timeout: 15000 }); }
        catch (err) {
          if (String(err).includes("intercepts pointer events")) {
            return await loc.last().click({ timeout: 10000 });
          }
          throw err;
        }
      });
      await humanDelay("click");
      return;
    } catch (err) { throw err; }
  }
  if (type === "dblclick")    { await withLocator(page, step, inputs, sel, 0, async loc => loc.first().dblclick({ timeout: 15000 })); await humanDelay("click"); return; }
  if (type === "right_click") { await withLocator(page, step, inputs, sel, 0, async loc => loc.first().click({ button: "right", timeout: 15000 })); await humanDelay("click"); return; }
  if (type === "hover")       { await withLocator(page, step, inputs, sel, 0, async loc => loc.first().hover({ timeout: 10000 })); await humanDelay("hover"); return; }
  if (type === "select" || type === "select_option") {
    await withLocator(page, step, inputs, sel, 0, async loc => loc.first().selectOption(interpolate(step.value || "", inputs), { timeout: 15000 }));
    await humanDelay(type);
    return;
  }
  if (type === "set_checkbox") {
    const checked = !["false", "0", "off", "unchecked"].includes(String(interpolate(step.value || "true", inputs)).toLowerCase());
    await withLocator(page, step, inputs, sel, 0, async loc => loc.first().setChecked(checked, { timeout: 10000 }));
    await humanDelay("click");
    return;
  }
  if (type === "set_radio") {
    await withLocator(page, step, inputs, sel, 0, async loc => {
      await loc.first().check({ timeout: 10000 }).catch(async () => {
        await loc.first().click({ timeout: 10000 });
      });
    });
    await humanDelay("click");
    return;
  }
  if (type === "focus") {
    if (sel) {
      await withLocator(page, step, inputs, sel, 0, async loc => {
        try { await loc.first().click({ timeout: 5000 }); }
        catch (_) { await loc.first().focus({ timeout: 10000 }).catch(() => {}); }
      });
    }
    await humanDelay("focus");
    return;
  }
  if (type === "keyboard_shortcut") {
    if (sel) await withLocator(page, step, inputs, sel, 0, async loc => loc.first().focus({ timeout: 5000 })).catch(() => {});
    await page.keyboard.press(shortcutCombo(step.value, inputs));
    return;
  }
  if (type === "drag_drop") {
    const payload = parseJsonObject(step.value);
    const src = interpolate(step.src_selector || step.src_css || payload.src_selector || payload.src_css || "", inputs);
    const dst = interpolate(step.dst_selector || step.dst_css || payload.dst_selector || payload.dst_css || sel, inputs);
    if (!src || !dst) throw new Error("drag_drop requires src_selector and dst_selector");
    await withLocatorPair(page, step, inputs, src, dst, 0, async (srcLoc, dstLoc) => srcLoc.first().dragTo(dstLoc.first(), { timeout: 15000 }));
    await humanDelay("click");
    return;
  }
  if (type === "upload" || type === "upload_intent") {
    if (!sel) throw new Error("upload requires selector");
    await withLocator(page, step, inputs, sel, 0, async loc => loc.first().setInputFiles(interpolate(step.value || "", inputs), { timeout: 15000 }));
    return;
  }
  if (type === "screenshot") { await page.screenshot({ type: "png" }).catch(() => null); return; }
  if (type === "check" || type === "assert") { await assertStep(page, step, inputs); return; }
  throw new Error(`Unsupported step type: ${type}`);
}

// ─── runSkill — CLI / file-based execution (simpler path) ────────────────────

async function runSkill(page, skillDir, inputs) {
  const execPath = path.join(skillDir, "execution.json");
  if (!fs.existsSync(execPath)) throw new Error(`execution.json not found in ${skillDir}`);
  const exec  = JSON.parse(fs.readFileSync(execPath, "utf8"));
  const steps = Array.isArray(exec) ? exec
              : Array.isArray(exec.steps) ? exec.steps
              : Array.isArray(exec.execution_plan) ? exec.execution_plan : [];
  const recoveryPath = path.join(skillDir, "recovery.json");
  const recovery = fs.existsSync(recoveryPath) ? JSON.parse(fs.readFileSync(recoveryPath, "utf8")) : { steps: [] };

  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    try {
      if (step.url_state?.before?.url_pattern) await waitForUrlState(page, step.url_state.before);
      await executeStep(page, step, inputs);
      if (step.url_state?.after?.url_pattern) await waitForUrlState(page, step.url_state.after);
    } catch (err) {
      if (String(err.message || err).includes("expected pattern"))
        throw new Error(`Step ${step.id || i} (${step.type}) failed: ${err.message}`);
      const stepNumber = i + 1;
      const rec = (recovery.steps || []).find(r => (step.id && r.id === step.id) || Number(r.step_id) === stepNumber);
      let recovered = false;
      if (rec) {
        const sctx = rec.selector_context && typeof rec.selector_context === "object" ? rec.selector_context : {};
        const fb   = rec.fallback && typeof rec.fallback === "object" ? rec.fallback : {};
        const candidates = Array.from(new Set([
          ...(Array.isArray(rec.fallback_selectors) ? rec.fallback_selectors : []),
          ...(Array.isArray(rec.candidates) ? rec.candidates : []),
          ...(typeof sctx.primary === "string" ? [sctx.primary] : []),
          ...(Array.isArray(sctx.alternatives) ? sctx.alternatives : []),
          ...(Array.isArray(fb.text_variants) ? fb.text_variants.map(t => `text=${JSON.stringify(String(t).trim())}`) : []),
          ...(Array.isArray(rec.anchors) ? rec.anchors.filter(a => a && typeof a.text === "string" && a.text.trim()).map(a => `text=${JSON.stringify(a.text.trim())}`) : []),
        ].filter(Boolean)));
        for (const cand of candidates) {
          if (await tryLocator(page, cand, 3000, step, inputs)) {
            try {
              await executeStep(page, { ...step, selector: cand }, inputs);
              if (step.url_state?.after?.url_pattern) await waitForUrlState(page, step.url_state.after);
              recovered = true;
              break;
            } catch (_) {}
          }
        }
      }
      if (!recovered) throw new Error(`Step ${step.id || i} (${step.type}) failed: ${err.message}`);
    }
  }
}

// ─── Execution pause/resume (checkpoint file protocol) ────────────────────────
// Pause: server writes {action:"pause"} to the execution control file.
// Resume: server clears the file; runPlan polls between steps.

function getControlFile(slug) {
  return path.join(CONXA_HOME, "executions", `${slug}.ctrl`);
}

function writePauseSignal(slug) {
  const ctrl = getControlFile(slug);
  try {
    fs.mkdirSync(path.dirname(ctrl), { recursive: true });
    fs.writeFileSync(ctrl, JSON.stringify({ action: "pause", ts: new Date().toISOString() }));
  } catch (_) {}
}

function clearPauseSignal(slug) {
  try { fs.unlinkSync(getControlFile(slug)); } catch (_) {}
}

function isPaused(slug) {
  try {
    const ctrl = getControlFile(slug);
    if (!fs.existsSync(ctrl)) return false;
    const data = JSON.parse(fs.readFileSync(ctrl, "utf8"));
    return data && data.action === "pause";
  } catch (_) { return false; }
}

async function waitForResume(slug, maxWaitMs = 10 * 60 * 1000) {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    if (!isPaused(slug)) return;
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`Execution of ${slug} timed out waiting for resume after pause`);
}

// Write step checkpoint so execution can resume from a known point.
function writeCheckpoint(slug, stepIndex, stepTotal) {
  const dir = path.join(CONXA_HOME, "executions");
  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${slug}.checkpoint`),
      JSON.stringify({ step_index: stepIndex, step_total: stepTotal, ts: new Date().toISOString() })
    );
  } catch (_) {}
}

function clearCheckpoint(slug) {
  try { fs.unlinkSync(path.join(CONXA_HOME, "executions", `${slug}.checkpoint`)); } catch (_) {}
}

// ─── runPlan — scoring-based recovery + adaptive timing + assertion verification

async function runPlan(page, steps, inputs, startFrom, slug) {
  const INTERACTIVE = new Set(["click", "type", "fill", "focus", "select", "select_option", "dblclick", "right_click"]);

  for (let i = startFrom; i < steps.length; i++) {
    const step = steps[i];

    // Check for pause signal between steps
    if (slug && isPaused(slug)) {
      appendRecoveryEvent({ event: "execution_paused", slug, step_index: i });
      await waitForResume(slug);
      appendRecoveryEvent({ event: "execution_resumed", slug, step_index: i });
    }

    // Adaptive page settle: use networkIdle for navigate steps, DOM-stable otherwise
    const isNavigate   = step.type === "navigate";
    const isInteractive = INTERACTIVE.has(step.type);
    await waitForStable(page, { timeout: 5000, networkIdle: isNavigate });

    // Pre-step screenshot (interactive steps only, for L4 vision recovery)
    const preShot = isInteractive
      ? await page.screenshot({ type: "png", timeout: 3000 }).catch(() => null)
      : null;

    // Pre-step URL state check
    try {
      if (step.url_state?.before?.url_pattern) await waitForUrlState(page, step.url_state.before);
    } catch (urlErr) {
      // URL pre-condition failed — enrich error for L4/L5
      const e = new Error(`Step ${i + 1} (${step.type}) pre-condition failed: ${urlErr.message}`);
      e.failedAt = i; e.failedStep = step; e.preShot = preShot;
      throw e;
    }

    // ── Primary attempt ────────────────────────────────────────────────────
    let primaryErr = null;
    try {
      await executeStep(page, step, inputs);
      if (step.url_state?.after?.url_pattern) await waitForUrlState(page, step.url_state.after);
      // Verify outcome assertions after successful action
      const { warnings } = await verifyAssertions(page, step, inputs);
      if (warnings.length) {
        appendRecoveryEvent({ event: "assertion_warnings", slug, step_index: i, warnings });
      }
      writeCheckpoint(slug || "unknown", i + 1, steps.length);
      continue;
    } catch (e) {
      if (e.assertionFailed) {
        // Outcome assertion failure: step action succeeded but outcome didn't match
        e.failedAt = i; e.failedStep = step; e.preShot = preShot;
        appendRecoveryEvent({ event: "assertion_failure", slug, step_index: i, error: e.message });
        throw e;
      }
      primaryErr = e;
    }

    // ── Scoring-based element recovery ────────────────────────────────────
    let recovered = false;
    const resolved = await resolveElement(page, step, inputs);
    if (resolved) {
      try {
        await executeStep(page, { ...step, selector: resolved.selector }, inputs);
        if (step.url_state?.after?.url_pattern) await waitForUrlState(page, step.url_state.after);
        const { warnings } = await verifyAssertions(page, step, inputs);
        if (warnings.length) {
          appendRecoveryEvent({ event: "assertion_warnings", slug, step_index: i, warnings });
        }
        recovered = true;
        appendRecoveryEvent({
          event: "element_recovered",
          slug, step_index: i,
          via: resolved.via,
          score: resolved.score,
          recovery_selector: resolved.selector,
        });
        writeCheckpoint(slug || "unknown", i + 1, steps.length);
      } catch (recErr) {
        if (recErr.assertionFailed) {
          recErr.failedAt = i; recErr.failedStep = step; recErr.preShot = preShot;
          throw recErr;
        }
        // Recovery selector found but action still failed — fall through to throw
      }
    }

    // ── All recovery exhausted → throw enriched error for L4/L5 ──────────
    if (!recovered) {
      const e = new Error(`Step ${i + 1} (${step.type}) failed: ${primaryErr.message}`);
      e.failedAt   = i;
      e.failedStep = step;
      e.preShot    = preShot;
      appendRecoveryEvent({ event: "step_failed", slug, step_index: i, error: primaryErr.message });
      throw e;
    }
  }

  if (slug) clearCheckpoint(slug);
}

module.exports = {
  appendRecoveryEvent,
  interpolate,
  tryLocator,
  waitForUrlState,
  waitForStable,
  enrichStepsWithRecovery,
  executeStep,
  resolveElement,
  verifyAssertions,
  runSkill,
  runPlan,
  checkRetryBudget,
  clearRetryBudget,
  writePauseSignal,
  clearPauseSignal,
  writeCheckpoint,
  clearCheckpoint,
  isPaused,
};
