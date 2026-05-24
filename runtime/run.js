"use strict";
const fs   = require("fs");
const path = require("path");
const os   = require("os");

const { mapErrorToCode } = require("./tracker");

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

function _sel(step, inputs) {
  return interpolate(step.selector || step.css_selector || (step.target && step.target.css) || "", inputs);
}

const _HANDLERS = {
  wait: async (page, step) => {
    await page.waitForTimeout(Number(step.ms) || 1000);
  },
  navigate: async (page, step, inputs) => {
    await page.goto(interpolate(step.url || "", inputs), { timeout: 30000, waitUntil: "domcontentloaded" });
  },
  scroll: async (page, step, inputs) => {
    const sel = _sel(step, inputs);
    if (sel) await withLocator(page, step, inputs, sel, 0, async loc => loc.first().scrollIntoViewIfNeeded({ timeout: 5000 })).catch(() => {});
    else     await page.evaluate(`window.scrollBy(${Number(step.delta_x) || 0}, ${Number(step.delta_y) || 0})`);
    await humanDelay("scroll");
  },
  fill: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().fill(interpolate(step.value || "", inputs), { timeout: 15000 }));
    await humanDelay("fill");
  },
  type: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().fill(interpolate(step.value || "", inputs), { timeout: 15000 }));
    await humanDelay("type");
  },
  click: async (page, step, inputs) => {
    const sel = _sel(step, inputs);
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
    }
    catch (err) {
      throw err;
    }
  },
  dblclick: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().dblclick({ timeout: 15000 }));
    await humanDelay("click");
  },
  right_click: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().click({ button: "right", timeout: 15000 }));
    await humanDelay("click");
  },
  hover: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().hover({ timeout: 10000 }));
    await humanDelay("focus");
  },
  select: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().selectOption(interpolate(step.value || "", inputs), { timeout: 15000 }));
    await humanDelay("select");
  },
  select_option: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().selectOption(interpolate(step.value || "", inputs), { timeout: 15000 }));
    await humanDelay("select");
  },
  focus: async (page, step, inputs) => {
    const sel = _sel(step, inputs);
    if (sel) {
      await withLocator(page, step, inputs, sel, 0, async loc => {
        try { await loc.first().click({ timeout: 5000 }); }
        catch (_) { await loc.first().focus({ timeout: 10000 }).catch(() => {}); }
      });
    }
    await humanDelay("focus");
  },
  set_checkbox: async (page, step, inputs) => {
    const checked = String(interpolate(step.value || "true", inputs)).toLowerCase() !== "false";
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().setChecked(checked, { timeout: 10000 }));
    await humanDelay("click");
  },
  set_radio: async (page, step, inputs) => {
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().click({ timeout: 10000 }));
    await humanDelay("click");
  },
  date_pick: async (page, step, inputs) => {
    const val = interpolate(step.value || "", inputs);
    await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => {
      const first = loc.first();
      try { await first.fill(val, { timeout: 10000 }); }
      catch (_) { await first.click({ timeout: 5000 }).catch(() => {}); }
    });
    await humanDelay("fill");
  },
  drag_drop: async (page, step, inputs) => {
    let srcSel = interpolate(step.src_selector || "", inputs);
    let dstSel = interpolate(step.dst_selector || _sel(step, inputs), inputs);
    if (!srcSel && step.value) {
      try {
        const v = JSON.parse(step.value);
        srcSel = v.src_css || "";
        if (!dstSel) dstSel = v.dst_css || "";
      } catch (_) {}
    }
    if (srcSel && dstSel) {
      await withLocatorPair(page, step, inputs, srcSel, dstSel, 0, async (srcLoc, dstLoc) => srcLoc.first().dragTo(dstLoc.first(), { timeout: 15000 }));
    }
    await humanDelay("click");
  },
  keyboard_shortcut: async (page, step, inputs) => {
    let keyStr = interpolate(step.value || "", inputs);
    try {
      const parsed = JSON.parse(keyStr);
      const mods = parsed.modifiers || {};
      const parts = [];
      if (mods.ctrl)  parts.push("Control");
      if (mods.meta)  parts.push("Meta");
      if (mods.shift) parts.push("Shift");
      if (mods.alt)   parts.push("Alt");
      if (parsed.key) parts.push(parsed.key.length === 1 ? parsed.key.toUpperCase() : parsed.key);
      if (parts.length) keyStr = parts.join("+");
    } catch (_) {}
    if (keyStr) await page.keyboard.press(keyStr, { delay: 50 });
  },
  check: async (page, step, inputs) => {
    const pattern = interpolate(step.pattern || step.check_pattern || "", inputs);
    if (pattern && !new RegExp(pattern).test(page.url()))
      throw new Error(`URL check failed: ${page.url()} does not match ${pattern}`);
  },
  assert: async (page, step, inputs) => {
    const kind = step.assert_kind || step.kind || "url";
    if (kind === "url") {
      const pattern = interpolate(step.pattern || step.value || "", inputs);
      if (pattern && !new RegExp(pattern).test(page.url()))
        throw new Error(`Assert failed: URL ${page.url()} does not match ${pattern}`);
    } else if (kind === "selector" || kind === "visible") {
      const sel = _sel(step, inputs);
      if (sel) await withLocator(page, step, inputs, sel, step.timeout || 5000, async loc => loc.first());
    } else if (kind === "text") {
      const sel = _sel(step, inputs);
      const expected = interpolate(step.value || "", inputs);
      if (sel && expected) {
        const actual = await withLocator(page, step, inputs, sel, 0, async loc => loc.first().innerText({ timeout: 5000 })).catch(() => "");
        if (!actual.includes(expected))
          throw new Error(`Assert text: "${actual}" does not include "${expected}"`);
      }
    }
  },
  screenshot: async (page) => {
    await page.screenshot({ type: "png", timeout: 5000 }).catch(() => null);
  },
  upload: async (page, step, inputs) => {
    const filePath = interpolate(step.value || "", inputs);
    if (filePath) await withLocator(page, step, inputs, _sel(step, inputs), 0, async loc => loc.first().setInputFiles(filePath, { timeout: 15000 }));
  },
};

