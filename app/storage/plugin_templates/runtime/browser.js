"use strict";
const { chromium } = require("playwright");
const fs   = require("fs");
const path = require("path");
const { getPluginConfig, getPluginDir, getAuthJson, getAuthMetaJson } = require("./config");

const LOGIN_URL_PATTERNS = [
  "login", "signin", "sign-in", "auth", "oauth", "sso",
  "session/new", "account/login", "accountchooser", "account-chooser",
];

// ─── Browser cache (per-slug, 5-min idle timeout) ────────────────────────────

const _cache = new Map(); // slug → { browser, context, idleTimer }
const BROWSER_IDLE_MS = 5 * 60 * 1000;

function _scheduleCleanup(slug) {
  const entry = _cache.get(slug);
  if (!entry) return;
  clearTimeout(entry.idleTimer);
  entry.idleTimer = setTimeout(async () => {
    console.error(`[browser-cache] Idle timeout for ${slug} — closing browser`);
    const b = entry.browser;
    _cache.delete(slug);
    if (b) await b.close().catch(() => {});
  }, BROWSER_IDLE_MS);
}

async function getCachedBrowser(slug) {
  const entry = _cache.get(slug);
  if (entry && entry.browser && entry.context) {
    try {
      entry.context.pages(); // throws if context is closed
      _scheduleCleanup(slug);
      console.error(`[browser-cache] Reusing cached browser for ${slug}`);
      return { browser: entry.browser, context: entry.context, protectedUrl: entry.protectedUrl, cached: true };
    } catch (_) {
      _cache.delete(slug);
    }
  }
  const { browser, context, protectedUrl } = await getAuthContext(slug, false);
  _cache.set(slug, { browser, context, protectedUrl, idleTimer: null });
  _scheduleCleanup(slug);
  console.error(`[browser-cache] Launched new browser for ${slug}`);
  return { browser, context, protectedUrl, cached: false };
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

function _readAuthMeta(slug) {
  try {
    const metaPath = getAuthMetaJson(slug);
    return fs.existsSync(metaPath) ? JSON.parse(fs.readFileSync(metaPath, "utf8")) : {};
  } catch (_) {
    return {};
  }
}

function _writeAuthMeta(slug, patch) {
  const meta = {
    ..._readAuthMeta(slug),
    ...patch,
    updated_at: new Date().toISOString(),
  };
  const metaPath = getAuthMetaJson(slug);
  fs.mkdirSync(path.dirname(metaPath), { recursive: true });
  fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2), { mode: 0o600 });
  return meta;
}

function _resolveProtectedUrl(slug, cfg = {}) {
  const metaUrl = String((_readAuthMeta(slug).protected_url || "")).trim();
  if (metaUrl) return metaUrl;
  return String((cfg.protected_url || "")).trim();
}

function isAuthenticated(page, protectedUrl) {
  try {
    const u = new URL(page.url());
    return u.hostname === new URL(protectedUrl).hostname && !u.pathname.startsWith("/login");
  } catch (_) { return false; }
}

async function _captureInteractiveAuth(slug, targetUrl) {
  const loginBrowser = await chromium.launch({ headless: false });
  const loginCtx     = await loginBrowser.newContext();
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
  attachPage(loginPage);
  await loginPage.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });

  while (loginBrowser.isConnected()) {
    const pages = loginCtx.pages().filter(page => !page.isClosed());
    for (const page of pages) await rememberPage(page);
    try { lastState = await loginCtx.storageState(); } catch (_) {}
    if (pages.length === 0) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  try {
    if (loginBrowser.isConnected()) await loginBrowser.close();
  } catch (_) {}

  const rejectReason = _rejectReasonForProtectedUrl(lastUrl);
  if (rejectReason) throw new Error(rejectReason);
  if (!lastState) throw new Error(`Authentication session was not captured for ${slug}. Please try again.`);
  return { state: lastState, protectedUrl: lastUrl };
}

async function getAuthContext(slug, headless) {
  const cfg         = getPluginConfig(slug);
  const protectedUrl = _resolveProtectedUrl(slug, cfg);
  const targetUrl    = cfg.target_url;
  const authJson     = getAuthJson(slug);

  if (fs.existsSync(authJson)) {
    let stored;
    try { stored = JSON.parse(fs.readFileSync(authJson, "utf8")); } catch (_) {}
    if (stored) {
      const browser  = await chromium.launch({ headless: headless !== false });
      const context  = await browser.newContext({ storageState: stored });
      if (protectedUrl) {
        const page = await context.newPage();
        await page.goto(protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
        await page.waitForTimeout(1500);
        if (isAuthenticated(page, protectedUrl)) {
          _writeAuthMeta(slug, { protected_url: protectedUrl });
          await page.close();
          console.error(`[auth:${slug}] Session restored from auth.json`);
          return { browser, context, protectedUrl };
        }
      }
      await browser.close();
      console.error(`[auth:${slug}] Stored session expired — starting manual login`);
    }
  } else {
    console.error(`[auth:${slug}] No auth.json — starting manual login`);
  }

  console.error(`[auth:${slug}] Opening login browser — waiting for user to authenticate...`);
  if (!targetUrl) throw new Error(`No target_url configured for plugin ${slug}. Cannot authenticate.`);

  const { state, protectedUrl: capturedProtectedUrl } = await _captureInteractiveAuth(slug, targetUrl);
  fs.mkdirSync(path.dirname(authJson), { recursive: true });
  fs.writeFileSync(authJson, JSON.stringify(state, null, 2));
  _writeAuthMeta(slug, { protected_url: capturedProtectedUrl });
  console.error(`[auth:${slug}] Session saved to auth.json — closing login browser`);

  console.error(`[auth:${slug}] Relaunching authenticated browser...`);
  const browser  = await chromium.launch({ headless: headless !== false });
  const context  = await browser.newContext({ storageState: state });
  const page     = await context.newPage();
  await page.goto(capturedProtectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  if (!isAuthenticated(page, capturedProtectedUrl)) {
    await browser.close();
    throw new Error("Authenticated navigation failed after login — unexpected error.");
  }
  await page.close();
  console.error(`[auth:${slug}] Authenticated context ready`);
  return { browser, context, protectedUrl: capturedProtectedUrl };
}

// ─── Graceful shutdown ────────────────────────────────────────────────────────

async function gracefulShutdown() {
  for (const [slug, entry] of _cache.entries()) {
    clearTimeout(entry.idleTimer);
    if (entry.browser) {
      console.error(`[browser-cache] SIGINT/SIGTERM — closing browser for ${slug}`);
      await entry.browser.close().catch(() => {});
    }
  }
  _cache.clear();
  process.exit(0);
}

module.exports = {
  getCachedBrowser,
  isAuthenticated,
  getAuthContext,
  gracefulShutdown,
  _readAuthMeta,
  _writeAuthMeta,
  _resolveProtectedUrl,
  _rejectReasonForProtectedUrl,
};
