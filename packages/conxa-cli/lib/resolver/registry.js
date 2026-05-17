"use strict";
/**
 * Resolver — hosted public/private registries.
 *
 * Contract-only stub. Reads ~/.conxa/auth/registry.json:
 *   { "registries": [{ "name": "...", "url": "https://...", "token": "..." }] }
 *
 * Until a hosted registry exists, search()/getManifest()/resolve() return
 * empty/null. The HTTP shape is documented for the future server:
 *   GET <url>/v1/search?q=...&limit=...     → [{ plugin_id, version, name, description, tags, auth_requirements, manifest_url, tarball_url }]
 *   GET <url>/v1/plugins/<id>/manifest      → plugin.json
 *   GET <url>/v1/plugins/<id>@<ver>/tarball → gzipped tar of data-only artifact
 *   Authorization: Bearer <token>
 */
const https = require("https");
const { URL } = require("url");
const { getRegistryAuth } = require("../config");

const HTTP_TIMEOUT_MS = 8000;

function _fetchJson(url, token) {
  return new Promise((resolve, reject) => {
    let parsed;
    try { parsed = new URL(url); } catch (e) { return reject(e); }
    const headers = { "Accept": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const req = https.request({
      method: "GET",
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: parsed.pathname + parsed.search,
      headers,
      timeout: HTTP_TIMEOUT_MS,
    }, (res) => {
      const chunks = [];
      res.on("data", c => chunks.push(c));
      res.on("end", () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
          catch (e) { reject(e); }
        } else {
          reject(new Error(`registry returned ${res.statusCode}`));
        }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(new Error("registry timeout")); });
    req.end();
  });
}

async function _searchOne(reg, query, limit) {
  const url = `${reg.url.replace(/\/$/, "")}/v1/search?q=${encodeURIComponent(query)}&limit=${limit}`;
  try {
    const body = await _fetchJson(url, reg.token);
    if (!Array.isArray(body)) return [];
    return body.map(item => ({ ...item, source: `registry:${reg.name || "default"}` }));
  } catch (_) {
    return [];
  }
}

async function search(query, limit) {
  const auth = getRegistryAuth();
  const regs = (auth && Array.isArray(auth.registries)) ? auth.registries : [];
  if (regs.length === 0) return [];
  const results = await Promise.all(regs.map(r => _searchOne(r, query, limit || 20)));
  return [].concat(...results).slice(0, limit || 20);
}

async function getManifest(pluginId) {
  const auth = getRegistryAuth();
  const regs = (auth && Array.isArray(auth.registries)) ? auth.registries : [];
  for (const reg of regs) {
    try {
      return await _fetchJson(`${reg.url.replace(/\/$/, "")}/v1/plugins/${pluginId}/manifest`, reg.token);
    } catch (_) { /* try next */ }
  }
  return null;
}

// Tarball download is a follow-up; install path uses git resolver until the
// hosted registry exists.
async function resolve() { return null; }

function list() { return []; }

module.exports = { search, getManifest, resolve, list, name: "registry" };
