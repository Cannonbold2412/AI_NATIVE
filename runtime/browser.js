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
const LOGIN_URL_PATTERNS = [
  "login", "signin", "sign-in", "auth", "oauth", "sso",
  "session/new", "account/login", "accountchooser", "account-chooser",
];

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
        return { browser: entry.browser, context: entry.context, protectedUrl: entry.protectedUrl, cached: true };
      } catch (_) {
        _cache.delete(company);
      }
    }
  }
  const result = await getAuthContext(company, authManager, { headless });
  if (headless) {
    _cache.set(company, { browser: result.browser, context: result.context, protectedUrl: result.protectedUrl, idleTimer: null });
    _scheduleCleanup(company);
  }
  return { ...result, cached: false };
}

// ─── Session management ───────────────────────────────────────────────────────

function _isBlankUrl(url) {
  const value = String(url || "").trim().toLowerCase();
  return !value || value === "about:blank" || value === "chrome://newtab/";
}

function _rejectReasonForProtectedUrl(url) {
  const value = String(url || "").trim();
  if (_isBlankUrl(value)) {
    return "No authenticated page URL was captured. Log in, navigate to the page where workflows should start, then close Chromium.";
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch (_) {
    return "The captured protected URL is not valid.";
  }
  if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) {
    return "The captured protected URL must be an http or https page.";
  }
  const lowered = value.toLowerCase();
  if (LOGIN_URL_PATTERNS.some(marker => lowered.includes(marker))) {
    return "The final page still looks like a login/auth page. Navigate to the authenticated app page, then close Chromium.";
  }
  return "";
}

function _authMetaPath(company) {
  return path.join(SESSIONS_DIR, `${company}_auth_meta.json`);
}

function _readAuthMeta(company) {
  try {
    const metaPath = _authMetaPath(company);
    return fs.existsSync(metaPath) ? JSON.parse(fs.readFileSync(metaPath, "utf8")) : {};
  } catch (_) {
    return {};
  }
}

function _writeAuthMeta(company, patch) {
  const meta = {
    ..._readAuthMeta(company),
    ...patch,
    updated_at: new Date().toISOString(),
  };
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
  fs.writeFileSync(_authMetaPath(company), JSON.stringify(meta, null, 2), { mode: 0o600 });
  return meta;
}

function _resolveProtectedUrl(company, pack = {}) {
  const metaUrl = String((_readAuthMeta(company).protected_url || "")).trim();
  if (metaUrl) return metaUrl;
  return String((pack.protected_url || "")).trim();
}

async function _isAuthenticated(page, protectedUrl) {
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    try {
      const u = new URL(page.url());
      if (u.hostname === new URL(protectedUrl).hostname && !u.pathname.startsWith("/login"))
        return true;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 200));
  }
  return false;
}

async function _captureInteractiveAuth(company, targetUrl) {
  const loginBrowser = await chromium.launch({
    headless: false,
    args: ["--disable-blink-features=AutomationControlled"],
  });
  const loginCtx = await loginBrowser.newContext({
    acceptDownloads: true,
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    viewport: { width: 1280, height: 720 },
    locale: "en-US",
    timezoneId: "America/New_York",
  });
  let lastUrl = "";
  let lastState = null;

  const rememberPage = async (page) => {
    if (!page) return;
    try {
      if (page.isClosed()) return;
      const url = page.url();
      if (!_isBlankUrl(url)) lastUrl = url;
    } catch (_) {}
  };

  const attachPage = (page) => {
    rememberPage(page).catch(() => {});
    page.on("framenavigated", (frame) => {
      try {
        if (!frame.parentFrame()) rememberPage(page).catch(() => {});
      } catch (_) {}
    });
  };

  loginCtx.on("page", attachPage);
  const loginPage = await loginCtx.newPage();

  // Mask Playwright detection at the JS level — prevents "browser not secure" errors
  await loginPage.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => undefined });
    Object.defineProperty(navigator, "plugins", { get: () => [1, 2, 3] });
  });

  attachPage(loginPage);
  await loginPage.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });

  while (loginBrowser.isConnected()) {
    const pages = loginCtx.pages().filter(page => !page.isClosed());
    for (const page of pages) await rememberPage(page);
    // Only capture storage when user is on an authenticated page — avoids interrupting
    // Google OAuth mid-redirect by calling storageState() every 500ms.
    if (!_rejectReasonForProtectedUrl(lastUrl)) {
      try { lastState = await loginCtx.storageState(); } catch (_) {}
    }
    if (pages.length === 0) break;
    await new Promise(resolve => setTimeout(resolve, 1500));
  }

  // Final capture once loop exits (covers case where user closes browser on login page)
  if (lastState === null) {
    try { lastState = await loginCtx.storageState(); } catch (_) {}
  }

  try {
    if (loginBrowser.isConnected()) await loginBrowser.close();
  } catch (_) {}

  const rejectReason = _rejectReasonForProtectedUrl(lastUrl);
  if (rejectReason) throw new Error(rejectReason);
  if (!lastState) throw new Error(`Authentication session was not captured for ${company}. Please try again.`);
  return { state: lastState, protectedUrl: lastUrl };
}

