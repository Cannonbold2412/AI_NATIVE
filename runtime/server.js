#!/usr/bin/env node
"use strict";
const path   = require("path");
const fs     = require("fs");
const os     = require("os");
const https  = require("https");
const semver = require("semver");
const { loadInstallId } = require("./install_identity");

// ─── 1. Resolve CONXA_DIR (install, read-only) and CONXA_DATA_DIR (user-writable) ─
const CONXA_DIR = process.env.CONXA_DIR || (
  process.platform === "win32"
    ? path.join(os.homedir(), "AppData", "Local", "Conxa")
    : path.join(os.homedir(), ".conxa")
);
const CONXA_DATA_DIR = process.env.CONXA_DATA_DIR || (
  process.platform === "win32"
    ? path.join(os.homedir(), "AppData", "Roaming", "Conxa")
    : path.join(os.homedir(), ".conxa")
);

const SKILL_PACKS_DIR = path.join(CONXA_DIR, "skill-packs");
const CACHE_DIR       = path.join(CONXA_DATA_DIR, "cache");
const SESSIONS_DIR    = path.join(CACHE_DIR, "sessions");
const LOG_FILE        = path.join(CONXA_DATA_DIR, "logs", "runtime.log");
const RUNTIME_VERSION = require("./package.json").version;
const INSTALL_ID      = loadInstallId(CONXA_DATA_DIR);

// ─── 2. Playwright browser path (MUST precede any playwright require) ─────────
// Respect a caller-supplied PLAYWRIGHT_BROWSERS_PATH (e.g. dev mode where CONXA_DIR
// points to a data dir that has no chromium/ subfolder).
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(CONXA_DIR, "chromium");
}
// Pass both dirs to browser.js
process.env.CONXA_DIR      = CONXA_DIR;
process.env.CONXA_DATA_DIR = CONXA_DATA_DIR;

// ─── 3. Handle CLI flags (--install-playwright, --handle-auth-callback, etc.) ──
const [,, ...cliArgs] = process.argv;
if (cliArgs.includes("--install-playwright")) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(CONXA_DIR, "chromium");
  // Use playwright-core's bundled CLI runner — works inside the pkg exe without
  // requiring system npm/npx, which is not guaranteed on end-user machines.
  try {
    require("playwright-core/cli")
      .main(["install", "--with-deps", "chromium"])
      .then(() => process.exit(0))
      .catch((e) => { process.stderr.write(e.message + "\n"); process.exit(1); });
  } catch (_) {
    // Dev / CI fallback: system npx (requires Node installed globally).
    const { execSync } = require("child_process");
    try {
      execSync("npx playwright install chromium --with-deps", { stdio: "inherit" });
      process.exit(0);
    } catch (e) {
      process.stderr.write(e.message + "\n");
      process.exit(1);
    }
  }
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

log("info", "runtime_bootstrap", {
  version: RUNTIME_VERSION,
  conxa_dir: CONXA_DIR,
  conxa_data_dir: CONXA_DATA_DIR,
  skill_packs_dir: SKILL_PACKS_DIR,
  cache_dir: CACHE_DIR,
  log_file: LOG_FILE,
});

process.on("uncaughtException",  (e) => log("error", "uncaught", { error: e.message, stack: e.stack }));
process.on("unhandledRejection", (r) => log("error", "unhandled_rejection", { reason: String(r) }));

// ─── 5. Lazy requires (after env setup) ──────────────────────────────────────
let Server;
let StdioServerTransport;
let CallToolRequestSchema;
let ListToolsRequestSchema;
let skillLoader;
let sync;
let authManager;
let runPlan;
let enrichStepsWithRecovery;
let appendRecoveryEvent;
let clearRetryBudget;
let checkRetryBudget;
let isAuthFailure;
let getCachedBrowser;
let gracefulShutdown;
let createTracker;
let mapErrorToCode;

