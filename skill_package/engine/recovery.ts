/**
 * Recovery map produced by the skill pack builder (`recovery.json`).
 * Used to propose alternate locators when the primary selector fails.
 */

import { readFile } from "fs/promises";
import type { SkillEngineConfig } from "./config";
import type { Logger } from "./logging";

export interface RecoveryFallback {
  text_variants: string[];
  visual_hint: string;
}

export interface RecoveryStep {
  step_id: number;
  intent: string;
  target: { text: string; type: string; section: string };
  anchors: string[];
  fallback: RecoveryFallback;
}

export interface RecoveryMap {
  steps: RecoveryStep[];
}

const TEXT_SELECTOR = /^\s*text\s*=\s*(.+)\s*$/i;

function stripQuotes(raw: string): string {
  const t = raw.trim();
  if (
    (t.startsWith('"') && t.endsWith('"')) ||
    (t.startsWith("'") && t.endsWith("'"))
  ) {
    return t.slice(1, -1);
  }
  return t;
}

export function parseRecoveryMap(raw: string): RecoveryMap {
  const data = JSON.parse(raw) as RecoveryMap;
  if (!data || typeof data !== "object" || !Array.isArray(data.steps)) {
    throw new Error("recovery.json must be an object with a steps array.");
  }
  return data;
}

export function recoveryForStepId(
  map: RecoveryMap,
  stepIndex1Based: number
): RecoveryStep | undefined {
  return map.steps.find((s) => s.step_id === stepIndex1Based);
}

/** Build extra `text=…` locators from recovery hints (only when the primary is text-based). */
export function alternativeTextSelectors(
  primarySelector: string,
  rec: RecoveryStep | undefined
): string[] {
  if (!rec?.fallback?.text_variants?.length) return [];
  const m = TEXT_SELECTOR.exec(primarySelector.trim());
  if (!m) return [];

  const out: string[] = [];
  const seen = new Set<string>();
  for (const variant of rec.fallback.text_variants) {
    const label = stripQuotes(String(variant)).trim();
    if (!label) continue;
    const sel = `text=${JSON.stringify(label)}`;
    if (!seen.has(sel)) {
      seen.add(sel);
      out.push(sel);
    }
  }
  return out;
}

export function anchorSelectors(rec: RecoveryStep | undefined): string[] {
  if (!rec?.anchors?.length) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const anchor of rec.anchors) {
    const label = stripQuotes(String(anchor)).trim();
    if (!label || label.toLowerCase() === "bottom") continue;
    const sel = `text=${JSON.stringify(label)}`;
    if (!seen.has(sel)) {
      seen.add(sel);
      out.push(sel);
    }
  }
  return out;
}

async function readRecoveryMap(path: string | undefined, log: Logger): Promise<RecoveryMap> {
  if (!path) return { steps: [] };
  try {
    return parseRecoveryMap(await readFile(path, "utf8"));
  } catch (err) {
    log.warn("recovery.json unavailable; deterministic recovery skipped", {
      path,
      error: String(err),
    });
    return { steps: [] };
  }
}

export async function recoverLocatorAction(args: {
  recoveryPath?: string;
  stepId: number;
  primarySelector: string;
  config: SkillEngineConfig;
  log: Logger;
  skillMarkdownPath?: string;
  run: (selector: string) => Promise<void>;
  error: unknown;
}): Promise<void> {
  const recovery = await readRecoveryMap(args.recoveryPath, args.log);
  const rec = recoveryForStepId(recovery, args.stepId);
  const deterministic = [
    args.primarySelector,
    ...alternativeTextSelectors(args.primarySelector, rec),
    ...anchorSelectors(rec),
  ];

  let last: unknown = args.error;
  for (let i = 0; i < deterministic.length; i++) {
    const selector = deterministic[i];
    try {
      await args.run(selector);
      args.log.info("step recovered deterministically", {
        step: args.stepId,
        selector,
        attempt: i + 1,
      });
      return;
    } catch (err) {
      last = err;
      args.log.warn("recovery selector failed", {
        step: args.stepId,
        selector,
        attempt: i + 1,
        error: String(err),
      });
    }
  }

  if (args.config.enableLlmRecoveryAssist && args.config.llmRecoveryEndpoint?.trim()) {
    let skillMarkdown = "";
    if (args.skillMarkdownPath) {
      try {
        skillMarkdown = await readFile(args.skillMarkdownPath, "utf8");
      } catch (err) {
        args.log.warn("skill.md fallback context unavailable", {
          path: args.skillMarkdownPath,
          error: String(err),
        });
      }
    }
    const hinted = await maybeLlmRecoveryAssist({
      endpoint: args.config.llmRecoveryEndpoint,
      primarySelector: args.primarySelector,
      errorMessage: String(last),
      visualHint: rec?.fallback?.visual_hint ?? "",
      skillMarkdown,
    });
    for (const selector of hinted) {
      try {
        await args.run(selector);
        args.log.info("step recovered via LLM fallback", {
          step: args.stepId,
          selector,
        });
        return;
      } catch (err) {
        last = err;
      }
    }
  }

  throw last instanceof Error ? last : new Error(String(last));
}

/** Placeholder for optional LLM assist (see `config.ts`). Not implemented in the open-source engine. */
export async function maybeLlmRecoveryAssist(_args: {
  endpoint?: string;
  primarySelector: string;
  errorMessage: string;
  visualHint: string;
  skillMarkdown?: string;
}): Promise<string[]> {
  return [];
}
