"""Static runtime and orchestration templates for generated skill packages."""

from __future__ import annotations

import json

EXECUTOR_JS = """\
"use strict";
const fs = require("fs");
const path = require("path");
const recovery = require("./recovery");
const validator = require("./validator");

function skillDir(name) {
  return path.join(__dirname, "..", "skills", name);
}

function interpolate(value, inputs) {
  if (typeof value !== "string") return value;
  return value.replace(/\\{\\{\\s*([^{}]+?)\\s*\\}\\}/g, (_, key) => String(inputs[key] ?? ""));
}

function parseArgs() {
  const args = {};
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    args[key] = argv[i + 1] ?? "";
  }
  return args;
}

async function trySelector(page, selector, timeout) {
  try {
    await page.locator(selector).waitFor({ state: "visible", timeout: timeout || 5000 });
    return true;
  } catch (_) {
    return false;
  }
}

async function applyRecovery(page, ctx) {
  for (const layer of [1, 2, 3, 4]) {
    let plan;
    try {
      plan = await recovery.runLayer(layer, ctx);
    } catch (_) {
      continue;
    }
    if (!plan) continue;

    const candidates = [];
    if (plan.strategy === "selector_fallback" && Array.isArray(plan.candidates)) {
      candidates.push(...plan.candidates);
    } else if (plan.strategy === "anchor_fallback" && Array.isArray(plan.anchors)) {
      const sorted = plan.anchors.slice().sort((a, b) => b.priority - a.priority);
      for (const anchor of sorted) {
        candidates.push(`text=${JSON.stringify(anchor.text)}`);
      }
    }

    for (const sel of candidates) {
      if (await trySelector(page, sel, 3000)) return sel;
    }
  }
  return null;
}

const RECOVERY_ACTION_TYPES = new Set(["type", "fill", "click", "select", "focus"]);
const PLAIN_RETRY_ACTION_TYPES = new Set(["navigate", "check"]);
const ELEMENT_TOTAL_ATTEMPTS = 2;
const NAV_CHECK_TOTAL_ATTEMPTS = 3;

function totalAttempts(type) {
  if (PLAIN_RETRY_ACTION_TYPES.has(type)) return NAV_CHECK_TOTAL_ATTEMPTS;
  if (RECOVERY_ACTION_TYPES.has(type)) return ELEMENT_TOTAL_ATTEMPTS;
  return 1;
}

async function runCheck(page, step, inputs) {
  const kind = String(step.kind || "url").toLowerCase();
  if (kind === "url") {
    const pattern = interpolate(step.pattern || step.check_pattern || "", inputs);
    const url = page.url();
    if (!url.includes(pattern)) throw new Error(`URL check failed: ${url} does not include ${pattern}`);
    return;
  }
  if (kind === "url_exact" || kind === "url_must_be") {
    const expected = interpolate(step.url || step.expected_url || step.pattern || step.check_pattern || "", inputs);
    const url = page.url();
    if (url !== expected) throw new Error(`URL exact check failed: ${url} does not equal ${expected}`);
    return;
  }
  if (kind === "selector") {
    const selector = interpolate(step.selector || "", inputs);
    await page.locator(selector).first().waitFor({ state: "attached", timeout: 5000 });
    return;
  }
  if (kind === "text") {
    const text = interpolate(step.text || "", inputs);
    await page.locator(`text=${JSON.stringify(text)}`).first().waitFor({ state: "visible", timeout: 5000 });
    return;
  }
  if (kind === "snapshot") {
    return;
  }
  throw new Error(`Unknown check kind: ${kind}`);
}

async function runScroll(page, step, inputs) {
  const selector = interpolate(step.selector || "", inputs);
  if (selector) {
    await page.locator(selector).first().scrollIntoViewIfNeeded({ timeout: 5000 });
    return;
  }
  await page.evaluate(`window.scrollBy(${Number(step.delta_x) || 0}, ${Number(step.delta_y) || 0})`);
}

async function performAction(page, step, inputs, selector) {
  const type = step.type;
  if (type === "wait") {
    await new Promise((resolve) => setTimeout(resolve, Number(step.ms) || 1000));
    return;
  }
  if (type === "navigate") {
    const url = interpolate(step.url || "", inputs);
    await page.goto(url, { timeout: 15000, waitUntil: "domcontentloaded" });
    return;
  }
  if (type === "scroll") {
    await runScroll(page, step, inputs);
    return;
  }
  if (type === "check") {
    await runCheck(page, step, inputs);
    return;
  }
  if (type === "fill" || type === "type") {
    const value = interpolate(step.value || "", inputs);
    await page.locator(selector).first().fill(value, { timeout: 15000 });
    return;
  }
  if (type === "click") {
    await page.locator(selector).first().click({ timeout: 15000 });
    return;
  }
  if (type === "select") {
    const value = interpolate(step.value || "", inputs);
    await page.locator(selector).first().selectOption(value, { timeout: 15000 });
    return;
  }
  if (type === "focus") {
    await page.locator(selector).first().focus({ timeout: 15000 });
    return;
  }
  throw new Error(`Unknown step type: ${type}`);
}

async function dispatchStep(page, step, inputs, skill, stepIdx) {
  const type = step.type;
  const sel = interpolate(step.selector || "", inputs);
  const start = Date.now();
  const row = { step: stepIdx, type, selector: sel, attempts: 0 };

  try {
    let lastError = null;
    const attempts = totalAttempts(type);
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      row.attempts = attempt;
      try {
        await performAction(page, step, inputs, sel);
        row.status = "ok";
        lastError = null;
        break;
      } catch (err) {
        lastError = err;
        if (RECOVERY_ACTION_TYPES.has(type)) {
          const alt = await applyRecovery(page, { skill, step: stepIdx, error: String(err), page });
          if (alt) {
            try {
              await performAction(page, step, inputs, alt);
              row.status = "recovered"; row.recovered_via = alt;
              lastError = null;
              break;
            } catch (recoveryErr) {
              lastError = recoveryErr;
            }
          }
        }
        if (attempt === attempts) throw lastError;
      }
    }
    if (lastError) throw lastError;
  } catch (err) {
    row.status = "failed";
    row.error = String(err).split("\\n")[0].slice(0, 300);
  }

  row.latency_ms = Date.now() - start;
  return row;
}

async function runSingleSkill(skill, inputs, resultPath, headless) {
  try {
    validator.validateInput(skill, inputs);
  } catch (err) {
    console.error(`[executor] input validation failed: ${err.message}`);
    process.exit(1);
  }

  const executionPath = path.join(skillDir(skill), "execution.json");
  if (!fs.existsSync(executionPath)) {
    console.error(`[executor] execution.json not found for skill: ${skill}`);
    process.exit(1);
  }

  const steps = JSON.parse(fs.readFileSync(executionPath, "utf8"));
  const { chromium } = require("playwright");
  const browser = await chromium.launch({ headless, slowMo: 100 });
  const context = await browser.newContext();
  const page = await context.newPage();

  const STEP_DELAY_MS = Number(process.env.STEP_DELAY_MS) || 1200;

  const rows = [];
  console.log(`[executor] skill=${skill} steps=${steps.length}`);

  for (let i = 0; i < steps.length; i++) {
    const stepIdx = i + 1;
    const stepType = steps[i].type;
    process.stdout.write(`[executor] step ${stepIdx}/${steps.length} type=${stepType} ... `);
    const row = await dispatchStep(page, steps[i], inputs, skill, stepIdx);
    rows.push(row);
    console.log(row.status + (row.recovered_via ? ` (via ${row.recovered_via})` : ""));
    if (stepType !== "wait") {
      await new Promise((resolve) => setTimeout(resolve, STEP_DELAY_MS));
    }
  }

  try { await browser.close(); } catch (_) {}

  const ok = rows.filter(r => r.status === "ok").length;
  const recovered = rows.filter(r => r.status === "recovered").length;
  const failed = rows.filter(r => r.status === "failed").length;
  const passed = failed === 0;
  const result = { skill, passed, steps: rows, summary: { total: rows.length, ok, recovered, failed } };
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), "utf8");
  console.log(`[executor] done — ok=${ok} recovered=${recovered} failed=${failed} → ${resultPath}`);

  return { passed, result };
}

async function main() {
  const args = parseArgs();

  // Plan mode: execute multiple skills from a plan file
  if (args.plan) {
    const planPath = path.resolve(args.plan);
    if (!fs.existsSync(planPath)) {
      console.error(`[executor] plan file not found: ${planPath}`);
      process.exit(1);
    }

    const plan = JSON.parse(fs.readFileSync(planPath, "utf8"));
    if (!Array.isArray(plan)) {
      console.error(`[executor] plan must be an array of {skill, inputs} objects`);
      process.exit(1);
    }

    const resultPath = args.result ? path.resolve(args.result) : path.join(__dirname, "..", "EXECUTION_PLAN_RESULT.json");
    const headless = args.headless === "1";
    const planResults = [];
    let anyFailed = false;

    for (const entry of plan) {
      const skill = entry.skill;
      const inputs = entry.inputs || {};
      if (!skill) {
        console.error(`[executor] plan entry missing 'skill'`);
        process.exit(1);
      }

      const { passed, result } = await runSingleSkill(skill, inputs, resultPath, headless);
      planResults.push(result);
      if (!passed) anyFailed = true;
    }

    const aggregated = {
      plan: plan.length,
      results: planResults,
      passed: !anyFailed
    };
    fs.writeFileSync(resultPath, JSON.stringify(aggregated, null, 2), "utf8");
    console.log(`[executor] plan complete: ${planResults.length} skills → ${resultPath}`);
    process.exit(anyFailed ? 1 : 0);
  }

  // Legacy single-skill mode
  const skill = args.skill;
  if (!skill) { console.error("[executor] --skill or --plan is required"); process.exit(1); }

  const inputs = args.inputs && fs.existsSync(args.inputs)
    ? JSON.parse(fs.readFileSync(args.inputs, "utf8"))
    : {};

  const resultPath = args.result
    ? path.resolve(args.result)
    : path.join(__dirname, "..", "EXECUTION_RESULT.json");

  const headless = args.headless === "1";

  const { passed } = await runSingleSkill(skill, inputs, resultPath, headless);
  process.exit(passed ? 0 : 1);
}

main().catch(err => {
  console.error("[executor] fatal:", err.message || err);
  process.exit(1);
});
"""

