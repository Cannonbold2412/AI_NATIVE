"use strict";
const fs   = require("fs");
const os   = require("os");
const path = require("path");

const CONXA_HOME     = path.join(os.homedir(), ".conxa");
const REGISTRY_PATH  = path.join(CONXA_HOME, "registry.json");
const CONXA_CLAUDE_MD = path.join(CONXA_HOME, "CLAUDE.md");
const CONXA_INDEX_MD  = path.join(CONXA_HOME, "index.md");
const CACHE_DIR       = path.join(CONXA_HOME, "cache");
const AUTH_DIR        = path.join(CONXA_HOME, "auth");
const REGISTRY_AUTH_PATH = path.join(AUTH_DIR, "registry.json");

function getPluginDir(slug) {
  return path.join(CONXA_HOME, "plugins", slug);
}

function getAuthJson(slug) {
  return path.join(CONXA_HOME, "plugins", slug, "auth", "auth.json");
}

function getPluginConfig(slug) {
  const cfgPath = path.join(getPluginDir(slug), "plugin.json");
  try { return JSON.parse(fs.readFileSync(cfgPath, "utf8")); }
  catch (e) { throw new Error(`Plugin "${slug}" has a malformed plugin.json: ${e.message}`); }
}

function getRegistry() {
  if (!fs.existsSync(REGISTRY_PATH)) return {};
  try { return JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8")); }
  catch (e) {
    const bak = REGISTRY_PATH + ".bak";
    try { fs.renameSync(REGISTRY_PATH, bak); } catch (_) {}
    process.stderr.write(`[conxa] Warning: registry.json was corrupt (${e.message}) — backed up to registry.json.bak\n`);
    return {};
  }
}

function getRegistryAuth() {
  const fromEnv = process.env.CONXA_REGISTRY_TOKEN;
  let stored = { registries: [] };
  if (fs.existsSync(REGISTRY_AUTH_PATH)) {
    try { stored = JSON.parse(fs.readFileSync(REGISTRY_AUTH_PATH, "utf8")); }
    catch (_) { stored = { registries: [] }; }
  }
  if (fromEnv && !stored.registries.some(r => r.token === fromEnv))
    stored.registries = [{ name: "env", url: "*", token: fromEnv }, ...stored.registries];
  return stored;
}

function writeRegistryAuth(payload) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.writeFileSync(REGISTRY_AUTH_PATH, JSON.stringify(payload, null, 2) + "\n", { mode: 0o600 });
}

module.exports = {
  CONXA_HOME, REGISTRY_PATH, CONXA_CLAUDE_MD, CONXA_INDEX_MD,
  CACHE_DIR, AUTH_DIR, REGISTRY_AUTH_PATH,
  getPluginDir, getAuthJson, getPluginConfig, getRegistry,
  getRegistryAuth, writeRegistryAuth,
};
