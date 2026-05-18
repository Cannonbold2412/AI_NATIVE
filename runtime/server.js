#!/usr/bin/env node
"use strict";
const path   = require("path");
const fs     = require("fs");
const os     = require("os");
const https  = require("https");
const semver = require("semver");

// ─── 1. Resolve CONXA_DIR ─────────────────────────────────────────────────────
const CONXA_DIR = process.env.CONXA_DIR || (
  process.platform === "win32"
    ? "C:\\Program Files\\Conxa"
    : path.join(os.homedir(), ".conxa")
);

const SKILL_PACKS_DIR = path.join(CONXA_DIR, "skill-packs");
const CACHE_DIR       = path.join(CONXA_DIR, "cache");
const SESSIONS_DIR    = path.join(CACHE_DIR, "sessions");
const LOG_FILE        = path.join(CONXA_DIR, "logs", "runtime.log");
const RUNTIME_VERSION = require("./package.json").version;

// ─── 2. Playwright browser path (MUST precede any playwright require) ─────────
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(CONXA_DIR, "chromium");
// Override session dir for browser.js
process.env.CONXA_DIR = CONXA_DIR;

// ─── 3. Handle CLI flags (--install-playwright, --register-mcp, etc.) ─────────
const [,, ...cliArgs] = process.argv;
if (cliArgs.includes("--install-playwright")) {
  const { execSync } = require("child_process");
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(CONXA_DIR, "chromium");
  try {
    execSync("npx playwright install chromium --with-deps", { stdio: "inherit" });
    process.exit(0);
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
if (cliArgs.includes("--register-mcp")) {
  _registerMcp(cliArgs[cliArgs.indexOf("--register-mcp") + 1]);
  process.exit(0);
}
if (cliArgs.includes("--unregister-mcp")) {
  _unregisterMcp(cliArgs[cliArgs.indexOf("--unregister-mcp") + 1]);
  process.exit(0);
}
if (cliArgs.includes("--handle-auth-callback")) {
  const callbackUrl = cliArgs[cliArgs.indexOf("--handle-auth-callback") + 1] || "";
  _handleAuthCallback(callbackUrl);
  process.exit(0);
}

// ─── 4. Logger ────────────────────────────────────────────────────────────────
function log(level, msg, extra = {}) {
  const line = JSON.stringify({ ts: new Date().toISOString(), level, msg, ...extra }) + "\n";
  try {
    fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true });
    if (fs.existsSync(LOG_FILE) && fs.statSync(LOG_FILE).size > 10 * 1024 * 1024)
      fs.renameSync(LOG_FILE, LOG_FILE + ".1");
    fs.appendFileSync(LOG_FILE, line);
  } catch (_) {}
  process.stderr.write(line);
}

// ─── 5. Lazy requires (after env setup) ──────────────────────────────────────
const { Server }               = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { CallToolRequestSchema, ListToolsRequestSchema } = require("@modelcontextprotocol/sdk/types.js");

const skillLoader  = require("./skill_loader");
const sync         = require("./sync");
const authManager  = require("./auth_manager");
const { runPlan, enrichStepsWithRecovery, appendRecoveryEvent, clearRetryBudget, checkRetryBudget } = require("./run");
const { getCachedBrowser, gracefulShutdown } = require("./browser");

// ─── 6. Execution state (single lock per process) ─────────────────────────────
let activeExecution = null;

// ─── 7. Skill index ───────────────────────────────────────────────────────────
let skillIndex = {};
try {
  skillIndex = skillLoader.loadSkillRegistryFromCache(SKILL_PACKS_DIR, CACHE_DIR);
  log("info", "skill_index_loaded", { count: Object.keys(skillIndex).length });
} catch (e) {
  log("warn", "skill_index_load_failed", { error: e.message });
}

// ─── 8. MCP server ────────────────────────────────────────────────────────────
const server = new Server(
  { name: "conxa", version: RUNTIME_VERSION },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: _toolDefinitions() }));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  log("info", "tool_call", { tool: name });
  try {
    return await _handleTool(name, args || {});
  } catch (e) {
    log("error", "tool_error", { tool: name, error: e.message });
    return { content: [{ type: "text", text: `Internal error: ${e.message}` }] };
  }
});