PACKAGE_JSON = json.dumps(
    {"name": "conxa-plugin-runtime", "private": True, "dependencies": {"playwright": "^1.47.0"}},
    indent=2,
) + "\n"

RECOVERY_JS = """\
const fs = require("fs");
const path = require("path");
const tracker = require("./tracker");

// layer 0 = crashed (all layers exhausted)
// layer 1 = selector alternatives / text-variant fallback
// layer 2 = anchors
// layer 3 = LLM intent recovery
// layer 4 = vision recovery

function skillDir(name) {
  return path.join(__dirname, "..", "skills", name);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function stepId(value) {
  const num = Number(value);
  return Number.isInteger(num) && num > 0 ? num : null;
}

function uniqueStrings(values) {
  const out = [];
  const seen = new Set();
  for (const value of values || []) {
    if (typeof value !== "string") continue;
    const clean = value.trim();
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out;
}

function loadRecoveryMap(skill) {
  if (!skill) return null;
  const filePath = path.join(skillDir(skill), "recovery.json");
  if (!fs.existsSync(filePath)) return null;
  try {
    return readJson(filePath);
  } catch (_) {
    return null;
  }
}

function getRecoveryEntry(ctx) {
  if (ctx && ctx.recoveryEntry && typeof ctx.recoveryEntry === "object") {
    return ctx.recoveryEntry;
  }
  const recovery = ctx && typeof ctx.recovery === "object" ? ctx.recovery : loadRecoveryMap(ctx && ctx.skill);
  if (!recovery || !Array.isArray(recovery.steps)) return null;
  const currentStep = stepId(ctx && ctx.step);
  if (currentStep == null) return null;
  return recovery.steps.find((entry) => stepId(entry && entry.step_id) === currentStep) || null;
}

function buildTextVariantSelectors(entry) {
  const fallback = entry && typeof entry.fallback === "object" ? entry.fallback : {};
  const variants = Array.isArray(fallback.text_variants) ? fallback.text_variants : [];
  return variants
    .map((text) => (typeof text === "string" && text.trim() ? `text=${JSON.stringify(text.trim())}` : ""))
    .filter(Boolean);
}

function runSelectorFallback(ctx, entry) {
  const selectorContext = entry && typeof entry.selector_context === "object" ? entry.selector_context : {};
  const primary = typeof selectorContext.primary === "string" ? selectorContext.primary : "";
  const alternatives = Array.isArray(selectorContext.alternatives) ? selectorContext.alternatives : [];
  const candidates = uniqueStrings([primary, ...alternatives, ...buildTextVariantSelectors(entry)]);
  if (!candidates.length) return null;
  return {
    layer: 1,
    strategy: "selector_fallback",
    candidates,
    recovery_entry: entry,
  };
}

function runAnchorFallback(ctx, entry) {
  const anchors = Array.isArray(entry && entry.anchors) ? entry.anchors : [];
  const fallback = entry && typeof entry.fallback === "object" ? entry.fallback : {};
  const target = entry && typeof entry.target === "object" ? entry.target : {};
  const role = typeof fallback.role === "string" && fallback.role.trim()
    ? fallback.role.trim()
    : (typeof target.role === "string" ? target.role.trim() : "");
  const texts = uniqueStrings(
    anchors
      .map((anchor) => (anchor && typeof anchor === "object" ? anchor.text : ""))
      .filter(Boolean)
  );
  if (!texts.length && !role) return null;
  return {
    layer: 2,
    strategy: "anchor_fallback",
    anchors: anchors
      .filter((anchor) => anchor && typeof anchor === "object" && typeof anchor.text === "string" && anchor.text.trim())
      .map((anchor) => ({
        text: anchor.text.trim(),
        priority: Number.isFinite(Number(anchor.priority)) ? Number(anchor.priority) : 1,
      })),
    role,
    recovery_entry: entry,
  };
}

function truncateText(value, maxLength) {
  const text = typeof value === "string" ? value : JSON.stringify(value || "");
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

async function captureDomSnapshot(page) {
  if (!page || typeof page.evaluate !== "function") return "";
  try {
    return truncateText(await page.evaluate(() => {
      const visibleText = (node) => (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim();
      const elements = Array.from(document.querySelectorAll("button,a,input,textarea,select,[role],[aria-label],[placeholder],[data-testid]"))
        .slice(0, 120)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          return {
            tag: el.tagName.toLowerCase(),
            id: el.id || "",
            role: el.getAttribute("role") || "",
            name: el.getAttribute("name") || "",
            type: el.getAttribute("type") || "",
            text: visibleText(el).slice(0, 120),
            aria: el.getAttribute("aria-label") || "",
            placeholder: el.getAttribute("placeholder") || "",
            testid: el.getAttribute("data-testid") || "",
            visible: rect.width > 0 && rect.height > 0,
          };
        });
      return {
        url: location.href,
        title: document.title,
        body_text: visibleText(document.body).slice(0, 3000),
        elements,
      };
    }), 12000);
  } catch (_) {
    try {
      return truncateText(await page.content(), 12000);
    } catch (_) {
      return "";
    }
  }
}

async function captureScreenshotBase64(page) {
  if (!page || typeof page.screenshot !== "function") return "";
  try {
    const buffer = await page.screenshot({ type: "jpeg", quality: 45, fullPage: false, timeout: 2000 });
    return buffer.toString("base64");
  } catch (_) {
    return "";
  }
}

function parseLlmSelectors(text) {
  if (!text) return [];
  const match = text.match(/\\{[\\s\\S]*\\}/);
  if (!match) return [];
  try {
    const parsed = JSON.parse(match[0]);
    return uniqueStrings(Array.isArray(parsed.selectors) ? parsed.selectors : []);
  } catch (_) {
    return [];
  }
}

async function runLlmIntentRecovery(ctx, entry) {
  const apiKey = process.env.ANTHROPIC_API_KEY || process.env.SKILL_LLM_API_KEY;
  if (!apiKey || !ctx || !ctx.page) return null;

  const [domResult, screenshotResult] = await Promise.allSettled([
    captureDomSnapshot(ctx.page),
    captureScreenshotBase64(ctx.page),
  ]);
  const dom = domResult.status === "fulfilled" ? domResult.value : "";
  const screenshot = screenshotResult.status === "fulfilled" ? screenshotResult.value : "";

  const prompt = [
    "Suggest Playwright selectors for recovering a failed browser automation step.",
    "Return only JSON: {\\"selectors\\":[\\"selector1\\",\\"selector2\\"]}.",
    "Prefer robust selectors: role selectors, text selectors, input attributes, aria labels, placeholders, data-testid.",
    `Error: ${truncateText(ctx.error || "", 2000)}`,
    `Recovery entry: ${truncateText(entry || {}, 4000)}`,
    `Current DOM summary: ${dom}`,
  ].join("\\n\\n");

  const content = [{ type: "text", text: prompt }];
  if (screenshot) {
    content.push({ type: "image", source: { type: "base64", media_type: "image/jpeg", data: screenshot } });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Number(process.env.CONXA_LLM_RECOVERY_TIMEOUT_MS) || 8000);
  try {
    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: process.env.ANTHROPIC_RECOVERY_MODEL || "claude-haiku-4-5-20251001",
        max_tokens: 200,
        messages: [{ role: "user", content }],
      }),
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const data = await response.json();
    const text = data.content && data.content[0] ? data.content[0].text || "" : "";
    const selectors = parseLlmSelectors(text);
    if (!selectors.length) return null;
    return {
      layer: 3,
      strategy: "selector_fallback",
      candidates: selectors,
      recovery_entry: entry,
    };
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function resolveVisualRef(ctx, entry) {
  const visualRef = entry && typeof entry.visual_ref === "string" ? entry.visual_ref.trim() : "";
  if (!visualRef) return "";
  if (path.isAbsolute(visualRef)) return visualRef;
  return path.join(skillDir(ctx && ctx.skill), visualRef);
}

async function runVisionRecovery(ctx, entry) {
  const page = ctx && ctx.page;
  const visualPath = resolveVisualRef(ctx, entry);
  if (!page || !visualPath || !fs.existsSync(visualPath)) return null;

  let current;
  try {
    current = ctx.currentScreenshot || await page.screenshot({ type: "png", scale: "css", fullPage: false, timeout: 2000 });
  } catch (_) {
    return null;
  }

  const target = entry && typeof entry.target === "object" ? entry.target : {};
  const fallback = entry && typeof entry.fallback === "object" ? entry.fallback : {};
  const payload = {
    currentDataUrl: `data:image/png;base64,${Buffer.from(current).toString("base64")}`,
    refDataUrl: `data:image/${path.extname(visualPath).toLowerCase() === ".png" ? "png" : "jpeg"};base64,${fs.readFileSync(visualPath).toString("base64")}`,
    targetText: typeof target.text === "string" ? target.text.trim() : "",
    targetRole: typeof target.role === "string" ? target.role.trim() : "",
    fallbackRole: typeof fallback.role === "string" ? fallback.role.trim() : "",
  };

  let candidates = [];
  try {
    candidates = await page.evaluate(async ({ currentDataUrl, refDataUrl, targetText, targetRole, fallbackRole }) => {
      const loadImage = (src) => new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = src;
      });
      const [current, reference] = await Promise.all([loadImage(currentDataUrl), loadImage(refDataUrl)]);
      const scale = Math.min(1, 180 / Math.max(current.width, current.height, reference.width, reference.height));
      const width = Math.max(1, Math.floor(Math.min(current.width, reference.width) * scale));
      const height = Math.max(1, Math.floor(Math.min(current.height, reference.height) * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width * 2;
      canvas.height = height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.drawImage(current, 0, 0, width, height);
      context.drawImage(reference, width, 0, width, height);
      const a = context.getImageData(0, 0, width, height).data;
      const b = context.getImageData(width, 0, width, height).data;
      const changed = new Uint8Array(width * height);
      for (let i = 0, p = 0; i < a.length; i += 4, p++) {
        changed[p] = Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]) > 42 ? 1 : 0;
      }

      const components = [];
      const queue = [];
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const start = y * width + x;
          if (!changed[start]) continue;
          changed[start] = 0;
          let minX = x, maxX = x, minY = y, maxY = y, count = 0;
          queue.length = 0;
          queue.push(start);
          for (let q = 0; q < queue.length; q++) {
            const idx = queue[q];
            const cx = idx % width;
            const cy = (idx / width) | 0;
            count++;
            if (cx < minX) minX = cx;
            if (cx > maxX) maxX = cx;
            if (cy < minY) minY = cy;
            if (cy > maxY) maxY = cy;
            const next = [idx - 1, idx + 1, idx - width, idx + width];
            for (const ni of next) {
              if (ni < 0 || ni >= changed.length || !changed[ni]) continue;
              const nx = ni % width;
              if ((ni === idx - 1 || ni === idx + 1) && Math.abs(nx - cx) !== 1) continue;
              changed[ni] = 0;
              queue.push(ni);
            }
          }
          if (count >= 6) components.push({ minX, maxX, minY, maxY, count });
        }
      }

      const needle = String(targetText || "").toLowerCase();
      const wantedRole = String(fallbackRole || targetRole || "").toLowerCase();
      const seen = new Set();
      const out = [];
      const add = (selector) => {
        if (selector && !seen.has(selector)) {
          seen.add(selector);
          out.push(selector);
        }
      };
      const attr = (value) => String(value).replace(/["\\\\]/g, "\\\\$&");
      const textOf = (el) => (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().replace(/\\s+/g, " ");
      const selectorsFor = (el) => {
        const tag = el.tagName.toLowerCase();
        const id = el.getAttribute("id");
        const testId = el.getAttribute("data-testid");
        const name = el.getAttribute("name");
        const aria = el.getAttribute("aria-label");
        const placeholder = el.getAttribute("placeholder");
        const text = textOf(el);
        if (id) add(`#${CSS.escape(id)}`);
        if (testId) add(`[data-testid="${attr(testId)}"]`);
        if (name) add(`${tag}[name="${attr(name)}"]`);
        if (aria) add(`${tag}[aria-label="${attr(aria)}"]`);
        if (placeholder) add(`${tag}[placeholder="${attr(placeholder)}"]`);
        if (wantedRole && text) add(`role=${wantedRole}[name="${attr(text)}"]`);
        if (text) add(`text=${JSON.stringify(text)}`);
      };
      const score = (el, component) => {
        if (!el || el === document.body || el === document.documentElement) return -1;
        const rect = el.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) return -1;
        const style = getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return -1;
        const text = textOf(el).toLowerCase();
        const role = (el.getAttribute("role") || el.tagName).toLowerCase();
        let value = component.count;
        if (needle && text.includes(needle)) value += 10000;
        if (wantedRole && role.includes(wantedRole)) value += 2000;
        if (/^(button|input|textarea|select|a)$/i.test(el.tagName)) value += 1000;
        return value;
      };

      const scaleX = current.width / width;
      const scaleY = current.height / height;
      components
        .sort((left, right) => right.count - left.count)
        .slice(0, 8)
        .map((component) => {
          const x = ((component.minX + component.maxX + 1) / 2) * scaleX;
          const y = ((component.minY + component.maxY + 1) / 2) * scaleY;
          let best = null;
          let bestScore = -1;
          for (const el of document.elementsFromPoint(x, y)) {
            for (let cur = el; cur && cur !== document.body; cur = cur.parentElement) {
              const value = score(cur, component);
              if (value > bestScore) {
                best = cur;
                bestScore = value;
              }
            }
          }
          return { best, bestScore };
        })
        .sort((left, right) => right.bestScore - left.bestScore)
        .forEach(({ best }) => {
          if (best) selectorsFor(best);
        });
      return out.slice(0, 12);
    }, payload);
  } catch (_) {
    return null;
  }

  const selectorCandidates = uniqueStrings(candidates);
  if (!selectorCandidates.length) return null;
  return {
    layer: 4,
    strategy: "selector_fallback",
    candidates: selectorCandidates,
    recovery_entry: entry,
  };
}

async function runLayer(layer, ctx) {
  tracker.send(`${ctx.skill}:${ctx.step}:${layer}`);
  const entry = getRecoveryEntry(ctx);
  switch (layer) {
    case 1:
      return runSelectorFallback(ctx, entry);
    case 2:
      return runAnchorFallback(ctx, entry);
    case 3:
      return runLlmIntentRecovery(ctx, entry);
    case 4:
      return runVisionRecovery(ctx, entry);
    default:
      throw new Error(`Unknown recovery layer: ${layer}`);
  }
}

async function runRecovery(ctx) {
  for (const layer of [1, 2, 3, 4]) {
    const result = await runLayer(layer, ctx);
    if (result) {
      return result;
    }
  }
  tracker.send(`${ctx.skill}:${ctx.step}:0`);
  throw new Error(`All recovery layers exhausted for ${ctx.skill}:${ctx.step}`);
}

module.exports = { runLayer, runRecovery };
"""

