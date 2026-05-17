"use strict";
/**
 * In-process search over the resolver chain.
 *
 * No database, no FTS, no background indexing. On every call we ask each
 * resolver for its top matches and merge by (plugin_id, slug). Designed for
 * <100-plugin scale; swap behind this same interface when scale demands a real
 * index.
 *
 * Resolver order: installed > cache > registry. Each resolver exposes
 * search(query, limit) and getManifest(plugin_id).
 */
const installed = require("./resolver/installed");
const cache     = require("./resolver/cache");
const registry  = require("./resolver/registry");

const _SOURCE_PRIORITY = { "installed": 3, "cache": 2 };

function _key(item) {
  const slug = item.slug || (item.skills && item.skills[0]) || "";
  return `${item.plugin_id || ""}::${slug}`;
}

async function search(query, limit) {
  const cap = Math.max(1, Math.min(50, Number(limit) || 20));
  const remoteResults = await registry.search(query, cap);
  const local = [
    ...installed.search(query, cap),
    ...cache.search(query, cap),
  ];
  const merged = new Map();
  for (const item of [...local, ...remoteResults]) {
    const k = _key(item);
    const existing = merged.get(k);
    if (!existing) { merged.set(k, item); continue; }
    const a = _SOURCE_PRIORITY[existing.source] || 1;
    const b = _SOURCE_PRIORITY[item.source]     || 1;
    if (b > a) merged.set(k, item);
  }
  return Array.from(merged.values()).slice(0, cap);
}

async function getManifest(pluginId) {
  return (
    (await installed.getManifest(pluginId)) ||
    (await cache.getManifest(pluginId)) ||
    (await registry.getManifest(pluginId))
  );
}

module.exports = { search, getManifest };
