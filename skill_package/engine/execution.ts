/**
 * Executes `execution.json` steps on a Playwright `Page`, using `recovery.json` for locator fallbacks.
 */

import { dirname, resolve } from "path";
import { readFile } from "fs/promises";
import type { Page } from "playwright";
import {
  resolveSkillEngineConfig,
  type SkillEngineConfig,
  type SkillEngineConfigOverrides,
} from "./config";
import { createLogger, createRunLogger } from "./logging";
import {
  recoverLocatorAction,
} from "./recovery";

const VAR_PATTERN = /\{\{\s*([^{}]+?)\s*\}\}/g;
type RuntimeInputs = Record<string, string | number | boolean | null | undefined>;

export type ExecutionStep =
  | { type: "navigate"; url: string }
  | { type: "fill"; selector: string; value: string }
  | { type: "click"; selector: string }
  | {
      type: "scroll";
      selector?: string;
      delta_y?: number;
      delta_x?: number;
    }
  | { type: "assert_visible"; selector: string };

export interface WorkflowIndexEntry {
  name: string;
  description: string;
  manifest: string;
}

export interface SkillPackageIndex {
  workflows: WorkflowIndexEntry[];
}

export interface WorkflowManifest {
  name: string;
  description: string;
  version: string;
  entry: {
    execution: string;
    recovery: string;
    inputs: string;
  };
  execution_mode: "deterministic";
  llm_required: false;
  inputs?: Array<{ name: string; type?: string; sensitive?: boolean }>;
}

export interface ExecuteWorkflowOptions {
  page: Page;
  executionPath: string;
  recoveryPath?: string;
  /** Runtime values for `{{placeholder}}` substitution in URLs, values, and selectors. */
  inputs?: Record<string, string | number | boolean | null | undefined>;
  workflowName?: string;
  skillMarkdownPath?: string;
  /** Optional engine overrides (timeouts, logging, experimental LLM recovery). */
  config?: SkillEngineConfigOverrides;
}

export interface ExecuteWorkflowFromManifestOptions {
  page: Page;
  manifestPath: string;
  inputs?: Record<string, string | number | boolean | null | undefined>;
  config?: SkillEngineConfigOverrides;
}

export interface ExecuteWorkflowForPromptOptions {
  page: Page;
  indexPath: string;
  prompt: string;
  inputs?: Record<string, string | number | boolean | null | undefined>;
  config?: SkillEngineConfigOverrides;
}

function interpolate(template: string, inputs: RuntimeInputs): string {
  return template.replace(VAR_PATTERN, (_m, rawKey: string) => {
    const key = String(rawKey).trim();
    if (!Object.prototype.hasOwnProperty.call(inputs, key)) {
      throw new Error(`Missing input "${key}" for placeholder in template.`);
    }
    const v = inputs[key];
    return v === null || v === undefined ? "" : String(v);
  });
}

function interpolateStep(
  step: ExecutionStep,
  inputs: RuntimeInputs
): ExecutionStep {
  if (step.type === "navigate") {
    return { type: "navigate", url: interpolate(step.url, inputs) };
  }
  if (step.type === "fill") {
    return {
      type: "fill",
      selector: interpolate(step.selector, inputs),
      value: interpolate(step.value, inputs),
    };
  }
  if (step.type === "click") {
    return { type: "click", selector: interpolate(step.selector, inputs) };
  }
  if (step.type === "scroll") {
    const out: ExecutionStep = { type: "scroll" };
    if (step.selector?.trim())
      out.selector = interpolate(step.selector.trim(), inputs);
    if (step.delta_y !== undefined) out.delta_y = step.delta_y;
    if (step.delta_x !== undefined) out.delta_x = step.delta_x;
    return out;
  }
  return { type: "assert_visible", selector: interpolate(step.selector, inputs) };
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function runScrollStep(
  page: Page,
  step: Extract<ExecutionStep, { type: "scroll" }>,
  timeout: number,
  log: ReturnType<typeof createLogger>
): Promise<void> {
  const sel = step.selector?.trim();
  const dy = step.delta_y ?? 0;
  const dx = step.delta_x ?? 0;

  if (sel) {
    await page.locator(sel).scrollIntoViewIfNeeded({ timeout });
    log.info("scroll into view", { selector: sel });
  }
  if (dx !== 0 || dy !== 0) {
    await page.mouse.wheel(dx, dy);
    log.info("scroll wheel", { delta_x: dx, delta_y: dy });
  }
}

async function runNavigate(
  page: Page,
  url: string,
  timeout: number,
  log: ReturnType<typeof createLogger>
): Promise<void> {
  let last: unknown;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await page.goto(url, { timeout, waitUntil: "domcontentloaded" });
      log.info("navigate ok", { url });
      return;
    } catch (err) {
      last = err;
      log.warn("navigate failed", { url, attempt, error: String(err) });
      if (attempt === 0) await sleep(300);
    }
  }
  throw last instanceof Error ? last : new Error(String(last));
}