TRACKER_JS = """\
const TRACKER_URL = process.env.CONXA_TRACKER_URL || "";

// Fire-and-forget: never awaited, never throws.
function send(event) {
  if (!TRACKER_URL) return;
  try {
    fetch(TRACKER_URL, { method: "POST", body: String(event) }).catch(() => {});
  } catch (_) {}
}

module.exports = { send };
"""

VALIDATOR_JS = """\
const fs = require("fs");
const path = require("path");

function skillDir(name) {
  return path.join(__dirname, "..", "skills", name);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function validateInput(skillName, inputs) {
  const inputPath = path.join(skillDir(skillName), "input.json");
  if (!fs.existsSync(inputPath)) return;
  const schema = readJson(inputPath);
  if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) {
    throw new Error("Inputs must be an object");
  }

  for (const field of schema.inputs || []) {
    const name = field.name;
    const value = inputs[name];

    if (!field.optional && (value === undefined || value === null || value === "")) {
      throw new Error(`Missing required input: ${name}`);
    }
    if (value === undefined || value === null || value === "") continue;

    if (field.type) {
      const actual = Array.isArray(value) ? "array" : typeof value;
      if (field.type === "integer") {
        if (!Number.isInteger(value)) throw new Error(`Invalid input type for ${name}: expected integer`);
      } else if (field.type === "array") {
        if (!Array.isArray(value)) throw new Error(`Invalid input type for ${name}: expected array`);
      } else if (field.type === "object") {
        if (actual !== "object" || Array.isArray(value)) {
          throw new Error(`Invalid input type for ${name}: expected object`);
        }
      } else if (actual !== field.type) {
        throw new Error(`Invalid input type for ${name}: expected ${field.type}`);
      }
    }

    const allowed = field.enum || field.options;
    if (allowed && !allowed.includes(value)) {
      throw new Error(`Invalid input value for ${name}: expected one of ${allowed.join(", ")}`);
    }

    if (typeof value === "string") {
      if (field.minLength !== undefined && value.length < field.minLength) {
        throw new Error(`Invalid input length for ${name}: minimum ${field.minLength}`);
      }
      if (field.maxLength !== undefined && value.length > field.maxLength) {
        throw new Error(`Invalid input length for ${name}: maximum ${field.maxLength}`);
      }
      if (field.pattern && !(new RegExp(field.pattern).test(value))) {
        throw new Error(`Invalid input format for ${name}`);
      }
    }
  }
}

function validateOutput(skillName, output) {
  if (!output || typeof output !== "object" || Array.isArray(output)) {
    throw new Error("Output must be an object");
  }
  if (output.skill !== skillName) {
    throw new Error(`Output skill mismatch: expected ${skillName}`);
  }
  if (typeof output.passed !== "boolean") {
    throw new Error("Output field 'passed' must be boolean");
  }
  if (!Array.isArray(output.steps)) {
    throw new Error("Output field 'steps' must be an array");
  }
  if (!output.summary || typeof output.summary !== "object" || Array.isArray(output.summary)) {
    throw new Error("Output field 'summary' must be an object");
  }

  const counts = { ok: 0, recovered: 0, failed: 0 };
  const allowedStatuses = new Set(["ok", "recovered", "failed"]);
  for (let i = 0; i < output.steps.length; i++) {
    const step = output.steps[i];
    if (!step || typeof step !== "object" || Array.isArray(step)) {
      throw new Error(`Output step ${i + 1} must be an object`);
    }
    if (step.step !== i + 1) {
      throw new Error(`Output step ${i + 1} has invalid step number`);
    }
    if (typeof step.type !== "string" || step.type === "") {
      throw new Error(`Output step ${i + 1} missing type`);
    }
    if (!allowedStatuses.has(step.status)) {
      throw new Error(`Output step ${i + 1} has invalid status`);
    }
    if (typeof step.latency_ms !== "number" || step.latency_ms < 0) {
      throw new Error(`Output step ${i + 1} has invalid latency_ms`);
    }
    counts[step.status]++;
  }

  const summary = output.summary;
  if (
    summary.total !== output.steps.length ||
    summary.ok !== counts.ok ||
    summary.recovered !== counts.recovered ||
    summary.failed !== counts.failed
  ) {
    throw new Error("Output summary does not match steps");
  }
  if (output.passed !== (counts.failed === 0)) {
    throw new Error("Output field 'passed' does not match failed step count");
  }

  const outputPath = path.join(skillDir(skillName), "output.json");
  if (!fs.existsSync(outputPath)) return;
  const schema = readJson(outputPath);
  for (const field of schema.outputs || []) {
    if (!field.optional && output[field.name] === undefined) {
      throw new Error(`Missing required output: ${field.name}`);
    }
  }
}

module.exports = { validateInput, validateOutput };
"""

