"use strict";
const { chromium } = require("playwright");
const fs   = require("fs");
const path = require("path");
const os   = require("os");

const CONXA_DIR      = process.env.CONXA_DIR || (
  process.platform === "win32" ? "C:\\Program Files\\Conxa" : path.join(os.homedir(), ".conxa")
);
const CONXA_DATA_DIR = process.env.CONXA_DATA_DIR || (
  process.platform === "win32"
    ? path.join(os.homedir(), "AppData", "Roaming", "Conxa")
    : path.join(os.homedir(), ".conxa")
);
const SESSIONS_DIR = path.join(CONXA_DATA_DIR, "cache", "sessions");

// ─── Browser cache (per-company, 5-min idle timeout) ─────────────────────────

const _cache    = new Map();
const IDLE_MS   = 5 * 60 * 1000;

function _scheduleCleanup(company) {
  const entry = _cache.get(company);
  if (!entry) return;
  clearTimeout(entry.idleTimer);
  entry.idleTimer = setTimeout(async () => {
    const b = entry.browser;
    _cache.delete(company);
    if (b) await b.close().catch(() => {});
  }, IDLE_MS);
}

async function getCachedBrowser(company, authManager, opts = {}) {
  const headless = opts.headless !== false; // default true
  if (headless) {
    const entry = _cache.get(company);
    if (entry && entry.browser && entry.context) {
      try {
        entry.context.pages(); // throws if closed
        _scheduleCleanup(company);
        return { browser: entry.browser, context: entry.context, cached: true };
      } catch (_) {
        _cache.delete(company);
      }
    }
  }
  const result = await getAuthContext(company, authManager, { headless });
  if (headless) {
    _cache.set(company, { browser: result.browser, context: result.context, idleTimer: null });
    _scheduleCleanup(company);
  }
  return { ...result, cached: false };
}

// ─── Session management ───────────────────────────────────────────────────────

function _isAuthenticated(page, protectedUrl) {
  try {
    const u = new URL(page.url());
    return u.hostname === new URL(protectedUrl).hostname && !u.pathname.startsWith("/login");
  } catch (_) { return false; }
}

async function getAuthContext(company, authManager, opts = {}) {
  const headless = opts.headless !== false; // default true
  // Resolve pack config for this company
  const packPath = path.join(CONXA_DIR, "skill-packs", company, "pack.json");
  let pack = {};
  try { pack = JSON.parse(fs.readFileSync(packPath, "utf8")); } catch (_) {}
  const protectedUrl = pack.protected_url || pack.target_url || "";
  const targetUrl    = pack.target_url    || protectedUrl;

  // Try encrypted session (requires Conxa token)
  if (authManager) {
    try {
      const token = await authManager.getToken(company);
      if (token) {
        const stored = authManager.loadDecryptedSession(company, token, SESSIONS_DIR);
        if (stored) {
          const browser  = await chromium.launch({ headless });
          const context  = await browser.newContext({ storageState: stored });
          if (protectedUrl) {
            const page = await context.newPage();
            await page.goto(protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
            await page.waitForTimeout(1500);
            if (_isAuthenticated(page, protectedUrl)) {
              await page.close();
              return { browser, context, sessionSource: "encrypted" };
            }
            await browser.close();
            // Session expired — fall through to raw session check
          } else {
            return { browser, context, sessionSource: "encrypted" };
          }
        }
      }
    } catch (_) {}
  }

  // Try raw session (installer-included initial session, not yet encrypted)
  const rawSessionPath = path.join(SESSIONS_DIR, `${company}_raw_state.json`);
  if (fs.existsSync(rawSessionPath)) {
    let stored;
    try { stored = JSON.parse(fs.readFileSync(rawSessionPath, "utf8")); } catch (_) {}
    if (stored) {
      const browser  = await chromium.launch({ headless });
      const context  = await browser.newContext({ storageState: stored });
      if (protectedUrl) {
        const page = await context.newPage();
        await page.goto(protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
        await page.waitForTimeout(1500);
        if (_isAuthenticated(page, protectedUrl)) {
          await page.close();
          return { browser, context, sessionSource: "raw" };
        }
        await browser.close();
      } else {
        return { browser, context, sessionSource: "raw" };
      }
    }
  }

  // No valid session — open interactive browser for user to log in
  if (!targetUrl) throw new Error(`No target_url configured for company ${company}. Cannot authenticate.`);

  const loginBrowser = await chromium.launch({ headless: false });
  const loginCtx     = await loginBrowser.newContext();
  const loginPage    = await loginCtx.newPage();
  await loginPage.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });

  if (protectedUrl) {
    try {
      await loginPage.waitForURL(
        url => url.href.startsWith(protectedUrl) && !url.href.includes("/login"),
        { timeout: 300000 }
      );
    } catch (_) {
      await loginBrowser.close();
      throw new Error(`Authentication timed out for ${company}. Please log in and retry.`);
    }
  }

  const state = await loginCtx.storageState();
  await loginBrowser.close();

  // Save as raw session — will be re-encrypted once Conxa token is available
  if (authManager) {
    try {
      const token = await authManager.getToken(company);
      if (token) {
        authManager.saveEncryptedSession(company, state, token, SESSIONS_DIR);
      } else {
        authManager.saveRawSession(company, state, SESSIONS_DIR);
      }
    } catch (_) {
      authManager.saveRawSession(company, state, SESSIONS_DIR);
    }
  } else {
    fs.mkdirSync(SESSIONS_DIR, { recursive: true });
    fs.writeFileSync(path.join(SESSIONS_DIR, `${company}_raw_state.json`), JSON.stringify(state, null, 2), { mode: 0o600 });
  }

  const browser  = await chromium.launch({ headless });
  const context  = await browser.newContext({ storageState: state });
  return { browser, context, sessionSource: "new" };
}

async function gracefulShutdown() {
  for (const [, entry] of _cache.entries()) {
    clearTimeout(entry.idleTimer);
    if (entry.browser) await entry.browser.close().catch(() => {});
  }
  _cache.clear();
  process.exit(0);
}

module.exports = { getCachedBrowser, getAuthContext, gracefulShutdown };
