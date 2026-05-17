"use strict";
/**
 * Resolver — git+https.
 *
 * Accepts plugin refs in any of:
 *   - "owner/repo"
 *   - "owner/repo@v1.0.0"
 *   - "https://github.com/owner/repo[.git][@v1.0.0]"
 *   - "git+https://..."
 *
 * Clones a shallow copy into ~/.conxa/cache/<id>@<version>/ so the cache
 * resolver picks it up. Provides no search() — git resolution is install-only.
 */
const { execFileSync } = require("child_process");
const cache = require("./cache");

const _GH_OWNER_REPO = /^([a-zA-Z0-9._-]+)\/([a-zA-Z0-9._-]+)(?:@(.+))?$/;
const _GIT_URL       = /^(?:git\+)?(https?:\/\/[^@]+?)(?:\.git)?(?:@(.+))?$/i;

function _parseRef(ref) {
  const text = String(ref || "").trim();
  if (!text) return null;
  let m = _GH_OWNER_REPO.exec(text);
  if (m) return { url: `https://github.com/${m[1]}/${m[2]}.git`, version: m[3] || null, id: `${m[1]}/${m[2]}` };
  m = _GIT_URL.exec(text);
  if (m) {
    const url    = `${m[1]}.git`;
    const path   = m[1].replace(/^https?:\/\/[^/]+\//, "");
    return { url, version: m[2] || null, id: path };
  }
  return null;
}

function _clone(url, version, destDir) {
  const args = ["clone", "--depth", "1"];
  if (version) args.push("--branch", version);
  args.push(url, destDir);
  execFileSync("git", args, { stdio: ["ignore", "pipe", "inherit"] });
}

async function resolve(pluginRef) {
  const parsed = _parseRef(pluginRef);
  if (!parsed) return null;
  const version = parsed.version || "main";
  const staged = cache.stagedDir(parsed.id, version);
  if (staged) return { staged_dir: staged, plugin_id: parsed.id, version, source: "git" };
  const dir = cache.ensureStagedDir(parsed.id, version);
  try {
    _clone(parsed.url, parsed.version, dir);
  } catch (e) {
    // Retry without branch if version refspec is wrong (lets us still clone HEAD)
    if (parsed.version) {
      try {
        const fallback = cache.ensureStagedDir(parsed.id, "main");
        _clone(parsed.url, null, fallback);
        return { staged_dir: fallback, plugin_id: parsed.id, version: "main", source: "git" };
      } catch (e2) {
        throw new Error(`git clone failed: ${e2.message}`);
      }
    }
    throw new Error(`git clone failed: ${e.message}`);
  }
  return { staged_dir: dir, plugin_id: parsed.id, version, source: "git" };
}

async function getManifest(pluginRef) {
  const result = await resolve(pluginRef);
  if (!result) return null;
  return cache.getManifest(result.plugin_id);
}

// Git resolver does not support search — it can only resolve a concrete ref.
function search() { return []; }
function list()   { return []; }

module.exports = { resolve, getManifest, search, list, name: "git" };
