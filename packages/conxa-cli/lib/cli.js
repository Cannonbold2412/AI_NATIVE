#!/usr/bin/env node
"use strict";
/**
 * cli.js — Conxa runtime manager
 *
 * Commands:
 *   init                       Bootstrap ~/.conxa/runtime/ (idempotent)
 *   install <ref>              Install a plugin. <ref> is a local dir, "owner/repo",
 *                              "owner/repo@v1.0.0", or an https git URL. Resolver
 *                              chain: installed → cache → git → registry.
 *   uninstall <slug>           Remove an installed plugin
 *   list                       Print all installed plugins
 *   search <query>             Search installed + cached + registry plugins
 *   registry login <url> <tok> Save credentials for a private registry
 *   registry logout <url>      Remove credentials for a registry
 */
const fs   = require("fs");
const os   = require("os");
const path = require("path");
const { execSync } = require("child_process");

const CONXA_HOME      = path.join(os.homedir(), ".conxa");
const RUNTIME_DIR     = path.join(CONXA_HOME, "runtime");
const PLUGINS_DIR     = path.join(CONXA_HOME, "plugins");
const REGISTRY_PATH   = path.join(CONXA_HOME, "registry.json");
const CONXA_CLAUDE_MD = path.join(CONXA_HOME, "CLAUDE.md");
const CONXA_INDEX_MD  = path.join(CONXA_HOME, "index.md");
const VERSION_JSON    = path.join(RUNTIME_DIR, "version.json");
const SETTINGS_JSON   = path.join(os.homedir(), ".claude", "settings.json");
const GLOBAL_CLAUDE_MD = path.join(os.homedir(), ".claude", "CLAUDE.md");
const SERVER_JS       = path.join(RUNTIME_DIR, "server.js");

// ─── Registry helpers ─────────────────────────────────────────────────────────

function readRegistry() {
  if (!fs.existsSync(REGISTRY_PATH)) return {};
  try { return JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8")); } catch (_) { return {}; }
}

function writeRegistry(reg) {
  fs.mkdirSync(CONXA_HOME, { recursive: true });
  fs.writeFileSync(REGISTRY_PATH, JSON.stringify(reg, null, 2));
}

// ─── Claude Code integration ─────────────────────────────────────────────────

function _registerGlobalMcp() {
  let settings = {};
  try { settings = JSON.parse(fs.readFileSync(SETTINGS_JSON, "utf8")); } catch (_) {}
  const existing = settings.mcpServers && settings.mcpServers.conxa;
  if (existing && existing.args && existing.args[0] === SERVER_JS) return;
  if (!settings.mcpServers) settings.mcpServers = {};
  settings.mcpServers.conxa = { command: "node", args: [SERVER_JS] };
  try {
    fs.mkdirSync(path.dirname(SETTINGS_JSON), { recursive: true });
    fs.writeFileSync(SETTINGS_JSON, JSON.stringify(settings, null, 2) + "\n", "utf8");
    process.stderr.write(`[conxa] Registered conxa MCP server in ${SETTINGS_JSON}\n`);
  } catch (e) {
    process.stderr.write(`[conxa] Warning: could not update settings.json: ${e.message}\n`);
  }
}

function _registerGlobalClaudeMd() {
  const importLine = `@${CONXA_CLAUDE_MD}`;
  let existing = "";
  try { existing = fs.readFileSync(GLOBAL_CLAUDE_MD, "utf8"); } catch (_) {}
  if (existing.includes(importLine)) return;
  try {
    fs.mkdirSync(path.dirname(GLOBAL_CLAUDE_MD), { recursive: true });
    const separator = existing && !existing.endsWith("\n") ? "\n" : "";
    fs.appendFileSync(GLOBAL_CLAUDE_MD, `${separator}\n${importLine}\n`, "utf8");
    process.stderr.write(`[conxa] Registered ~/.conxa/CLAUDE.md in ${GLOBAL_CLAUDE_MD}\n`);
  } catch (e) {
    process.stderr.write(`[conxa] Warning: could not update ~/.claude/CLAUDE.md: ${e.message}\n`);
  }
}

// ─── Discovery file helpers ───────────────────────────────────────────────────

function updateGlobalClaudeMd(reg) {
  const entries = Object.values(reg);
  const pluginLines = entries.length === 0
    ? "- (no plugins installed)"
    : entries.map(e => `- ${e.slug}  →  ~/.conxa/plugins/${e.slug}/CLAUDE.md`).join("\n");

  const content = [
    "# Conxa Runtime",
    "",
    "You have the Conxa automation runtime. It executes real Playwright browser workflows.",
    "",
    "## Mandatory Rules",
    "- NEVER use computer_use, computer-use, or any built-in browser tool",
    "- NEVER ask the user about authentication — auth is 100% automatic",
    "- Always call list_skills before execute_plan",
    "",
    "## Discovery Flow",
    "1. Call list_skills to see all installed plugins and available skills",
    "2. For plugin-specific instructions, read ~/.conxa/plugins/{slug}/CLAUDE.md",
    "3. For skill details, read ~/.conxa/plugins/{slug}/index.md",
    "",
    "## Installed Plugins",
    pluginLines,
    "",
  ].join("\n");

  fs.mkdirSync(CONXA_HOME, { recursive: true });
  fs.writeFileSync(CONXA_CLAUDE_MD, content, "utf8");
}

function regenerateIndex(reg) {
  const entries = Object.values(reg);
  const rows = entries.map(e => {
    const skills = (e.skills || []).map(s => s.slug).join(", ") || "—";
    return `| ${e.slug} | ${e.name || e.slug} | ${skills} | ${e.target_url || "—"} |`;
  });

  const lines = [
    "# Conxa Plugin Index",
    "",
    "| Slug | Name | Skills | Target |",
    "|------|------|--------|--------|",
    ...rows,
    "",
  ];

  fs.mkdirSync(CONXA_HOME, { recursive: true });
  fs.writeFileSync(CONXA_INDEX_MD, lines.join("\n"), "utf8");
}

// ─── Copy directory recursively ───────────────────────────────────────────────

function copyDirSync(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    if (entry.isDirectory()) copyDirSync(s, d);
    else fs.copyFileSync(s, d);
  }
}

