"use strict";
const fs     = require("fs");
const path   = require("path");
const crypto = require("crypto");
const https  = require("https");

function _fetchJSON(url, token, timeoutMs) {
  return new Promise((resolve, reject) => {
    const headers = { "User-Agent": "conxa-runtime/1.0" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const req = https.get(url, { headers }, (res) => {
      let data = "";
      res.on("data", c => data += c);
      res.on("end", () => {
        if (res.statusCode === 200) {
          try { resolve(JSON.parse(data)); }
          catch (e) { reject(new Error(`JSON parse error: ${e.message}`)); }
        } else if (res.statusCode === 304) {
          resolve({ files: [] }); // not modified
        } else {
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      });
    });
    req.setTimeout(timeoutMs || 8000, () => { req.destroy(); reject(new Error("request timeout")); });
    req.on("error", reject);
  });
}

function _downloadBuffer(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, (res) => {
      const chunks = [];
      res.on("data", c => chunks.push(c));
      res.on("end", () => resolve(Buffer.concat(chunks)));
      res.on("error", reject);
    });
    req.setTimeout(timeoutMs || 15000, () => { req.destroy(); reject(new Error("download timeout")); });
    req.on("error", reject);
  });
}

// Write to .tmp, verify SHA-256, rename atomically
function atomicWrite(targetPath, content, expectedSha256) {
  const tmpPath = targetPath + ".tmp";
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(tmpPath, content);
  const actual = crypto.createHash("sha256").update(content).digest("hex");
  if (actual !== expectedSha256) {
    try { fs.unlinkSync(tmpPath); } catch (_) {}
    throw new Error(`Checksum mismatch for ${path.basename(targetPath)}: expected ${expectedSha256}`);
  }
  fs.renameSync(tmpPath, targetPath);
}

function backupSkill(skillDir) {
  const backupDir = skillDir + ".bak";
  if (fs.existsSync(skillDir)) {
    if (fs.existsSync(backupDir)) {
      try { fs.rmSync(backupDir, { recursive: true }); } catch (_) {}
    }
    try { fs.cpSync(skillDir, backupDir, { recursive: true }); } catch (_) {}
  }
}

function restoreSkillBackup(skillDir) {
  const backupDir = skillDir + ".bak";
  if (fs.existsSync(backupDir)) {
    try {
      if (fs.existsSync(skillDir)) fs.rmSync(skillDir, { recursive: true });
      fs.renameSync(backupDir, skillDir);
    } catch (_) {}
  }
}

async function _doSync(skillPacksDir, authManager, log) {
  if (!fs.existsSync(skillPacksDir)) return;

  for (const company of fs.readdirSync(skillPacksDir)) {
    const packPath = path.join(skillPacksDir, company, "pack.json");
    if (!fs.existsSync(packPath)) continue;

    let pack;
    try { pack = JSON.parse(fs.readFileSync(packPath, "utf8")); } catch (_) { continue; }

    const syncEndpoint = pack.sync_endpoint;
    if (!syncEndpoint) continue;

    const token = await authManager.getToken(company);
    if (!token) {
      log(`[sync] ${company}: no auth token — skipping`);
      continue;
    }

    let delta;
    try {
      const url = `${syncEndpoint}?since=${encodeURIComponent(pack.skill_pack_version || "0")}`;
      delta = await _fetchJSON(url, token, 8000);
    } catch (e) {
      log(`[sync] ${company}: delta fetch failed — ${e.message}`);
      continue;
    }

    if (!delta.files || delta.files.length === 0) {
      log(`[sync] ${company}: up to date`);
      continue;
    }

    const updatedSlugs = new Set(delta.files.map(f => f.skill).filter(Boolean));
    for (const slug of updatedSlugs)
      backupSkill(path.join(skillPacksDir, company, slug));

    let allOk = true;
    for (const fileEntry of delta.files) {
      const targetPath = path.join(skillPacksDir, company, fileEntry.path);
      try {
        let content;
        if (fileEntry.content_base64) {
          content = Buffer.from(fileEntry.content_base64, "base64");
        } else if (fileEntry.content_url) {
          content = await _downloadBuffer(fileEntry.content_url, 15000);
        } else {
          throw new Error("no content source in delta entry");
        }
        atomicWrite(targetPath, content, fileEntry.sha256);
      } catch (e) {
        log(`[sync] ${company}/${fileEntry.path}: failed — ${e.message}`);
        for (const slug of updatedSlugs)
          restoreSkillBackup(path.join(skillPacksDir, company, slug));
        allOk = false;
        break;
      }
    }

    if (!allOk) continue;

    // Bump version only after all files written and verified
    pack.skill_pack_version = delta.current_version;
    pack.last_synced = new Date().toISOString();
    const packTmp = packPath + ".tmp";
    fs.writeFileSync(packTmp, JSON.stringify(pack, null, 2));
    fs.renameSync(packTmp, packPath);

    // Clean up backups on success
    for (const slug of updatedSlugs) {
      const backupDir = path.join(skillPacksDir, company, slug + ".bak");
      try { if (fs.existsSync(backupDir)) fs.rmSync(backupDir, { recursive: true }); } catch (_) {}
    }

    log(`[sync] ${company}: updated to ${delta.current_version} (${delta.files.length} files)`);
  }
}

// Public: run sync with a hard timeout
async function syncSkillPacks(skillPacksDir, authManager, { timeoutMs = 3000, log = console.error } = {}) {
  await Promise.race([
    _doSync(skillPacksDir, authManager, log),
    new Promise((_, reject) => setTimeout(() => reject(new Error("sync timeout")), timeoutMs)),
  ]);
}

module.exports = { syncSkillPacks };