ORCHESTRATION_SCHEMA_JSON = json.dumps(
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ExecutionPlan",
        "type": "array",
        "items": {
            "type": "object",
            "required": ["skill"],
            "properties": {
                "skill": {"type": "string", "description": "Skill name from plugin index"},
                "inputs": {
                    "type": "object",
                    "description": "Input values for the skill",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
    },
    ensure_ascii=False,
    indent=2,
)


def orchestration_index_md(plugin_name: str, plugin_slug: str, skill_names: list[str]) -> str:
    skill_list = "\n".join(f"- `{s}`" for s in skill_names) if skill_names else "- (none yet)"
    return (
        f"# {plugin_name} Plugin - Orchestration Guide\n\n"
        "## Entry Point\n\n"
        f"Start from `../{plugin_slug}.json` - the machine-readable index of all available skills.\n\n"
        "## How to Use\n\n"
        f"1. Read `../{plugin_slug}.json` to see all available skills and their inputs\n"
        "2. Pick the skill(s) that match the user's request\n"
        "3. Read `planner.md` for how to sequence skills and gather inputs\n"
        "4. Return a plan matching `schema.json` so `../execution/executor.js` can run it\n\n"
        "## Available Skills\n\n"
        f"{skill_list}\n"
    )


def orchestration_planner_md(plugin_slug: str) -> str:
    return (
        "# Planner Guide\n\n"
        "## Your Job\n\n"
        "Convert a user request into a JSON plan that `../execution/executor.js` can execute.\n\n"
        "## Steps\n\n"
        f"1. Read `../{plugin_slug}.json` to see available skills\n"
        "2. Identify which skill(s) the user needs (one or more, in order)\n"
        "3. For each chosen skill, read `../skills/<skill-name>/input.json` for required inputs\n"
        "4. Ask the user for any missing inputs - ask once, not repeatedly\n"
        "5. Return ONLY the JSON plan matching `schema.json`, no explanations\n\n"
        "## Rules\n\n"
        f"* ONLY use skills listed in `../{plugin_slug}.json`\n"
        "* DO NOT invent or guess skill names\n"
        "* DO NOT output anything outside the JSON plan\n"
        "* Recovery is automatic - do not plan for failure explicitly\n"
    )