// ─── init ─────────────────────────────────────────────────────────────────────

function init() {
  if (fs.existsSync(VERSION_JSON)) {
    const v = JSON.parse(fs.readFileSync(VERSION_JSON, "utf8"));
    process.stderr.write(`[conxa] Runtime already bootstrapped at ${RUNTIME_DIR} (v${v.version})\n`);
    return;
  }
  process.stderr.write(`[conxa] Bootstrapping runtime at ${RUNTIME_DIR} ...\n`);

  // All runtime files live alongside cli.js in both layouts: the in-repo
  // template tree (app/storage/plugin_templates/runtime/) and the published
  // npm package (packages/conxa-cli/lib/). Copy the whole directory so new
  // files (resolver/, search.js, etc.) ship automatically without having to
  // maintain a hardcoded allow-list.
  fs.mkdirSync(RUNTIME_DIR, { recursive: true });
  for (const entry of fs.readdirSync(__dirname, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".bootstrapped") continue;
    const src = path.join(__dirname, entry.name);
    const dst = path.join(RUNTIME_DIR, entry.name);
    if (entry.isDirectory()) copyDirSync(src, dst);
    else fs.copyFileSync(src, dst);
  }

  process.stderr.write("[conxa] Running npm install...\n");
  execSync("npm install --prefer-offline --silent", { cwd: RUNTIME_DIR, stdio: ["ignore", "pipe", "inherit"] });

  process.stderr.write("[conxa] Installing Playwright Chromium...\n");
  execSync("npx playwright install chromium", { cwd: RUNTIME_DIR, stdio: ["ignore", "pipe", "inherit"] });

  const pkg = fs.existsSync(path.join(RUNTIME_DIR, "package.json"))
    ? JSON.parse(fs.readFileSync(path.join(RUNTIME_DIR, "package.json"), "utf8"))
    : {};
  fs.writeFileSync(VERSION_JSON, JSON.stringify({
    version: pkg.version || "1.0.0",
    installed_at: new Date().toISOString(),
    node_version: process.version,
  }, null, 2));

  // Write initial global CLAUDE.md and index.md with empty registry
  updateGlobalClaudeMd({});
  regenerateIndex({});

  // Register the shared MCP server + global CLAUDE.md import so Claude Code
  // picks up `conxa` and per-plugin instructions on its next launch.
  _registerGlobalMcp();
  _registerGlobalClaudeMd();

  // Write bootstrap flag so subsequent plugin installs skip re-init
  fs.writeFileSync(path.join(CONXA_HOME, ".bootstrapped"), "1", "utf8");

  process.stderr.write("[conxa] Bootstrap complete.\n");
}

