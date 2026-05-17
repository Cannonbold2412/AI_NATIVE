"use strict";
/**
 * Resolver — installed plugins (~/.conxa/registry.json).
 *
 * Fastest tier: surfaces what's already on disk.
 */
const fs   = require("fs");
const path = require("path");
const { getRegistry, getPluginDir } = require("../config");

function _readManifest(pluginDir) {
  const cfgPath = path.join(pluginDir, "plugin.json");
  if (!fs.existsSync(cfgPath)) return null;
  try { return JSON.parse(fs.readFileSync(cfgPath, "utf8")); } catch (_) { return null; }
}

function _lightweight(entry, manifest) {
  return {
    plugin_id:         (manifest && manifest.id) || entry.slug,
    slug:              entry.slug,
    name:              manifest && manifest.name        || entry.name        || entry.slug,
    description:       manifest && manifest.description || "",
    tags:              (manifest && manifest.tags) || [],
    visibility:        (manifest && manifest.visibility) || "private",
    version:           entry.version || (manifest && manifest.version) || "0.0.0",
    auth_requirements: (manifest && manifest.auth_requirements) || null,
    source:            "installed",
    skills:            (entry.skills || []).map(s => s.slug),
  };
}

function list() {
  const reg = getRegistry();
  return Object.values(reg).map(entry => {
    const manifest = _readManifest(getPluginDir(entry.slug));
    return _lightweight(entry, manifest);
  });
}

function search(query, limit) {
  const q = String(query || "").trim().toLowerCase();
  const all = list();
  if (!q) return all.slice(0, limit || 20);
  const ranked = [];
  for (const item of all) {
    const hay = `${item.plugin_id} ${item.slug} ${item.name} ${item.description} ${(item.tags || []).join(" ")}`.toLowerCase();
    if (!hay.includes(q)) continue;
    // Tag-exact bias
    const score = (item.tags || []).some(t => String(t).toLowerCase() === q) ? 2 : 1;
    ranked.push({ score, item });
  }
  ranked.sort((a, b) => b.score - a.score);
  return ranked.slice(0, limit || 20).map(r => r.item);
}

async function getManifest(pluginId) {
  for (const item of list()) {
    if (item.plugin_id === pluginId || item.slug === pluginId) {
      return _readManifest(getPluginDir(item.slug));
    }
  }
  return null;
}

module.exports = { list, search, getManifest, name: "installed" };