function parseExecutionPlan(raw: string): ExecutionStep[] {
  const data = JSON.parse(raw) as unknown;
  if (!Array.isArray(data)) {
    throw new Error("execution.json must be a JSON array of step objects.");
  }
  const out: ExecutionStep[] = [];
  for (const item of data) {
    if (!item || typeof item !== "object") {
      throw new Error("execution.json steps must be objects.");
    }
    const rec = item as Record<string, unknown>;
    const t = String(rec.type || "").trim();
    if (t === "navigate") {
      out.push({
        type: "navigate",
        url: String(rec.url ?? ""),
      });
      continue;
    }
    if (t === "fill") {
      out.push({
        type: "fill",
        selector: String(rec.selector ?? ""),
        value: String(rec.value ?? ""),
      });
      continue;
    }
    if (t === "click") {
      out.push({ type: "click", selector: String(rec.selector ?? "") });
      continue;
    }
    if (t === "assert_visible") {
      out.push({ type: "assert_visible", selector: String(rec.selector ?? "") });
      continue;
    }
    if (t === "scroll") {
      const rawSel = rec.selector;
      const selector =
        typeof rawSel === "string" && rawSel.trim() !== "" ? rawSel.trim() : undefined;

      let delta_y: number | undefined;
      if (rec.delta_y !== undefined && rec.delta_y !== null && `${rec.delta_y}`.trim() !== "") {
        const n = Number(rec.delta_y);
        if (Number.isNaN(n)) throw new Error("scroll delta_y must be a number.");
        delta_y = n;
      }

      let delta_x = 0;
      if (rec.delta_x !== undefined && rec.delta_x !== null && `${rec.delta_x}`.trim() !== "") {
        const n = Number(rec.delta_x);
        if (Number.isNaN(n)) throw new Error("scroll delta_x must be a number.");
        delta_x = n;
      }

      const hasSel = !!selector;
      const hasWheel = (delta_y !== undefined && delta_y !== 0) || delta_x !== 0;
      if (!hasSel && !hasWheel) {
        throw new Error("scroll step requires selector and/or non-zero delta_y / delta_x.");
      }

      const scrollStep: ExecutionStep = { type: "scroll" };
      if (selector) scrollStep.selector = selector;
      if (delta_y !== undefined) scrollStep.delta_y = delta_y;
      if (delta_x !== 0) scrollStep.delta_x = delta_x;
      out.push(scrollStep);
      continue;
    }
    throw new Error(`Unsupported step type in execution.json: ${t}`);
  }
  return out;
}

function parseManifest(raw: string): WorkflowManifest {
  const data = JSON.parse(raw) as Partial<WorkflowManifest>;
  if (!data || typeof data !== "object") {
    throw new Error("manifest.json must be a JSON object.");
  }
  if (!data.name || !data.entry?.execution || !data.entry?.recovery || !data.entry?.inputs) {
    throw new Error("manifest.json is missing required name or entry paths.");
  }
  if (data.execution_mode !== "deterministic" || data.llm_required !== false) {
    throw new Error("Only deterministic, non-LLM workflow manifests can be executed directly.");
  }
  return data as WorkflowManifest;
}

function parseIndex(raw: string): SkillPackageIndex {
  const data = JSON.parse(raw) as SkillPackageIndex;
  if (!data || typeof data !== "object" || !Array.isArray(data.workflows)) {
    throw new Error("index.json must be an object with a workflows array.");
  }
  return data;
}

function resolveEntryPath(baseDir: string, entryPath: string): string {
  return resolve(baseDir, entryPath);
}

function resolveManifestFromIndex(indexPath: string, manifest: string): string {
  const root = dirname(indexPath);
  if (manifest.startsWith("/skills/")) {
    const parts = manifest.split("/").filter(Boolean);
    const workflow = parts[1];
    return resolve(root, "workflows", workflow, "manifest.json");
  }
  return resolve(root, manifest);
}

function scoreWorkflow(prompt: string, workflow: WorkflowIndexEntry): number {
  const haystack = `${workflow.name} ${workflow.description}`.toLowerCase();
  const tokens = prompt
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length > 1);
  let score = 0;
  for (const token of tokens) {
    if (haystack.includes(token)) score += 1;
  }
  if (haystack.includes(prompt.toLowerCase().trim())) score += 5;
  return score;
}

export function selectWorkflowForPrompt(
  index: SkillPackageIndex,
  prompt: string
): WorkflowIndexEntry {
  if (index.workflows.length === 0) {
    throw new Error("index.json does not contain any workflows.");
  }
  const ranked = [...index.workflows].sort(
    (a, b) => scoreWorkflow(prompt, b) - scoreWorkflow(prompt, a)
  );
  return ranked[0];
}