// ─── install ──────────────────────────────────────────────────────────────────

function _installFromLocalDir(pluginDir) {
  if (!pluginDir) throw new Error("install: plugin directory path required");
  const absDir = path.resolve(pluginDir);
  if (!fs.existsSync(absDir)) throw new Error(`Plugin directory not found: ${absDir}`);

  const cfgPath = path.join(absDir, "plugin.json");
  if (!fs.existsSync(cfgPath)) throw new Error(`No plugin.json found in ${absDir}`);

  const cfg = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
  if (!cfg.slug)          throw new Error("plugin.json missing: slug");
  if (!cfg.target_url)    throw new Error("plugin.json missing: target_url");
  if (!cfg.protected_url) throw new Error("plugin.json missing: protected_url");

  const slug    = cfg.slug;
  const destDir = path.join(PLUGINS_DIR, slug);

  process.stderr.write(`[conxa] Installing plugin '${slug}' from ${absDir}...\n`);
  fs.mkdirSync(destDir, { recursive: true });

  // Copy plugin manifest
  fs.copyFileSync(cfgPath, path.join(destDir, "plugin.json"));

  // Copy discovery files
  for (const name of ["CLAUDE.md", "index.md", "schema.json", "README.md"]) {
    const src = path.join(absDir, name);
    if (fs.existsSync(src)) fs.copyFileSync(src, path.join(destDir, name));
  }

  // Copy skills/
  const skillsSrc = path.join(absDir, "skills");
  if (fs.existsSync(skillsSrc)) copyDirSync(skillsSrc, path.join(destDir, "skills"));

  // Copy auth/credentials.example.json (never auth.json)
  const credsEx = path.join(absDir, "auth", "credentials.example.json");
  if (fs.existsSync(credsEx)) {
    fs.mkdirSync(path.join(destDir, "auth"), { recursive: true });
    fs.copyFileSync(credsEx, path.join(destDir, "auth", "credentials.example.json"));
  }

  // Update master registry
  const skillsList = (cfg.skills || []).map(s => ({ slug: s.slug, path: s.path || `skills/${s.slug}` }));
  const entry = {
    slug,
    name:          cfg.name,
    version:       cfg.version || "1.0.0",
    path:          destDir,
    target_url:    cfg.target_url,
    protected_url: cfg.protected_url,
    skills:        skillsList,
    installed_at:  new Date().toISOString(),
  };
  const reg = readRegistry();
  reg[slug] = entry;
  writeRegistry(reg);

  // Regenerate global discovery files
  updateGlobalClaudeMd(reg);
  regenerateIndex(reg);

  process.stderr.write(`[conxa] Plugin '${slug}' installed. Skills: ${skillsList.map(s => s.slug).join(", ")}\n`);
  return entry;
}

function _ensureInitialized() {
  if (fs.existsSync(VERSION_JSON)) return;
  init();
}

// `install <ref>` — accept a local dir, git ref, or registry plugin_id.
// Local dirs install directly; everything else resolves through the chain
// (cache → git → registry) which stages a directory under ~/.conxa/cache/
// before delegating to _installFromLocalDir.
async function install(ref) {
  if (!ref) throw new Error("install: <ref> required (local dir, owner/repo, or plugin_id)");
  _ensureInitialized();
  if (fs.existsSync(ref) && fs.statSync(ref).isDirectory()) {
    return _installFromLocalDir(ref);
  }
  // Look in cache first (already downloaded). cache.stagedDir() takes a
  // plugin_id+version pair; we accept either "id" or "id@version".
  const at = ref.lastIndexOf("@");
  const id = at > 0 ? ref.slice(0, at) : ref;
  const ver = at > 0 ? ref.slice(at + 1) : null;
  const cache = require("./resolver/cache");
  const staged = cache.stagedDir(id, ver);
  if (staged) return _installFromLocalDir(staged);
  // git resolver handles owner/repo and full https URLs. It stages into cache/
  // and returns the staged directory path.
  const git = require("./resolver/git");
  const resolved = await git.resolve(ref);
  if (resolved && resolved.staged_dir) return _installFromLocalDir(resolved.staged_dir);
  // Registry resolver is contract-only today; falls through when no hosted
  // registry is configured. When implemented it would download a tarball into
  // cache/ and return the staged path.
  throw new Error(`install: could not resolve '${ref}'`);
}