// ─── 9. Connect MCP immediately ───────────────────────────────────────────────
const transport = new StdioServerTransport();
server.connect(transport);
log("info", "mcp_connected", { version: RUNTIME_VERSION, conxa_dir: CONXA_DIR });

// ─── 10. Async post-connect tasks ────────────────────────────────────────────
(async () => {
  // Telemetry — fire and forget
  _phonehome().catch(() => {});

  // Skill pack sync — 3s hard timeout, then continue with cache
  try {
    await sync.syncSkillPacks(SKILL_PACKS_DIR, authManager, { timeoutMs: 3000, log: (m) => log("info", m) });
    skillIndex = skillLoader.loadSkillRegistry(SKILL_PACKS_DIR, CACHE_DIR);
    log("info", "sync_complete", { count: Object.keys(skillIndex).length });
  } catch (e) {
    log("warn", "sync_skipped", { reason: e.message });
  }
})();

// ─── 11. Graceful shutdown ────────────────────────────────────────────────────
process.on("SIGINT",  () => gracefulShutdown());
process.on("SIGTERM", () => gracefulShutdown());
process.on("uncaughtException",  (e) => log("error", "uncaught", { error: e.message, stack: e.stack }));
process.on("unhandledRejection", (r) => log("error", "unhandled_rejection", { reason: String(r) }));

// ─── Tool definitions ─────────────────────────────────────────────────────────
function _toolDefinitions() {
  return [
    {
      name: "list_skills",
      description: "List all installed company workflow skills. Call once before planning — returns sync_status per company.",
      inputSchema: {
        type: "object",
        properties: {
          company: { type: "string", description: "Filter to a specific company slug (optional)" },
        },
        required: [],
      },
    },
    {
      name: "execute_skill",
      description: "Execute a workflow skill. Handles auth on demand — returns auth_required if the user needs to authenticate first. Returns result + screenshot on success, or failure data for recovery.",
      inputSchema: {
        type: "object",
        properties: {
          skill:       { type: "string",  description: "Skill slug from list_skills" },
          company:     { type: "string",  description: "Company slug (required if skill slug is not unique)" },
          inputs:      { type: "object",  description: "Input values. Call get_skill_inputs first to see the schema." },
          resume_from: { type: "integer", description: "Step index to resume from after fixing a failure." },
        },
        required: ["skill"],
      },
    },
    {
      name: "execute_sequence",
      description: "Execute an ordered list of skills in one shared browser session.",
      inputSchema: {
        type: "object",
        properties: {
          skills: {
            type: "array",
            items: {
              type: "object",
              properties: {
                skill:   { type: "string" },
                company: { type: "string" },
                inputs:  { type: "object" },
              },
              required: ["skill"],
            },
          },
        },
        required: ["skills"],
      },
    },
    {
      name: "get_skill_inputs",
      description: "Return the input schema for a skill. Always call this before execute_skill to know what to ask the user.",
      inputSchema: {
        type: "object",
        properties: {
          skill:   { type: "string" },
          company: { type: "string" },
        },
        required: ["skill"],
      },
    },
    {
      name: "get_execution_status",
      description: "Return the status of any currently running execution.",
      inputSchema: { type: "object", properties: {}, required: [] },
    },
    {
      name: "cancel_execution",
      description: "Cancel the currently running execution. Safe to call at any time.",
      inputSchema: { type: "object", properties: {}, required: [] },
    },
    {
      name: "refresh_skills",
      description: "Force an immediate skill pack sync from Conxa servers. Use if skills appear outdated.",
      inputSchema: {
        type: "object",
        properties: {
          company: { type: "string", description: "Sync only this company (optional, default: all)" },
        },
        required: [],
      },
    },
    {
      name: "read_skill_files",
      description: "DEBUG ONLY — inspect raw execution.json and recovery.json for a skill.",
      inputSchema: {
        type: "object",
        properties: {
          skill:   { type: "string" },
          company: { type: "string" },
        },
        required: ["skill"],
      },
    },
  ];
}

// ─── Resolve skill from index ─────────────────────────────────────────────────
function _resolveSkill(skillSlug, company) {
  if (!skillSlug) return null;
  const normalSlug = skillSlug.replace(/-/g, "_");

  // Exact match
  if (company) {
    const entry = skillIndex[`${company}:${skillSlug}`];
    if (entry) return entry;
    // Try underscore/dash normalization
    for (const v of Object.values(skillIndex)) {
      if (v.company === company && v.slug.replace(/-/g, "_") === normalSlug) return v;
    }
  }

  // Slug-only match across all companies
  for (const v of Object.values(skillIndex)) {
    if (v.slug === skillSlug || v.slug.replace(/-/g, "_") === normalSlug) return v;
  }
  return null;
}

