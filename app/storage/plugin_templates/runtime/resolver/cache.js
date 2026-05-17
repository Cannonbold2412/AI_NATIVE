"use strict";
/**
 * Resolver — cache (~/.conxa/cache/<plugin_id>@<version>/).
 *
 * Plugins already downloaded but not yet installed (e.g. fetched by
 * a previous resolver run). Lookup by plugin_id; install reads the
 * staged directory.
 */
const fs   = require("fs");
const path = require("path");
const { CACHE_DIR } = require("../config");

function _safeSlug(id) {
  return String(id || "").replace(/[^a-zA-Z0-9._@\/-]/g, "_");
}

function _cacheRoot(pluginId, version) {
  const slug = _safeSlug(pluginId).replace(/\//g, "__");
  const ver  = version ? `@${_safeSlug(version)}` : "";
  return path.join(CACHE_DIR, `${slug}${ver}`);
}

function _readManifest(dir) {
  const cfgPath = path.join(dir, "plugin.json");
  if (!fs.existsSync(cfgPath)) return null;
  try { return JSON.parse(fs.readFileSync(cfgPath, "utf8")); } catch (_) { return null; }
}

function list() {
  if (!fs.existsSync(CACHE_DIR)) return [];
  const out = [];
  for (const name of fs.readdirSync(CACHE_DIR)) {
    const dir = path.join(CACHE_DIR, name);
    if (!fs.statSync(dir).isDirectory()) continue;
    const manifest = _readManifest(dir);
    if (!manifest) continue;
    out.push({
      plugin_id:         manifest.id || name,
      slug:              manifest.slug,
      name:              manifest.name || manifest.slug,
      description:       manifest.description || "",
      tags:              manifest.tags || [],
      visibility:        manifest.visibility || "private",
      version:           manifest.version || "0.0.0",
      auth_requirements: manifest.auth_requirements || null,
      source:            "cache",
      _cache_dir:        dir,
      skills:            (manifest.skills || []).map(s => s.slug),
    });
  }
  return out;
}

function search(query, limit) {
  const q = String(query || "").trim().toLowerCase();
  const all = list();
  if (!q) return all.slice(0, limit || 20);
  const ranked = [];
  for (const item of all) {
    const hay = `${item.plugin_id} ${item.slug} ${item.name} ${item.description} ${(item.tags || []).join(" ")}`.toLowerCase();
    if (!hay.includes(q)) continue;
    const score = (item.tags || []).some(t => String(t).toLowerCase() === q) ? 2 : 1;
    ranked.push({ score, item });
  }
  ranked.sort((a, b) => b.score - a.score);
  return ranked.slice(0, limit || 20).map(r => r.item);
}

async function getManifest(pluginId) {
  for (const item of list()) {
    if (item.plugin_id === pluginId || item.slug === pluginId) {
      return _readManifest(item._cache_dir);
    }
  }
  return null;
}

function stagedDir(pluginId, version) {
  const dir = _cacheRoot(pluginId, version);
  return fs.existsSync(dir) ? dir : null;
}

function ensureStagedDir(pluginId, version) {
  const dir = _cacheRoot(pluginId, version);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

module.exports = { list, search, getManifest, stagedDir, ensureStagedDir, name: "cache" };
