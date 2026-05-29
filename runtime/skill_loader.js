"use strict";
const fs     = require("fs");
const path   = require("path");
const crypto = require("crypto");

// Scan skill-packs/ dir → flat index { "company:slug": {slug, company, skillDir, manifest, pack} }
function loadSkillRegistry(skillPacksDir, cacheDir) {
  const index = {};
  if (!fs.existsSync(skillPacksDir)) return index;

  for (const company of fs.readdirSync(skillPacksDir)) {
    const companyDir = path.join(skillPacksDir, company);
    let stat;
    try { stat = fs.statSync(companyDir); } catch (_) { continue; }
    if (!stat.isDirectory()) continue;

    const packPath = path.join(companyDir, "pack.json");
    if (!fs.existsSync(packPath)) continue;

    let pack;
    try { pack = JSON.parse(fs.readFileSync(packPath, "utf8")); } catch (_) { continue; }

    for (const slug of (pack.skills || [])) {
      const skillDir     = path.join(companyDir, slug);
      const manifestPath = path.join(skillDir, "manifest.json");
      if (!fs.existsSync(manifestPath)) continue;
      let manifest;
      try { manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8")); } catch (_) { continue; }
      index[`${company}:${slug}`] = { slug, company, skillDir, manifest, pack };
    }
  }

  // Persist flat index to cache for fast startup
  if (cacheDir) {
    try {
      fs.mkdirSync(cacheDir, { recursive: true });
      fs.writeFileSync(path.join(cacheDir, "manifests.json"), JSON.stringify(index, null, 2));
    } catch (_) {}
  }

  return index;
}

// Load from cache (instant) — falls back to full scan if cache missing
function loadSkillRegistryFromCache(skillPacksDir, cacheDir) {
  const cachePath = path.join(cacheDir, "manifests.json");
  if (fs.existsSync(cachePath)) {
    try {
      return JSON.parse(fs.readFileSync(cachePath, "utf8"));
    } catch (_) {}
  }
  return loadSkillRegistry(skillPacksDir, cacheDir);
}

// Verify SHA-256 checksums declared in manifest.json
// Throws Error if any file is missing or hash mismatches
function verifySkillIntegrity(skillDir, manifest) {
  const checksums = manifest.checksum || {};
  for (const [file, expected] of Object.entries(checksums)) {
    const fullPath = path.join(skillDir, file);
    if (!fs.existsSync(fullPath))
      throw new Error(`Integrity: missing ${file} in ${path.basename(skillDir)}`);
    const actual = crypto.createHash("sha256").update(fs.readFileSync(fullPath)).digest("hex");
    if (actual !== expected)
      throw new Error(`Integrity: ${file} checksum mismatch`);
  }
}

// Reload a single skill in the live index without process restart
function hotReloadSkill(company, slug, skillPacksDir, index) {
  const skillDir     = path.join(skillPacksDir, company, slug);
  const manifestPath = path.join(skillDir, "manifest.json");
  const key          = `${company}:${slug}`;
  if (!fs.existsSync(manifestPath)) {
    delete index[key];
    return;
  }
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const packPath  = path.join(skillPacksDir, company, "pack.json");
    const pack      = fs.existsSync(packPath) ? JSON.parse(fs.readFileSync(packPath, "utf8")) : {};
    index[key] = { slug, company, skillDir, manifest, pack };
  } catch (_) {}
}

module.exports = { loadSkillRegistry, loadSkillRegistryFromCache, verifySkillIntegrity, hotReloadSkill };