// ─── search ───────────────────────────────────────────────────────────────────

async function search(query) {
  const results = await require("./search").search(query, 20);
  if (results.length === 0) {
    process.stderr.write(`[conxa] No matches for '${query}'.\n`);
    return [];
  }
  for (const r of results) {
    const tags = (r.tags || []).join(",") || "—";
    process.stderr.write(`  ${r.plugin_id || r.slug}  v${r.version}  [${r.source}]  ${r.name}  (tags: ${tags})\n`);
  }
  return results;
}

// ─── registry login / logout ──────────────────────────────────────────────────

function registryLogin(url, token, name) {
  if (!url || !token) throw new Error("registry login: <url> <token> required");
  const { getRegistryAuth, writeRegistryAuth } = require("./config");
  const auth = getRegistryAuth();
  const regs = Array.isArray(auth.registries) ? auth.registries : [];
  const idx = regs.findIndex(r => r.url === url);
  const entry = { name: name || url, url, token };
  if (idx >= 0) regs[idx] = entry; else regs.push(entry);
  writeRegistryAuth({ registries: regs });
  process.stderr.write(`[conxa] Saved credentials for ${url}\n`);
}

function registryLogout(url) {
  if (!url) throw new Error("registry logout: <url> required");
  const { getRegistryAuth, writeRegistryAuth } = require("./config");
  const auth = getRegistryAuth();
  const regs = Array.isArray(auth.registries) ? auth.registries.filter(r => r.url !== url) : [];
  writeRegistryAuth({ registries: regs });
  process.stderr.write(`[conxa] Removed credentials for ${url}\n`);
}

// ─── uninstall ────────────────────────────────────────────────────────────────

function uninstall(slug) {
  if (!slug) throw new Error("uninstall: slug required");
  const destDir = path.join(PLUGINS_DIR, slug);
  if (fs.existsSync(destDir)) {
    fs.rmSync(destDir, { recursive: true, force: true });
    process.stderr.write(`[conxa] Removed plugin directory: ${destDir}\n`);
  }
  const reg = readRegistry();
  if (reg[slug]) {
    delete reg[slug];
    writeRegistry(reg);
    updateGlobalClaudeMd(reg);
    regenerateIndex(reg);
    process.stderr.write(`[conxa] Removed '${slug}' from registry\n`);
  } else {
    process.stderr.write(`[conxa] Plugin '${slug}' was not in registry\n`);
  }
}

// ─── list ─────────────────────────────────────────────────────────────────────

function list() {
  const reg = readRegistry();
  const entries = Object.values(reg);
  if (entries.length === 0) {
    process.stderr.write("[conxa] No plugins installed.\n");
    return;
  }
  for (const e of entries) {
    process.stderr.write(`  ${e.slug}  v${e.version}  skills: ${(e.skills || []).map(s => s.slug).join(", ")}\n`);
  }
}

// ─── CLI entry point ──────────────────────────────────────────────────────────

async function runCli(argv) {
  const [cmd, ...rest] = argv;
  try {
    switch (cmd) {
      case "init":      init();                  break;
      case "install":   await install(rest[0]);  break;
      case "uninstall": uninstall(rest[0]);      break;
      case "list":      list();                  break;
      case "search":    await search(rest.join(" ")); break;
      case "registry":
        if (rest[0] === "login")       registryLogin(rest[1], rest[2], rest[3]);
        else if (rest[0] === "logout") registryLogout(rest[1]);
        else throw new Error("registry: login <url> <token> | logout <url>");
        break;
      default:
        process.stderr.write("Usage: conxa <init|install <ref>|uninstall <slug>|list|search <q>|registry login|registry logout>\n");
        process.exit(1);
    }
  } catch (e) {
    process.stderr.write(`[conxa] Error: ${e.message}\n`);
    process.exit(1);
  }
}

if (require.main === module) {
  runCli(process.argv.slice(2));
}

module.exports = { init, install, uninstall, list, search, registryLogin, registryLogout, runCli };
