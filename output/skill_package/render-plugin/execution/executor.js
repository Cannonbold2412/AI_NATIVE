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
  return value.replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (_, key) => String(inputs[key] ?? ""));
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
    await page.locator(selector).waitFor({ state: "attached", timeout: timeout || 5000 });
    return true;
  } catch (_) {
    return false;
  }
}

async function applyRecovery(page, ctx) {
  let plan;
  try {
    plan = await recovery.runRecovery(ctx);
  } catch (_) {
    return null;
  }
  const candidates = [];
  if (plan && plan.strategy === "selector_fallback" && Array.isArray(plan.candidates)) {
    candidates.push(...plan.candidates);
  } else if (plan && plan.strategy === "anchor_fallback" && Array.isArray(plan.anchors)) {
    const sorted = plan.anchors.slice().sort((a, b) => b.priority - a.priority);
    for (const anchor of sorted) {
      candidates.push(`text=${JSON.stringify(anchor.text)}`);
    }
  }
  for (const sel of candidates) {
    if (await trySelector(page, sel, 3000)) return sel;
  }
  return null;
}

async function dispatchStep(page, step, inputs, skill, stepIdx) {
  const type = step.type;
  const sel = interpolate(step.selector || "", inputs);
  const start = Date.now();
  const row = { step: stepIdx, type, selector: sel };

  try {
    if (type === "navigate") {
      const url = interpolate(step.url || "", inputs);
      await page.goto(url, { timeout: 15000, waitUntil: "domcontentloaded" });
      row.status = "ok";
    } else if (type === "scroll") {
      await page.evaluate(`window.scrollBy(0, ${Number(step.delta_y) || 0})`);
      row.status = "ok";
    } else if (type === "fill") {
      const value = interpolate(step.value || "", inputs);
      try {
        await page.locator(sel).first().fill(value, { timeout: 5000 });
        row.status = "ok";
      } catch (err) {
        const alt = await applyRecovery(page, { skill, step: stepIdx, error: String(err), page });
        if (alt) {
          await page.locator(alt).first().fill(value, { timeout: 5000 });
          row.status = "recovered"; row.recovered_via = alt;
        } else { throw err; }
      }
    } else if (type === "click") {
      try {
        await page.locator(sel).first().click({ timeout: 5000 });
        row.status = "ok";
      } catch (err) {
        const alt = await applyRecovery(page, { skill, step: stepIdx, error: String(err), page });
        if (alt) {
          await page.locator(alt).first().click({ timeout: 5000 });
          row.status = "recovered"; row.recovered_via = alt;
        } else { throw err; }
      }
    } else if (type === "assert_visible") {
      try {
        await page.locator(sel).waitFor({ state: "visible", timeout: 5000 });
        row.status = "ok";
      } catch (err) {
        const alt = await applyRecovery(page, { skill, step: stepIdx, error: String(err), page });
        if (alt) {
          await page.locator(alt).waitFor({ state: "visible", timeout: 5000 });
          row.status = "recovered"; row.recovered_via = alt;
        } else { throw err; }
      }
    } else {
      throw new Error(`Unknown step type: ${type}`);
    }
  } catch (err) {
    row.status = "failed";
    row.error = String(err).split("\n")[0].slice(0, 300);
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
  const browser = await chromium.launch({ headless });
  const context = await browser.newContext();
  const page = await context.newPage();

  const rows = [];
  console.log(`[executor] skill=${skill} steps=${steps.length}`);

  for (let i = 0; i < steps.length; i++) {
    const stepIdx = i + 1;
    process.stdout.write(`[executor] step ${stepIdx}/${steps.length} type=${steps[i].type} ... `);
    const row = await dispatchStep(page, steps[i], inputs, skill, stepIdx);
    rows.push(row);
    console.log(row.status + (row.recovered_via ? ` (via ${row.recovered_via})` : ""));
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
    const headless = args.headless !== "0";
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

  const headless = args.headless !== "0";

  const { passed } = await runSingleSkill(skill, inputs, resultPath, headless);
  process.exit(passed ? 0 : 1);
}

main().catch(err => {
  console.error("[executor] fatal:", err.message || err);
  process.exit(1);
});