async function getAuthContext(company, authManager, opts = {}) {
  const headless = opts.headless !== false; // default true
  let _hadEncryptedSession = false; // set true if encrypted path ran; raw session is then stale
  // Resolve pack config for this company
  const packPath = path.join(CONXA_DIR, "skill-packs", company, "pack.json");
  let pack = {};
  try { pack = JSON.parse(fs.readFileSync(packPath, "utf8")); } catch (_) {}
  const protectedUrl = _resolveProtectedUrl(company, pack);
  const targetUrl    = pack.target_url || protectedUrl;

  // Try encrypted session (requires Conxa token)
  if (authManager) {
    try {
      const token = await authManager.getToken(company);
      if (token) {
        const stored = authManager.loadDecryptedSession(company, token, SESSIONS_DIR);
        if (stored) {
          const browser  = await chromium.launch({ headless, args: ["--disable-blink-features=AutomationControlled"] });
          const context  = await browser.newContext({ storageState: stored, acceptDownloads: true });
          if (protectedUrl) {
            const page = await context.newPage();
            await page.goto(protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
            if (await _isAuthenticated(page, protectedUrl)) {
              _writeAuthMeta(company, { protected_url: protectedUrl });
              await page.close();
              return { browser, context, protectedUrl, sessionSource: "encrypted" };
            }
            await browser.close();
            // Session expired — skip raw session (encrypted takes precedence), go to interactive auth
            _hadEncryptedSession = true;
          } else {
            await browser.close();
            _hadEncryptedSession = true;
          }
        }
      }
    } catch (_) {}
  }

  // Try raw session (installer-included initial session, not yet encrypted)
  // Skip if encrypted path already ran — raw session is then stale and should not override
  const rawSessionPath = path.join(SESSIONS_DIR, `${company}_raw_state.json`);
  if (!_hadEncryptedSession && fs.existsSync(rawSessionPath)) {
    let stored;
    try { stored = JSON.parse(fs.readFileSync(rawSessionPath, "utf8")); } catch (_) {}
    if (stored) {
      const browser  = await chromium.launch({ headless });
      const context  = await browser.newContext({ storageState: stored, acceptDownloads: true });
      if (protectedUrl) {
        const page = await context.newPage();
        await page.goto(protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
        if (await _isAuthenticated(page, protectedUrl)) {
          _writeAuthMeta(company, { protected_url: protectedUrl });
          await page.close();
          return { browser, context, protectedUrl, sessionSource: "raw" };
        }
        await browser.close();
      } else {
        await browser.close();
      }
    }
  }

  // No valid session — open interactive browser for user to log in
  if (!targetUrl) throw new Error(`No target_url configured for company ${company}. Cannot authenticate.`);

  const { state, protectedUrl: capturedProtectedUrl } = await _captureInteractiveAuth(company, targetUrl);
  _writeAuthMeta(company, { protected_url: capturedProtectedUrl });

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
  const context  = await browser.newContext({ storageState: state, acceptDownloads: true });
  const page = await context.newPage();
  await page.goto(capturedProtectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  if (!await _isAuthenticated(page, capturedProtectedUrl)) {
    await browser.close();
    throw new Error("Authenticated navigation failed after login — unexpected error.");
  }
  await page.close();
  return { browser, context, protectedUrl: capturedProtectedUrl, sessionSource: "new" };
}

async function gracefulShutdown() {
  for (const [, entry] of _cache.entries()) {
    clearTimeout(entry.idleTimer);
    if (entry.browser) await entry.browser.close().catch(() => {});
  }
  _cache.clear();
  process.exit(0);
}

module.exports = {
  getCachedBrowser,
  getAuthContext,
  gracefulShutdown,
  _authMetaPath,
  _readAuthMeta,
  _writeAuthMeta,
  _resolveProtectedUrl,
  _rejectReasonForProtectedUrl,
};
