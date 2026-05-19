"use strict";
const crypto = require("crypto");
const fs     = require("fs");
const path   = require("path");
const https  = require("https");

const SERVICE    = "conxa";
const CONXA_API  = process.env.CONXA_API_URL || "https://api.conxa.io";

// keytar loaded at runtime (native .node file alongside exe or regular require)
let _keytar = null;
function _getKeytar() {
  if (_keytar) return _keytar;
  try {
    if (process.pkg) {
      // running as pkg bundle: keytar.node is a sibling of the exe
      const nativePath = path.join(path.dirname(process.execPath), "keytar.node");
      const mod = { exports: {} };
      process.dlopen(mod, nativePath);
      _keytar = mod.exports;
    } else {
      _keytar = require("keytar");
    }
  } catch (e) {
    // keytar unavailable — fall back to plaintext file (dev/testing only)
    _keytar = {
      _file: path.join(process.env.CONXA_DATA_DIR || require("os").homedir() + "/.conxa", "cache", ".keytar.json"),
      _load() {
        try { return JSON.parse(fs.readFileSync(this._file, "utf8")); } catch (_) { return {}; }
      },
      async getPassword(svc, acct) { return this._load()[`${svc}:${acct}`] || null; },
      async setPassword(svc, acct, val) {
        const data = this._load();
        data[`${svc}:${acct}`] = val;
        fs.mkdirSync(path.dirname(this._file), { recursive: true });
        fs.writeFileSync(this._file, JSON.stringify(data, null, 2));
      },
    };
  }
  return _keytar;
}

// In-flight refresh locks
const _refreshLocks = new Map();

async function getToken(company) {
  const raw = await _getKeytar().getPassword(SERVICE, company);
  if (!raw) return null;
  try {
    const stored = JSON.parse(raw);
    if (stored.expires_at && Date.now() > new Date(stored.expires_at).getTime() - 300000) {
      return await refreshToken(company, stored.token);
    }
    return stored.token;
  } catch (_) {
    return raw; // legacy raw string
  }
}

async function setToken(company, token, expiresAt = null) {
  await _getKeytar().setPassword(SERVICE, company, JSON.stringify({ token, expires_at: expiresAt }));
}

async function refreshToken(company, oldToken) {
  if (_refreshLocks.has(company)) return _refreshLocks.get(company);
  const p = _doRefresh(company, oldToken);
  _refreshLocks.set(company, p);
  try {
    const result = await p;
    _refreshLocks.delete(company);
    return result;
  } catch (e) {
    _refreshLocks.delete(company);
    return null;
  }
}

function _doRefresh(company, oldToken) {
  return new Promise((resolve) => {
    const body = JSON.stringify({ token: oldToken, company });
    const req  = https.request(`${CONXA_API}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
    }, (res) => {
      let data = "";
      res.on("data", c => data += c);
      res.on("end", async () => {
        if (res.statusCode === 200) {
          try {
            const parsed = JSON.parse(data);
            await setToken(company, parsed.token, parsed.expires_at);
            resolve(parsed.token);
          } catch (_) { resolve(null); }
        } else {
          resolve(null);
        }
      });
    });
    req.on("error", () => resolve(null));
    req.setTimeout(5000, () => { req.destroy(); resolve(null); });
    req.write(body);
    req.end();
  });
}

function getAuthChallengeUrl(company) {
  const nonce = crypto.randomBytes(16).toString("hex");
  const url   = `https://app.conxa.io/auth/cli?company=${encodeURIComponent(company)}&nonce=${nonce}`;
  return { url, nonce };
}

// Session encryption — AES-256-GCM, key from Conxa token via HKDF
const HKDF_INFO = Buffer.from("conxa-session-v1");

function _deriveKey(token) {
  return crypto.hkdfSync("sha256", Buffer.from(token), Buffer.alloc(32), HKDF_INFO, 32);
}

function saveEncryptedSession(company, state, token, sessionsDir) {
  try {
    const key    = _deriveKey(token);
    const iv     = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
    const enc    = Buffer.concat([cipher.update(JSON.stringify(state)), cipher.final()]);
    const tag    = cipher.getAuthTag();
    const payload = JSON.stringify({
      iv:   iv.toString("base64"),
      tag:  tag.toString("base64"),
      data: enc.toString("base64"),
    });
    fs.mkdirSync(sessionsDir, { recursive: true });
    fs.writeFileSync(path.join(sessionsDir, `${company}_state.json`), payload);
  } catch (_) {}
}

function loadDecryptedSession(company, token, sessionsDir) {
  const sessionPath = path.join(sessionsDir, `${company}_state.json`);
  if (!fs.existsSync(sessionPath)) return null;
  try {
    const { iv, tag, data } = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
    const key     = _deriveKey(token);
    const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(iv, "base64"));
    decipher.setAuthTag(Buffer.from(tag, "base64"));
    const dec = Buffer.concat([decipher.update(Buffer.from(data, "base64")), decipher.final()]);
    return JSON.parse(dec.toString());
  } catch (_) {
    return null; // corrupted or wrong token — fresh session needed
  }
}

// Save unencrypted session (fallback when no token yet — target website auth before Conxa auth)
function saveRawSession(company, state, sessionsDir) {
  try {
    fs.mkdirSync(sessionsDir, { recursive: true });
    fs.writeFileSync(
      path.join(sessionsDir, `${company}_raw_state.json`),
      JSON.stringify(state, null, 2),
      { mode: 0o600 }
    );
  } catch (_) {}
}

function loadRawSession(company, sessionsDir) {
  const p = path.join(sessionsDir, `${company}_raw_state.json`);
  try { return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null; } catch (_) { return null; }
}

module.exports = {
  getToken,
  setToken,
  refreshToken,
  getAuthChallengeUrl,
  saveEncryptedSession,
  loadDecryptedSession,
  saveRawSession,
  loadRawSession,
};
