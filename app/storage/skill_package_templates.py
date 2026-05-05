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
        const alt = await applyRecovery(page, { skill, step: stepIdx, error: String(err) });
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
        const alt = await applyRecovery(page, { skill, step: stepIdx, error: String(err) });
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
        const alt = await applyRecovery(page, { skill, step: stepIdx, error: String(err) });
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

async function runLayer(layer, ctx) {
  tracker.send(`${ctx.skill}:${ctx.step}:${layer}`);
  const entry = getRecoveryEntry(ctx);
  switch (layer) {
    case 1:
      return runSelectorFallback(ctx, entry);
    case 2:
      return runAnchorFallback(ctx, entry);
    case 3:
      // TODO: call LLM with error + current DOM/screenshot to suggest an alternative action
      return null;
    case 4:
      // TODO: compare current screenshot to recovery_entry.visual_ref and find the moved element
      return null;
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
  // TODO: validate inputs against skills/{skillName}/input.json schema
  const inputPath = path.join(skillDir(skillName), "input.json");
  if (!fs.existsSync(inputPath)) return;
  const schema = readJson(inputPath);
  for (const field of schema.inputs || []) {
    if (!field.optional && (inputs[field.name] === undefined || inputs[field.name] === "")) {
      throw new Error(`Missing required input: ${field.name}`);
    }
  }
}

function validateOutput(skillName, output) {
  // TODO: validate output shape after skill completes
  void skillName, output;
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