// ─── Sync status per company ──────────────────────────────────────────────────
function _syncStatus(pack) {
  if (!pack.last_synced) return "unknown";
  return (Date.now() - new Date(pack.last_synced).getTime()) < 3600000 ? "current" : "stale";
}

// ─── Build L4/L5 failure response ─────────────────────────────────────────────
async function _buildFailureResponse(page, err, resolvedEntry) {
  const url      = page.url();
  const failedAt = typeof err.failedAt === "number" ? err.failedAt : null;

  const failShot = await page.screenshot({ type: "png" }).catch(() => null);

  let visualRefData = null, visualRefMime = null;
  if (resolvedEntry && failedAt !== null) {
    const visualDir = path.join(resolvedEntry.skillDir, "visuals");
    const stepNum   = failedAt + 1;
    for (const ext of [".jpg", ".jpeg", ".png"]) {
      const candidate = path.join(visualDir, `Image_${stepNum}${ext}`);
      if (fs.existsSync(candidate)) {
        visualRefData = fs.readFileSync(candidate).toString("base64");
        visualRefMime = ext === ".png" ? "image/png" : "image/jpeg";
        break;
      }
    }
  }

  let pageStructure = null, viewport = null, scrollY = null, consoleErrors = [];
  try {
    viewport = page.viewportSize();
    scrollY  = await page.evaluate(() => window.scrollY).catch(() => null);
    pageStructure = await page.evaluate(() => {
      const seen = new Set();
      return Array.from(document.querySelectorAll(
        'button, a[href], input, select, textarea, [role="button"], [role="link"], [role="menuitem"], [role="option"]'
      )).map(el => {
        const text = (el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 80);
        const tag  = el.tagName.toLowerCase();
        const type = el.getAttribute("type")        || "";
        const role = el.getAttribute("role")        || "";
        const id   = el.id                          || undefined;
        const dt   = el.getAttribute("data-testid") || el.getAttribute("data-test") || undefined;
        const key  = `${tag}|${type}|${text}`;
        if (!text && !type && !id && !dt) return null;
        if (seen.has(key)) return null;
        seen.add(key);
        return { tag, type: type || undefined, role: role || undefined, text: text || undefined, id, "data-testid": dt };
      }).filter(Boolean).slice(0, 250);
    });
  } catch (_) {}

  const resumeHint = failedAt !== null
    ? `\nFix the selector, then call execute_skill with resume_from: ${failedAt}.`
    : "";

  const content = [
    { type: "text", text: `Execution failed at step ${failedAt !== null ? failedAt + 1 : "?"}: ${err.message}\nPage URL: ${url}${resumeHint}` },
    { type: "text", text: "\nLayer 4 — vision recovery" },
  ];

  if (err.preShot)    content.push({ type: "text", text: "Pre-step screenshot:" }, { type: "image", data: err.preShot.toString("base64"), mimeType: "image/png" });
  if (visualRefData)  content.push({ type: "text", text: `Reference image for step ${failedAt + 1}:` }, { type: "image", data: visualRefData, mimeType: visualRefMime });
  if (failShot)       content.push({ type: "text", text: "Current page at failure:" }, { type: "image", data: failShot.toString("base64"), mimeType: "image/png" });

  const l5 = ["\nLayer 5 — intent recovery"];
  if (viewport)    l5.push(`viewport: ${JSON.stringify(viewport)}, scrollY: ${scrollY}`);
  if (pageStructure && pageStructure.length > 0) l5.push(`Interactive elements (${pageStructure.length}):\n${JSON.stringify(pageStructure, null, 2)}`);
  content.push({ type: "text", text: l5.join("\n") });

  return { content };
}