// Recording-only markers and context-level events have no replay action
for (const k of ["tab_open","tab_switch","popup","frame_enter","frame_exit",
                  "upload_intent","download_observed","dialog_appeared","dialog_accept",
                  "dialog_dismiss","file_chooser_opened","clipboard_copy","clipboard_paste"]) {
  _HANDLERS[k] = async () => {};
}

async function executeStep(page, step, inputs) {
  const type = step.type;
  const handler = _HANDLERS[type];
  if (!handler) return; // unknown type — skip gracefully
  await handler(page, step, inputs);
}

// ─── runPlan — 5-layer recovery cascade ──────────────────────────────────────

async function runPlan(page, steps, inputs, startFrom, slug, { onStep, cancelCheck, tracker } = {}) {
  const t = tracker || { emit: () => {} };
  let recoveredSteps = 0;
  const INTERACTIVE = new Set([
    "click", "dblclick", "right_click",
    "type", "fill", "focus", "select", "select_option",
    "set_checkbox", "set_radio", "date_pick",
    "drag_drop", "keyboard_shortcut", "upload",
  ]);

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
      await executeStep(page, step, inputs);
      continue;
    } catch (e) { primaryErr = e; }

    let recovered = false;

    // L1: Transient retry
    t.emit("rec_start", { si: i, l: 1, sc: "selector_retry" });
    try {
      await page.waitForTimeout(1500);
      if (primarySel && await tryLocator(page, primarySel, 3500, step, inputs)) {
        await executeStep(page, step, inputs);
        recovered = true;
        recoveredSteps++;
        appendRecoveryEvent({ event: "transient_recovered", slug, step_index: i });
        t.emit("rec_ok", { si: i, l: 1, sc: "selector_retry" });
      }
    } catch (_) {}
    if (!recovered) t.emit("rec_fail", { si: i, l: 1, sc: "selector_retry" });

    // L2: Predefined alternatives
    if (!recovered) {
      t.emit("rec_start", { si: i, l: 2, sc: "candidate_fallback" });
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
        if (await tryLocator(page, cand, 3000, step, inputs)) {
          try {
            await executeStep(page, { ...step, selector: cand }, inputs);
            recovered = true;
            recoveredSteps++;
            appendRecoveryEvent({ event: "layer_recovered", layer: 2, slug, step_index: i, recovery_selector: cand });
            t.emit("rec_ok", { si: i, l: 2, sc: "candidate_fallback" });
            break;
          } catch (_) {}
        }
      }
      if (!recovered) t.emit("rec_fail", { si: i, l: 2, sc: "candidate_fallback" });
    }

    // L3a: Dialog-scoped
    if (!recovered && step.type === "click" && primarySel) {
      t.emit("rec_start", { si: i, l: 3, sc: "dialog_scope" });
      for (const container of ['[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]', ".modal"]) {
        const scoped = `${container} ${primarySel}`;
        if (await tryLocator(page, scoped, 2000, step, inputs)) {
          try {
            await executeStep(page, { ...step, selector: scoped }, inputs);
            recovered = true;
            recoveredSteps++;
            appendRecoveryEvent({ event: "layer_recovered", layer: 3, slug, step_index: i, mode: "dialog" });
            t.emit("rec_ok", { si: i, l: 3, sc: "dialog_scope" });
            break;
          } catch (_) {}
        }
        if (recovered) break;
      }
      if (!recovered) t.emit("rec_fail", { si: i, l: 3, sc: "dialog_scope" });
    }

    // L3b: Fuzzy tag+text DOM match
    if (!recovered) {
      t.emit("rec_start", { si: i, l: 4, sc: "fuzzy_dom" });
      const intent  = [step.value, step.label, step.aria_label, step._intent]
        .filter(v => v && typeof v === "string" && v.trim()).map(v => v.trim())[0];
      const tagMatch = primarySel.match(/^(button|a|input|select|textarea)/i);
      const tagHint  = tagMatch ? tagMatch[1].toLowerCase() : null;

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
            if (await tryLocator(page, fuzzySel, 2000, step, inputs)) {
              try {
                await executeStep(page, { ...step, selector: fuzzySel }, inputs);
                recovered = true;
                recoveredSteps++;
                appendRecoveryEvent({ event: "layer_recovered", layer: 3, slug, step_index: i, mode: "fuzzy" });
                t.emit("rec_ok", { si: i, l: 4, sc: "fuzzy_dom" });
              } catch (_) {}
            }
          }
        } catch (_) {}
      }
      if (!recovered) t.emit("rec_fail", { si: i, l: 4, sc: "fuzzy_dom" });
    }

    if (!recovered) {
      t.emit("step_fail", { si: i, fc: mapErrorToCode(primaryErr) });
      const e = new Error(`Step ${i + 1} (${step.type}) failed: ${primaryErr.message}`);
      e.failedAt   = i;
      e.failedStep = step;
      e.preShot    = preShot;
      throw e;
    }
  }
  return { recoveredSteps };
}

module.exports = {
  appendRecoveryEvent,
  interpolate,
  tryLocator,
  enrichStepsWithRecovery,
  executeStep,
  runPlan,
  checkRetryBudget,
  clearRetryBudget,
  mapErrorToCode,
};
