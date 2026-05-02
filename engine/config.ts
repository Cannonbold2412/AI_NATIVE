/**
 * Runtime tuning for the skill-package Playwright engine.
 * LLM-assisted recovery is intentionally off by default — enable only in trusted environments.
 */

export type SkillEngineLogLevel = "debug" | "info" | "warn" | "error";

export interface SkillEngineLoggingConfig {
  enabled: boolean;
  directory: string;
  console: boolean;
}

export interface SkillEngineConfig {
  /** Timeout for each locator action (fill, click, visibility). */
  stepTimeoutMs: number;
  /** Timeout for page.goto. */
  navigationTimeoutMs: number;
  /** Timeout for assert_visible waits. */
  assertionTimeoutMs: number;
  /** How many attempts to make with the primary locator before trying recovery alternates (default 2 = initial try + one retry). */
  sameLocatorAttempts: number;
  enableLlmRecoveryAssist: boolean;
  llmRecoveryEndpoint?: string;
  logLevel: SkillEngineLogLevel;
  logging: SkillEngineLoggingConfig;
}

export type SkillEngineConfigOverrides = Partial<Omit<SkillEngineConfig, "logging">> & {
  logging?: Partial<SkillEngineLoggingConfig>;
};

export const defaultSkillEngineConfig: SkillEngineConfig = {
  stepTimeoutMs: 30_000,
  navigationTimeoutMs: 60_000,
  assertionTimeoutMs: 15_000,
  sameLocatorAttempts: 2,
  enableLlmRecoveryAssist: false,
  llmRecoveryEndpoint: undefined,
  logLevel: "info",
  logging: {
    enabled: true,
    directory: "./runtime/logs",
    console: true,
  },
};

export function resolveSkillEngineConfig(
  overrides?: SkillEngineConfigOverrides
): SkillEngineConfig {
  const merged: SkillEngineConfig = {
    ...defaultSkillEngineConfig,
    ...overrides,
    logging: {
      ...defaultSkillEngineConfig.logging,
      ...(overrides?.logging ?? {}),
    },
  };
  merged.sameLocatorAttempts = Math.max(1, merged.sameLocatorAttempts);
  return merged;
}