// ─── Tool handler ─────────────────────────────────────────────────────────────
async function _handleTool(name, args) {
  const text = (t) => ({ content: [{ type: "text", text: t }] });
  const err  = (t) => text(t);

  // ── list_skills ──────────────────────────────────────────────────────────────
  if (name === "list_skills") {
    const filterCompany = args.company ? String(args.company) : null;
    const skills = Object.values(skillIndex)
      .filter(s => !filterCompany || s.company === filterCompany)
      .map(s => ({
        skill:           s.slug,
        company:         s.company,
        name:            s.manifest.name || s.slug,
        description:     s.manifest.description || "",
        inputs_required: s.manifest.inputs_required || [],
        sync_status:     _syncStatus(s.pack),
        version:         s.manifest.version || "1.0.0",
      }));
    return text(JSON.stringify({ skills, total: skills.length }, null, 2));
  }

  // ── get_skill_inputs ─────────────────────────────────────────────────────────
  if (name === "get_skill_inputs") {
    const entry = _resolveSkill(String(args.skill || ""), args.company ? String(args.company) : null);
    if (!entry) return err(`Skill not found: ${args.skill}. Call list_skills first.`);
    const inputsPath = path.join(entry.skillDir, "inputs.json");
    // Fall back to legacy input.json
    const legacyPath = path.join(entry.skillDir, "input.json");
    const schema = fs.existsSync(inputsPath)
      ? JSON.parse(fs.readFileSync(inputsPath, "utf8"))
      : (fs.existsSync(legacyPath) ? JSON.parse(fs.readFileSync(legacyPath, "utf8")) : {});
    return text(JSON.stringify(schema, null, 2));
  }

  // ── get_execution_status ─────────────────────────────────────────────────────
  if (name === "get_execution_status") {
    if (!activeExecution) return text('{"status":"idle"}');
    return text(JSON.stringify({
      status:     "running",
      skill:      activeExecution.slug,
      company:    activeExecution.company,
      step:       activeExecution.step,
      total:      activeExecution.total,
      started_at: activeExecution.startedAt,
    }));
  }

  // ── cancel_execution ─────────────────────────────────────────────────────────
  if (name === "cancel_execution") {
    if (!activeExecution) return text('{"cancelled":false,"reason":"no active execution"}');
    activeExecution.cancelRequested = true;
    return text('{"cancelled":true}');
  }

  // ── refresh_skills ───────────────────────────────────────────────────────────
  if (name === "refresh_skills") {
    try {
      await sync.syncSkillPacks(SKILL_PACKS_DIR, authManager, { timeoutMs: 15000, log: (m) => log("info", m) });
      skillIndex = skillLoader.loadSkillRegistry(SKILL_PACKS_DIR, CACHE_DIR);
      return text(`Refreshed. ${Object.keys(skillIndex).length} skills loaded.`);
    } catch (e) {
      return err(`Refresh failed: ${e.message}. Cached data in use.`);
    }
  }

  // ── read_skill_files (debug) ─────────────────────────────────────────────────
  if (name === "read_skill_files") {
    const entry = _resolveSkill(String(args.skill || ""), args.company ? String(args.company) : null);
    if (!entry) return err(`Skill not found: ${args.skill}. Call list_skills.`);
    const { skillDir } = entry;
    const execPath     = path.join(skillDir, "execution.json");
    const recPath      = path.join(skillDir, "recovery.json");
    const inputsPath   = path.join(skillDir, "inputs.json");
    const legacyInput  = path.join(skillDir, "input.json");
    const rawExec      = fs.existsSync(execPath) ? JSON.parse(fs.readFileSync(execPath, "utf8")) : null;
    const rawRec       = fs.existsSync(recPath)  ? JSON.parse(fs.readFileSync(recPath, "utf8"))  : null;
    const inputSchema  = fs.existsSync(inputsPath) ? JSON.parse(fs.readFileSync(inputsPath, "utf8"))
                       : (fs.existsSync(legacyInput) ? JSON.parse(fs.readFileSync(legacyInput, "utf8")) : null);
    const rawSteps = Array.isArray(rawExec) ? rawExec : (rawExec?.steps || []);
    return text(JSON.stringify({
      slug: entry.slug, company: entry.company,
      manifest: entry.manifest,
      input_schema: inputSchema,
      execution: enrichStepsWithRecovery(rawSteps, rawRec),
      recovery: rawRec,
    }, null, 2));
  }

  // ── execute_skill / execute_sequence ─────────────────────────────────────────
  if (name === "execute_skill" || name === "execute_sequence") {
    const runs = name === "execute_sequence"
      ? (Array.isArray(args.skills) ? args.skills : [])
      : [{ skill: args.skill, company: args.company, inputs: args.inputs, resume_from: args.resume_from }];

    if (runs.length === 0) return err("No skills provided.");

    // Execution lock
    if (activeExecution) return err(`Execution already running: ${activeExecution.slug}. Call cancel_execution first.`);

    // Resolve all skills (fail fast)
    const resolved = [];
    for (const run of runs) {
      const entry = _resolveSkill(String(run.skill || ""), run.company ? String(run.company) : null);
      if (!entry) return err(`Skill not found: ${run.skill}. Call list_skills.`);

      // Auth gate (Conxa token)
      let token;
      try { token = await authManager.getToken(entry.company); } catch (_) { token = null; }
      if (!token) {
        const { url } = authManager.getAuthChallengeUrl(entry.company);
        return text(JSON.stringify({
          status:      "auth_required",
          company:     entry.company,
          message:     `Authentication required for ${entry.company} workflows.`,
          auth_url:    url,
          instruction: "Ask the user to visit the auth_url to authenticate with Conxa, then retry.",
        }));
      }

      // Integrity gate
      try {
        skillLoader.verifySkillIntegrity(entry.skillDir, entry.manifest);
      } catch (integrityErr) {
        // Trigger background re-sync
        sync.syncSkillPacks(SKILL_PACKS_DIR, authManager, { timeoutMs: 15000, log: (m) => log("info", m) })
          .then(() => { skillIndex = skillLoader.loadSkillRegistry(SKILL_PACKS_DIR, CACHE_DIR); })
          .catch(() => {});
        return err(`Skill integrity check failed: ${integrityErr.message}. A re-sync has been triggered — call refresh_skills, then retry.`);
      }

      // Runtime compatibility
      const required = entry.manifest.required_runtime || ">=0.0.0";
      if (!semver.satisfies(RUNTIME_VERSION, required))
        return err(`Skill ${run.skill} requires runtime ${required}, installed: ${RUNTIME_VERSION}. Please update the Conxa runtime.`);

      const execPath = path.join(entry.skillDir, "execution.json");
      const recPath  = path.join(entry.skillDir, "recovery.json");
      const rawExec  = fs.existsSync(execPath) ? JSON.parse(fs.readFileSync(execPath, "utf8")) : null;
      const rawRec   = fs.existsSync(recPath)  ? JSON.parse(fs.readFileSync(recPath,  "utf8")) : null;
      const rawSteps = Array.isArray(rawExec) ? rawExec : (rawExec?.steps || rawExec?.execution_plan || []);
      const steps    = enrichStepsWithRecovery(rawSteps, rawRec);

      resolved.push({
        entry,
        steps,
        inputs:     (run.inputs && typeof run.inputs === "object") ? run.inputs : {},
        resumeFrom: (Number.isInteger(run.resume_from) && run.resume_from > 0) ? run.resume_from : 0,
        token,
      });
    }

    // Retry budget check on resume
    const primary = resolved[0];
    if (primary.resumeFrom > 0 && !checkRetryBudget(primary.entry.slug, primary.resumeFrom))
      return err(`Retry budget exhausted at step ${primary.resumeFrom}. Fix the root cause in execution.json before retrying from step 0.`);

    // Acquire execution lock
    activeExecution = {
      slug:            primary.entry.slug,
      company:         primary.entry.company,
      step:            0,
      total:           resolved.reduce((n, r) => n + r.steps.length, 0),
      startedAt:       new Date().toISOString(),
      cancelRequested: false,
    };

    let page = null;
    let _browser, _context;
    try {
      ({ browser: _browser, context: _context } = await getCachedBrowser(primary.entry.company, authManager));
      page = await _context.newPage();

      const runtimeLog = { consoleErrors: [], pageErrors: [], failedRequests: [] };
      page.on("console", msg => {
        if (["error", "warning"].includes(msg.type()) && runtimeLog.consoleErrors.length < 50)
          runtimeLog.consoleErrors.push({ type: msg.type(), text: msg.text() });
      });
      page.on("pageerror",     e  => { if (runtimeLog.pageErrors.length < 20) runtimeLog.pageErrors.push(e.message); });
      page.on("requestfailed", req => {
        if (runtimeLog.failedRequests.length < 30)
          runtimeLog.failedRequests.push({ url: req.url(), failure: req.failure()?.errorText });
      });

      for (let si = 0; si < resolved.length; si++) {
        const { entry, steps, inputs, resumeFrom } = resolved[si];
        const startAt = si === 0 ? resumeFrom : 0;
        try {
          await runPlan(page, steps, inputs, startAt, entry.slug, {
            onStep:      (i) => { if (activeExecution) activeExecution.step = i; },
            cancelCheck: () => activeExecution?.cancelRequested,
          });
        } catch (runErr) {
          runErr.fromEntry = entry;
          throw runErr;
        }
      }

      // Success — save session
      const state = await _context.storageState();
      authManager.saveEncryptedSession(primary.entry.company, state, primary.token, SESSIONS_DIR);

      const url  = page.url();
      const shot = await page.screenshot({ type: "png" }).catch(() => null);
      await page.close().catch(() => {});

      for (const r of resolved) {
        clearRetryBudget(r.entry.slug);
        appendRecoveryEvent({ event: "run_success", slug: r.entry.slug, steps_executed: r.steps.length });
      }

      log("info", "execute_success", { skill: primary.entry.slug, url });

      const content = [{ type: "text", text: `Done. URL: ${url}` }];
      if (shot) content.push({ type: "image", data: shot.toString("base64"), mimeType: "image/png" });
      return { content };

    } catch (runErr) {
      log("error", "execute_failed", { skill: primary.entry.slug, error: runErr.message });
      appendRecoveryEvent({ event: "terminal_failure", slug: primary.entry.slug, error: runErr.message });
      const failResp = page ? await _buildFailureResponse(page, runErr, runErr.fromEntry || primary.entry) : err(runErr.message);
      if (page) await page.close().catch(() => {});
      return failResp;

    } finally {
      activeExecution = null;
    }
  }

  return err(`Unknown tool: ${name}`);
}

