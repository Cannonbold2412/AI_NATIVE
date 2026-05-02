/** Structured console and run-file logging for skill-package execution (no external deps). */

import { mkdir, writeFile } from "fs/promises";
import { join } from "path";
import { defaultSkillEngineConfig, type SkillEngineConfig } from "./config";

export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

export interface LoggerOptions {
  namespace?: string;
  minLevel?: LogLevel;
}

export interface Logger {
  debug(message: string, meta?: Record<string, unknown>): void;
  info(message: string, meta?: Record<string, unknown>): void;
  warn(message: string, meta?: Record<string, unknown>): void;
  error(message: string, meta?: Record<string, unknown>): void;
}

export interface StepLogEntry {
  step: number;
  action: string;
  status: "success" | "failed";
  error?: string;
  timestamp: string;
}

export interface FinalRunLog {
  workflow: string;
  status: "success" | "failed";
  steps: StepLogEntry[];
}

export function logStep(
  data: object,
  config: SkillEngineConfig = defaultSkillEngineConfig
): void {
  if (!config.logging.enabled) return;
  if (config.logging.console) {
    console.log(JSON.stringify(data));
  }
}

function runLogFilename(): string {
  return `run_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
}

export function createRunLogger(workflow: string, config: SkillEngineConfig) {
  const steps: StepLogEntry[] = [];

  return {
    step(data: Omit<StepLogEntry, "timestamp"> & { timestamp?: string }): void {
      const entry: StepLogEntry = {
        ...data,
        timestamp: data.timestamp ?? new Date().toISOString(),
      };
      steps.push(entry);
      logStep(entry, config);
    },
    async flush(status: "success" | "failed"): Promise<void> {
      if (!config.logging.enabled) return;
      const finalLog: FinalRunLog = { workflow, status, steps };
      await mkdir(config.logging.directory, { recursive: true });
      await writeFile(
        join(config.logging.directory, runLogFilename()),
        `${JSON.stringify(finalLog, null, 2)}\n`,
        "utf8"
      );
    },
  };
}

function emit(level: LogLevel, line: string, meta?: Record<string, unknown>): void {
  if (meta !== undefined) {
    const fn =
      level === "debug"
        ? console.debug
        : level === "info"
          ? console.info
          : level === "warn"
            ? console.warn
            : console.error;
    fn(line, meta);
  } else if (level === "debug") {
    console.debug(line);
  } else if (level === "info") {
    console.info(line);
  } else if (level === "warn") {
    console.warn(line);
  } else {
    console.error(line);
  }
}

export function createLogger(options: LoggerOptions = {}): Logger {
  const min = options.minLevel ?? "info";
  const prefix = options.namespace ? `[${options.namespace}] ` : "";

  function log(level: LogLevel, message: string, meta?: Record<string, unknown>): void {
    if (LEVEL_ORDER[level] < LEVEL_ORDER[min]) return;
    emit(level, `${prefix}[${level}] ${message}`, meta);
  }

  return {
    debug: (message, meta) => log("debug", message, meta),
    info: (message, meta) => log("info", message, meta),
    warn: (message, meta) => log("warn", message, meta),
    error: (message, meta) => log("error", message, meta),
  };
}