try {
  ({ Server }               = require("@modelcontextprotocol/sdk/server/index.js"));
  ({ StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js"));
  ({ CallToolRequestSchema, ListToolsRequestSchema } = require("@modelcontextprotocol/sdk/types.js"));

  skillLoader  = require("./skill_loader");
  sync         = require("./sync");
  authManager  = require("./auth_manager");
  ({ runPlan, enrichStepsWithRecovery, appendRecoveryEvent, clearRetryBudget, checkRetryBudget, isAuthFailure } = require("./run"));
  ({ getCachedBrowser, gracefulShutdown } = require("./browser"));
  ({ createTracker, mapErrorToCode } = require("./tracker"));
} catch (e) {
  log("error", "runtime_bootstrap_failed", { error: e.message, stack: e.stack });
  process.exit(1);
}

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

// ─── 9. Runtime self-update (Phase 6) ────────────────────────────────────────
// On cold start: if a pending update is ready, apply it via update.bat and exit
// so the next invocation picks up the new binary. Otherwise, check the cloud
// manifest and download in the background (applied on the next cold start).
const CONXA_API = process.env.CONXA_API_URL || "https://apis.conxa.in";
const RUNTIME_UPDATE_CACHE = path.join(CACHE_DIR, "runtime-update-cache.json");
const RUNTIME_UPDATE_PENDING = path.join(CACHE_DIR, "runtime-update-pending.json");

function _compareVersions(a, b) {
  // Simple semver-ish compare: v1.2.3 → [1,2,3]
  const parse = (v) => String(v).replace(/^v/, "").split(".").map(Number);
  const [aP, bP] = [parse(a), parse(b)];
  for (let i = 0; i < 3; i++) {
    const diff = (aP[i] || 0) - (bP[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

async function _applyPendingUpdate() {
  if (!fs.existsSync(RUNTIME_UPDATE_PENDING)) return false;
  let pending;
  try { pending = JSON.parse(fs.readFileSync(RUNTIME_UPDATE_PENDING, "utf8")); } catch (_) { return false; }
  if (!pending.ready) return false;
  const nextExe = path.join(CONXA_DIR, "runtime.exe.next");
  if (!fs.existsSync(nextExe)) return false;

  // Write update.bat with a random suffix to avoid predictable path attacks.
  const suffix = Math.random().toString(36).slice(2);
  const batPath = path.join(os.tmpdir(), `conxa-update-${suffix}.bat`);
  const runtimeExe = path.join(CONXA_DIR, "runtime.exe");
  const keytarNext    = path.join(CONXA_DIR, "keytar.node.next");
  const keytarCurrent = path.join(CONXA_DIR, "keytar.node");
  const batContent = [
    "@echo off",
    "timeout /t 3 /nobreak >nul",
    `move /Y "${nextExe}" "${runtimeExe}"`,
    // Swap keytar.node if a new one was staged alongside the exe.
    `if exist "${keytarNext}" move /Y "${keytarNext}" "${keytarCurrent}"`,
    // Re-run Playwright browser install so Chromium revision matches the new exe.
    // Idempotent: no-op if the revision is already present on disk.
    `"${runtimeExe}" --install-playwright`,
    `del "${batPath}"`,
  ].join("\r\n");
  fs.writeFileSync(batPath, batContent);
  const { spawn } = require("child_process");
  spawn("cmd.exe", ["/C", batPath], { detached: true, stdio: "ignore" }).unref();
  log("info", "[runtime:update-pending] applying update → restart", { version: pending.version });
  return true;
}

async function _checkRuntimeUpdate() {
  if (process.env.CONXA_SKIP_SELF_UPDATE === "1") return;
  if (fs.existsSync(RUNTIME_UPDATE_PENDING)) return; // already downloaded, wait for next cold start

  let manifest = null;
  // Try local cache first (valid for 24h)
  if (fs.existsSync(RUNTIME_UPDATE_CACHE)) {
    try {
      const cached = JSON.parse(fs.readFileSync(RUNTIME_UPDATE_CACHE, "utf8"));
      if (cached._cached_at && Date.now() - cached._cached_at < 24 * 60 * 60 * 1000) {
        manifest = cached;
      }
    } catch (_) {}
  }

  if (!manifest) {
    try {
      manifest = await new Promise((resolve, reject) => {
        const req = https.get(`${CONXA_API}/api/v1/updates/runtime-manifest`, (res) => {
          let data = "";
          res.on("data", (c) => { data += c; });
          res.on("end", () => {
            try {
              const parsed = JSON.parse(data);
              parsed._cached_at = Date.now();
              fs.mkdirSync(path.dirname(RUNTIME_UPDATE_CACHE), { recursive: true });
              fs.writeFileSync(RUNTIME_UPDATE_CACHE, JSON.stringify(parsed));
              resolve(parsed);
            } catch (e) { reject(e); }
          });
        });
        req.setTimeout(8000, () => { req.destroy(); reject(new Error("timeout")); });
        req.on("error", reject);
      });
    } catch (_) {
      return; // network unavailable — skip silently
    }
  }

  if (!manifest || !manifest.version) return;
  if (_compareVersions(manifest.version, RUNTIME_VERSION) <= 0) return;

  // Newer version available — download in background
  log("info", `[runtime:update-pending] v${RUNTIME_VERSION}→${manifest.version} downloading`);
  const nextExe = path.join(CONXA_DIR, "runtime.exe.next");
  try {
    const buf = await new Promise((resolve, reject) => {
      const req = https.get(manifest.url, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve(Buffer.concat(chunks)));
      });
      req.setTimeout(120_000, () => { req.destroy(); reject(new Error("download timeout")); });
      req.on("error", reject);
    });
    // SHA-256 verify
    if (manifest.sha256) {
      const { createHash } = require("crypto");
      const actual = createHash("sha256").update(buf).digest("hex");
      if (actual.toLowerCase() !== manifest.sha256.toLowerCase()) {
        throw new Error(`SHA-256 mismatch: expected ${manifest.sha256} got ${actual}`);
      }
    }
    fs.mkdirSync(path.dirname(nextExe), { recursive: true });
    fs.writeFileSync(nextExe, buf);

    // Download keytar.node.next alongside the exe — must match the new Node ABI.
    let hasKeytar = false;
    if (manifest.keytar_url) {
      try {
        const keytarBuf = await new Promise((resolve, reject) => {
          const req = https.get(manifest.keytar_url, (res) => {
            const chunks = [];
            res.on("data", (c) => chunks.push(c));
            res.on("end", () => resolve(Buffer.concat(chunks)));
          });
          req.setTimeout(60_000, () => { req.destroy(); reject(new Error("keytar download timeout")); });
          req.on("error", reject);
        });
        if (manifest.keytar_sha256) {
          const { createHash } = require("crypto");
          const actual = createHash("sha256").update(keytarBuf).digest("hex");
          if (actual.toLowerCase() !== manifest.keytar_sha256.toLowerCase())
            throw new Error(`keytar SHA-256 mismatch: expected ${manifest.keytar_sha256} got ${actual}`);
        }
        fs.writeFileSync(path.join(CONXA_DIR, "keytar.node.next"), keytarBuf);
        hasKeytar = true;
      } catch (e) {
        log("warn", "keytar_update_download_failed", { reason: e.message });
        // Non-fatal: old keytar stays in place; token storage still works unless Node ABI changed.
      }
    }

    fs.writeFileSync(RUNTIME_UPDATE_PENDING, JSON.stringify({ version: manifest.version, ready: true, has_keytar: hasKeytar }));
    log("info", `[runtime:update-pending] v${RUNTIME_VERSION}→${manifest.version} ready (keytar=${hasKeytar})`);
  } catch (e) {
    log("warn", "runtime_update_download_failed", { reason: e.message });
  }
}

// Apply pending update before connecting (may exit process on Windows).
if (process.platform === "win32") {
  const _pendingApplied = _applyPendingUpdate();
  // _applyPendingUpdate() is async but its shell spawn is fire-and-forget;
  // if it returns true the process exits in the bat timeout window — safe to continue.
}
// Delete the pending marker after a confirmed successful first run post-update.
if (fs.existsSync(RUNTIME_UPDATE_PENDING)) {
  try {
    const p = JSON.parse(fs.readFileSync(RUNTIME_UPDATE_PENDING, "utf8"));
    if (p.ready && !fs.existsSync(path.join(CONXA_DIR, "runtime.exe.next"))) {
      fs.unlinkSync(RUNTIME_UPDATE_PENDING);
      log("info", "runtime_update_applied", { version: p.version });
    }
  } catch (_) {}
}

// ─── 10. Connect MCP immediately ─────────────────────────────────────────────
const transport = new StdioServerTransport();
server.connect(transport);
log("info", "mcp_connected", { version: RUNTIME_VERSION, conxa_dir: CONXA_DIR });

// ─── 11. Async post-connect tasks ────────────────────────────────────────────
(async () => {
  // Skill pack sync first — ensures companies[] in phonehome is accurate
  try {
    await sync.syncSkillPacks(SKILL_PACKS_DIR, { timeoutMs: 15000, log: (m) => log("info", m) });
    skillIndex = skillLoader.loadSkillRegistry(SKILL_PACKS_DIR, CACHE_DIR);
    log("info", "sync_complete", { count: Object.keys(skillIndex).length });
  } catch (e) {
    log("warn", "sync_skipped", { reason: e.message });
  }

  // Phonehome after sync so companies[] reflects current skill index
  _phonehome().catch(() => {});

  // Background runtime self-update check (downloads update for next cold start)
  _checkRuntimeUpdate().catch(() => {});
})();

// ─── 12. Graceful shutdown ────────────────────────────────────────────────────
process.on("SIGINT",  () => gracefulShutdown());
process.on("SIGTERM", () => gracefulShutdown());

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
      description: "Execute a workflow skill. Default watch: true (visible browser). Pass watch: false only if the user explicitly asks to run in the background. Returns result on success, or failure data for recovery.",
      inputSchema: {
        type: "object",
        properties: {
          skill:       { type: "string",  description: "Skill slug from list_skills" },
          company:     { type: "string",  description: "Company slug (required if skill slug is not unique)" },
          inputs:      { type: "object",  description: "Input values. Call get_skill_inputs first to see the schema." },
          resume_from: { type: "integer", description: "Step index to resume from after fixing a failure." },
          watch:       { type: "boolean", description: "true = open a visible browser so the user can watch; false = run headlessly in the background." },
        },
        required: ["skill"],
      },
    },
    {
      name: "execute_sequence",
      description: "Execute an ordered list of skills in one shared browser session. Default watch: true (visible browser). Pass watch: false only if the user explicitly asks to run in the background.",
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
          watch: { type: "boolean", description: "true = visible browser; false = headless." },
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
      name: "cancel_execution",
      description: "Cancel the currently running execution. Safe to call at any time.",
      inputSchema: { type: "object", properties: {}, required: [] },
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

function _trackingStatus(pack) {
  const tracking = (pack && pack.tracking) || {};
  return {
    enabled: tracking.enabled === true,
    tracking_url_present: Boolean(tracking.tracking_url),
    tracking_token_present: Boolean(tracking.tracking_token),
    company_id: tracking.company_id || "",
    workspace_id: pack?.published?.workspace_id || pack?.workspace_id || "",
    sync_endpoint: pack?.sync_endpoint || "",
  };
}


// ─── Build L4/L5 failure response ─────────────────────────────────────────────
async function _buildFailureResponse(page, err, resolvedEntry) {
  const url      = page.url();
  const failedAt = typeof err.failedAt === "number" ? err.failedAt : null;

  // P7: capture as JPEG (lossless PNG is 3-8× larger; Claude token cost is dimension-based either way)
  const failShot = await page.screenshot({ type: "jpeg", quality: 80 }).catch(() => null);

  // P5: skip visual reference if already sent for this (slug, step) in this execution
  const sentRefs    = activeExecution?.sentVisualRefs;
  const visualRefKey = resolvedEntry && failedAt !== null ? `${resolvedEntry.slug}:${failedAt}` : null;
  const alreadySentRef = sentRefs && visualRefKey ? sentRefs.has(visualRefKey) : false;

  let visualRefData = null, visualRefMime = null;
  if (resolvedEntry && failedAt !== null && !alreadySentRef) {
    const visualDir = path.join(resolvedEntry.skillDir, "visuals");
    const stepNum   = failedAt + 1;
    for (const ext of [".jpg", ".jpeg", ".png"]) {
      const candidate = path.join(visualDir, `Image_${stepNum}${ext}`);
      if (fs.existsSync(candidate)) {
        visualRefData = fs.readFileSync(candidate).toString("base64");
        visualRefMime = ext === ".png" ? "image/png" : "image/jpeg";
        if (sentRefs && visualRefKey) sentRefs.add(visualRefKey);
        break;
      }
    }
  }

  // P2: cap at 50 elements (was 250) — dominant text payload; nearby elements suffice for recovery
  let pageStructure = null, viewport = null, scrollY = null;
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
      }).filter(Boolean).slice(0, 50);
    });
  } catch (_) {}

  const sessionExpiredHint = err.session_expired
    ? `\nSession expired — the workflow was redirected to: ${err.login_url || url}\nAsk the user to re-authenticate, then call execute_skill with resume_from: ${failedAt ?? 0}.`
    : "";
  const resumeHint = !err.session_expired && failedAt !== null
    ? `\nFix the selector, then call execute_skill with resume_from: ${failedAt}.`
    : "";

  const content = [
    { type: "text", text: `Execution failed at step ${failedAt !== null ? failedAt + 1 : "?"}: ${err.message}\nPage URL: ${url}${sessionExpiredHint}${resumeHint}` },
    { type: "text", text: "\nLayer 4 — vision recovery" },
  ];

  if (err.preShot)    content.push({ type: "text", text: "Pre-step screenshot:" }, { type: "image", data: err.preShot.toString("base64"), mimeType: "image/png" });
  if (visualRefData)  content.push({ type: "text", text: `Reference image for step ${failedAt + 1}:` }, { type: "image", data: visualRefData, mimeType: visualRefMime });
  // P7: mimeType updated to match JPEG capture above
  if (failShot)       content.push({ type: "text", text: "Current page at failure:" }, { type: "image", data: failShot.toString("base64"), mimeType: "image/jpeg" });

  // P4: compact JSON (no null,2 indentation)
  const l5 = ["\nLayer 5 — intent recovery"];
  if (viewport)    l5.push(`viewport: ${JSON.stringify(viewport)}, scrollY: ${scrollY}`);
  if (pageStructure && pageStructure.length > 0) l5.push(`Interactive elements (${pageStructure.length}):\n${JSON.stringify(pageStructure)}`);
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
    return text(JSON.stringify({ skills, total: skills.length }));
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
    return text(JSON.stringify(schema));
  }

  // ── cancel_execution ─────────────────────────────────────────────────────────
  if (name === "cancel_execution") {
    if (!activeExecution) return text('{"cancelled":false,"reason":"no active execution"}');
    activeExecution.cancelRequested = true;
    return text('{"cancelled":true}');
  }

  // ── execute_skill / execute_sequence ─────────────────────────────────────────
  if (name === "execute_skill" || name === "execute_sequence") {
    const watch = args.watch !== false;
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

      // Integrity gate
      try {
        skillLoader.verifySkillIntegrity(entry.skillDir, entry.manifest);
      } catch (integrityErr) {
        // Trigger background re-sync
        sync.syncSkillPacks(SKILL_PACKS_DIR, { timeoutMs: 15000, log: (m) => log("info", m) })
          .then(() => { skillIndex = skillLoader.loadSkillRegistry(SKILL_PACKS_DIR, CACHE_DIR); })
          .catch(() => {});
        return err(`Skill integrity check failed: ${integrityErr.message}. A background re-sync has been triggered — please retry in a moment.`);
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
      sentVisualRefs:  new Set(), // P5: tracks which (slug:stepIndex) visual refs were sent this execution
    };

    // Per-company observer pace (ms of minimum viewing time per page transition)
    const _observerMs = primary.entry.pack?.pacing?.observer_ms ?? 600;

    log("info", "execute_start", {
      tool: name,
      run_count: resolved.length,
      skill: primary.entry.slug,
      company: primary.entry.company,
      total_steps: resolved.reduce((n, r) => n + r.steps.length, 0),
      watch,
      tracking: _trackingStatus(primary.entry.pack),
    });

    // Set up lightweight tracker for this execution
    const _tracker    = createTracker(primary.entry.pack?.tracking || {}, {
      runtime_version: RUNTIME_VERSION,
      plugin_id:       primary.entry.slug,
      plugin_version:  primary.entry.manifest?.version || "0",
      company_id:      primary.entry.company,
      log,
    });
    const _runId      = `r_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
    const _runTracker = _tracker.forRun(_runId, { uid: INSTALL_ID, wid: "" });
    const _wfStartAt  = Date.now();
    let   _totalRecovered = 0;

    // Signal LLM/vision recovery retry (L4/L5) when resuming mid-plan
    if (primary.resumeFrom > 0) {
      _runTracker.emit("rec_start", { si: primary.resumeFrom, l: 5, sc: "llm_intent" });
    }
    _runTracker.emit("wf_start", {});

    let page = null;
    let _browser, _context, _protectedUrl;
    try {
      ({ browser: _browser, context: _context, protectedUrl: _protectedUrl } = await getCachedBrowser(primary.entry.company, authManager, { headless: !watch }));
      page = await _context.newPage();
      if (_protectedUrl) {
        await page.goto(_protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
      }

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

      const _downloadsDir = path.join(os.homedir(), ".conxa", "downloads", _runId);
      const _downloads = [];
      const _downloadSaves = [];
      page.on("download", (download) => {
        const savePromise = (async () => {
          fs.mkdirSync(_downloadsDir, { recursive: true });
          const fname = download.suggestedFilename() || `download_${Date.now()}`;
          const dest  = path.join(_downloadsDir, fname);
          await download.saveAs(dest);
          _downloads.push(dest);
        })().catch(() => {});
        _downloadSaves.push(savePromise);
      });

      for (let si = 0; si < resolved.length; si++) {
        const { entry, steps, inputs, resumeFrom } = resolved[si];
        let startAt = si === 0 ? resumeFrom : 0;
        let authRetried = false;

        while (true) { // eslint-disable-line no-constant-condition
          try {
            const result = await runPlan(page, steps, inputs, startAt, entry.slug, {
              onStep:      (i) => { if (activeExecution) activeExecution.step = i; },
              cancelCheck: () => activeExecution?.cancelRequested,
              tracker:     _runTracker,
              observerMs:  _observerMs,
            });
            _totalRecovered += (result && result.recoveredSteps) ? result.recoveredSteps : 0;
            break;
          } catch (runErr) {
            // Auth-failure recovery (Phase 5): detect login redirect, refresh session, resume.
            const failedStep = runErr.failedAt ?? null;
            if (!authRetried && failedStep !== null && await isAuthFailure(page)) {
              authRetried = true;
              appendRecoveryEvent({ event: "auth_failure_detected", slug: entry.slug, step_index: failedStep });
              const loginUrl = entry.manifest?.login_url || entry.manifest?.target_url || entry.manifest?.entry_url || page.url();
              const refreshResult = await authManager.refreshSession(
                entry.company, loginUrl, _context, SESSIONS_DIR
              );
              if (refreshResult.ok) {
                appendRecoveryEvent({ event: "auth_refreshed", slug: entry.slug });
                startAt = failedStep; // resume from the step that failed
                continue;
              }
              // Headless or retry limit — surface to Claude as session_expired.
              const authErr = Object.assign(
                new Error(refreshResult.message),
                { session_expired: true, login_url: refreshResult.login_url, failedAt: failedStep }
              );
              authErr.fromEntry = entry;
              throw authErr;
            }
            runErr.fromEntry = entry;
            throw runErr;
          }
        }
      }

      // Success — save session
      const state = await _context.storageState();
      authManager.saveRawSession(primary.entry.company, state, SESSIONS_DIR);

      const url  = page.url();
      const shot = process.env.CONXA_CAPTURE_SUCCESS_SCREENSHOT === "1"
        ? await page.screenshot({ type: "png" }).catch(() => null)
        : null;
      await Promise.allSettled(_downloadSaves);
      await page.close().catch(() => {});
      if (watch) {
        await _context.close().catch(() => {});
        await _browser.close().catch(() => {});
      }

      for (const r of resolved) {
        clearRetryBudget(r.entry.slug);
        appendRecoveryEvent({ event: "run_success", slug: r.entry.slug, steps_executed: r.steps.length });
      }

      _runTracker.emit("wf_ok", {
        dur: Date.now() - _wfStartAt,
        tot: resolved.reduce((n, r) => n + r.steps.length, 0),
        rec: _totalRecovered,
      });
      await _tracker.flush();
      _tracker.destroy();

      log("info", "execute_success", { skill: primary.entry.slug, url });

      const downloadNote = _downloads.length
        ? `\nDownloaded files:\n${_downloads.map(p => `  ${p}`).join("\n")}`
        : "";
      const content = [{ type: "text", text: `Done. URL: ${url}${downloadNote}` }];
      if (shot) content.push({ type: "image", data: shot.toString("base64"), mimeType: "image/png" });
      return { content };

    } catch (runErr) {
      log("error", "execute_failed", { skill: primary.entry.slug, error: runErr.message });
      appendRecoveryEvent({ event: "terminal_failure", slug: primary.entry.slug, error: runErr.message });
      _runTracker.emit("wf_fail", {
        dur: Date.now() - _wfStartAt,
        fsi: runErr.failedAt ?? null,
        fc:  mapErrorToCode(runErr),
      });
      await _tracker.flush();
      _tracker.destroy();
      const failResp = page ? await _buildFailureResponse(page, runErr, runErr.fromEntry || primary.entry) : err(runErr.message);
      if (page) await page.close().catch(() => {});
      if (watch) {
        await _context?.close().catch(() => {});
        await _browser?.close().catch(() => {});
      }
      return failResp;

    } finally {
      activeExecution = null;
    }
  }

  return err(`Unknown tool: ${name}`);
}

// MCP registration is handled by the official .mcpb Desktop Extension mechanism.
// Claude Desktop owns claude_desktop_config.json; we do not edit it directly.

async function _phonehome() {
  const companies = [...new Set(Object.values(skillIndex).map(s => s.company))];
  const body = JSON.stringify({
    runtime_version: RUNTIME_VERSION,
    companies,
    platform: process.platform,
    install_id: INSTALL_ID,
  });
  await new Promise((resolve) => {
    const req = https.request(`${CONXA_API}/api/v1/telemetry/runtime-start`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    }, (res) => { res.resume(); resolve(); });
    req.on("error", resolve);
    req.setTimeout(5000, () => { req.destroy(); resolve(); });
    req.write(body);
    req.end();
  });
}