// ─── MCP config helpers ───────────────────────────────────────────────────────
function _registerMcp(configPath) {
  if (!configPath || !fs.existsSync(path.dirname(configPath))) return;
  let cfg = {};
  try { cfg = JSON.parse(fs.readFileSync(configPath, "utf8")); } catch (_) {}
  cfg.mcpServers = cfg.mcpServers || {};
  const runtimeExe = process.platform === "win32"
    ? "C:\\Program Files\\Conxa\\runtime\\runtime.exe"
    : path.join(CONXA_DIR, "runtime", "runtime");
  if (cfg.mcpServers.conxa && cfg.mcpServers.conxa.command === runtimeExe) return;
  cfg.mcpServers.conxa = { command: runtimeExe };
  const tmp = configPath + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(cfg, null, 2));
  fs.renameSync(tmp, configPath);
}

function _unregisterMcp(configPath) {
  if (!configPath || !fs.existsSync(configPath)) return;
  let cfg = {};
  try { cfg = JSON.parse(fs.readFileSync(configPath, "utf8")); } catch (_) { return; }
  if (!cfg.mcpServers || !cfg.mcpServers.conxa) return;
  delete cfg.mcpServers.conxa;
  const tmp = configPath + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(cfg, null, 2));
  fs.renameSync(tmp, configPath);
}