async function validateInputsIfDeclared(
  inputsPath: string,
  inputs: RuntimeInputs
): Promise<void> {
  const raw = await readFile(inputsPath, "utf8");
  const data = JSON.parse(raw) as unknown;
  const declared = Array.isArray(data)
    ? data
    : data && typeof data === "object" && Array.isArray((data as { inputs?: unknown }).inputs)
      ? (data as { inputs: unknown[] }).inputs
      : [];
  const missing: string[] = [];
  for (const item of declared) {
    if (!item || typeof item !== "object") continue;
    const name = String((item as { name?: unknown }).name ?? "").trim();
    if (!name) continue;
    if (!Object.prototype.hasOwnProperty.call(inputs, name) || inputs[name] === undefined) {
      missing.push(name);
    }
  }
  if (missing.length) {
    throw new Error(`Missing workflow input(s): ${missing.join(", ")}.`);
  }
}

async function runLocatorStep(
  page: Page,
  step: Extract<ExecutionStep, { selector: string }>,
  timeout: number
): Promise<void> {
  const loc = page.locator(step.selector);
  if (step.type === "fill") {
    await loc.fill(step.value, { timeout });
    return;
  }
  if (step.type === "click") {
    await loc.click({ timeout });
    return;
  }
  await loc.waitFor({ state: "visible", timeout });
}

async function runStep(
  options: ExecuteWorkflowOptions,
  step: ExecutionStep,
  stepId: number,
  cfg: SkillEngineConfig,
  log: ReturnType<typeof createLogger>
): Promise<void> {
  const { page } = options;
  if (step.type === "navigate") {
    await runNavigate(page, step.url, cfg.navigationTimeoutMs, log);
    return;
  }

  if (step.type === "scroll") {
    const dy = step.delta_y ?? 0;
    const dx = step.delta_x ?? 0;
    if (!step.selector?.trim() && dx === 0 && dy === 0) {
      throw new Error(
        `Step ${stepId}: scroll has no selector and no wheel delta; check execution.json.`
      );
    }
    await runScrollStep(page, step, cfg.stepTimeoutMs, log);
    return;
  }

  const timeout = step.type === "assert_visible" ? cfg.assertionTimeoutMs : cfg.stepTimeoutMs;
  try {
    await runLocatorStep(page, step, timeout);
  } catch (err) {
    log.warn("primary selector failed; loading recovery.json", {
      step: stepId,
      selector: step.selector,
      error: String(err),
    });
    await recoverLocatorAction({
      recoveryPath: options.recoveryPath,
      stepId,
      primarySelector: step.selector,
      config: cfg,
      log,
      skillMarkdownPath: options.skillMarkdownPath,
      run: async (selector) => {
        await runLocatorStep(page, { ...step, selector }, timeout);
      },
      error: err,
    });
  }
}

export async function executeWorkflowFromManifest(
  options: ExecuteWorkflowFromManifestOptions
): Promise<void> {
  const manifest = parseManifest(await readFile(options.manifestPath, "utf8"));
  const baseDir = dirname(options.manifestPath);
  const inputs = options.inputs ?? {};
  const inputsPath = resolveEntryPath(baseDir, manifest.entry.inputs);
  await validateInputsIfDeclared(inputsPath, inputs);
  await executeWorkflow({
    page: options.page,
    workflowName: manifest.name,
    executionPath: resolveEntryPath(baseDir, manifest.entry.execution),
    recoveryPath: resolveEntryPath(baseDir, manifest.entry.recovery),
    skillMarkdownPath: resolveEntryPath(baseDir, "./skill.md"),
    inputs,
    config: options.config,
  });
}

export async function executeWorkflowForPrompt(
  options: ExecuteWorkflowForPromptOptions
): Promise<void> {
  const index = parseIndex(await readFile(options.indexPath, "utf8"));
  const workflow = selectWorkflowForPrompt(index, options.prompt);
  await executeWorkflowFromManifest({
    page: options.page,
    manifestPath: resolveManifestFromIndex(options.indexPath, workflow.manifest),
    inputs: options.inputs ?? {},
    config: options.config,
  });
}

export async function executeWorkflow(options: ExecuteWorkflowOptions): Promise<void> {
  const cfg = resolveSkillEngineConfig(options.config);
  const log = createLogger({
    namespace: "skill-pack",
    minLevel: cfg.logLevel,
  });
  const workflowName = options.workflowName ?? "workflow";
  const runLog = createRunLogger(workflowName, cfg);

  const execRaw = await readFile(options.executionPath, "utf8");
  const inputs = options.inputs ?? {};
  const plan = parseExecutionPlan(execRaw).map((s) => interpolateStep(s, inputs));

  log.info("execution start", { steps: plan.length });

  try {
    for (let i = 0; i < plan.length; i++) {
      const step = plan[i];
      const stepId = i + 1;
      log.info(`step ${stepId}/${plan.length}`, { type: step.type });
      try {
        await runStep(options, step, stepId, cfg, log);
        runLog.step({ step: stepId, action: step.type, status: "success" });
      } catch (err) {
        runLog.step({
          step: stepId,
          action: step.type,
          status: "failed",
          error: String(err),
        });
        throw err;
      }
    }
    await runLog.flush("success");
  } catch (err) {
    await runLog.flush("failed");
    throw err;
  }

  log.info("execution complete");
}
