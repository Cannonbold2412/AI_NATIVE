"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

function loadInstallId(dataDir) {
  const installIdFile = path.join(dataDir, "identity", "install_id");
  try {
    if (fs.existsSync(installIdFile)) {
      const existing = fs.readFileSync(installIdFile, "utf8").trim();
      if (/^[A-Za-z0-9_-]{12,96}$/.test(existing)) return existing;
    }
    const next = crypto.randomUUID ? crypto.randomUUID() : crypto.randomBytes(16).toString("hex");
    fs.mkdirSync(path.dirname(installIdFile), { recursive: true });
    fs.writeFileSync(installIdFile, next, { encoding: "utf8", mode: 0o600 });
    return next;
  } catch (_) {
    return crypto.randomBytes(16).toString("hex");
  }
}

module.exports = { loadInstallId };