function _handleAuthCallback(callbackUrl) {
  try {
    const url    = new URL(callbackUrl);
    const token  = url.searchParams.get("token");
    const nonce  = url.searchParams.get("nonce");
    const company = url.searchParams.get("company");
    if (!token || !company) return;
    // Write to a well-known file that the runtime process will pick up
    const callbackFile = path.join(CONXA_DIR, "cache", ".auth_callback.json");
    fs.mkdirSync(path.dirname(callbackFile), { recursive: true });
    fs.writeFileSync(callbackFile, JSON.stringify({ token, nonce, company, ts: Date.now() }));
    authManager.setToken(company, token).catch(() => {});
  } catch (_) {}
}

async function _phonehome() {
  const CONXA_API = process.env.CONXA_API_URL || "https://api.conxa.io";
  const companies = [...new Set(Object.values(skillIndex).map(s => s.company))];
  const body = JSON.stringify({
    runtime_version: RUNTIME_VERSION,
    companies,
    platform: process.platform,
  });
  await new Promise((resolve) => {
    const req = https.request(`${CONXA_API}/telemetry/runtime-start`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    }, (res) => { res.resume(); resolve(); });
    req.on("error", resolve);
    req.setTimeout(5000, () => { req.destroy(); resolve(); });
    req.write(body);
    req.end();
  });
}
