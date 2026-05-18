"use strict";
const { chromium } = require("playwright");
const fs   = require("fs");
const path = require("path");
const { getPluginConfig, getPluginDir, getAuthJson } = require("./config");

// ─── Browser cache (per-slug, 5-min idle timeout) ────────────────────────────

const _cache    = new Map();  // slug → { browser, context, idleTimer }
const _holds    = new Map();  // slug → hold count
const _inflight = new Map();  // slug → Promise<{browser,context}> (dedup concurrent launches)
const BROWSER_IDLE_MS = 5 * 60 * 1000;
const BROWSER_MAX     = 5;

function _scheduleCleanup(slug) {
  const entry = _cache.get(slug);
  if (!entry) return;
  clearTimeout(entry.idleTimer);
  entry.idleTimer = setTimeout(async () => {
    if ((_holds.get(slug) || 0) > 0) {
      _scheduleCleanup(slug); // still held — defer
      return;
    }
    console.error(`[browser-cache] Idle timeout for ${slug} — closing browser`);
    const b = entry.browser;
    _cache.delete(slug);
    if (b) await b.close().catch(() => {});
  }, BROWSER_IDLE_MS);
  entry.idleTimer.unref?.();
}

function holdBrowser(slug) {
  _holds.set(slug, (_holds.get(slug) || 0) + 1);
}

function releaseBrowserHold(slug) {
  const n = (_holds.get(slug) || 0) - 1;
  if (n <= 0) _holds.delete(slug); else _holds.set(slug, n);
}

async function getCachedBrowser(slug) {
  const entry = _cache.get(slug);
  if (entry && entry.browser && entry.context) {
    try {
      entry.context.pages(); // throws if context is closed
      _scheduleCleanup(slug);
      console.error(`[browser-cache] Reusing cached browser for ${slug}`);
      return { browser: entry.browser, context: entry.context, cached: true };
    } catch (_) {
      _cache.delete(slug);
    }
  }
  // Dedup concurrent launch requests for the same slug
  if (_inflight.has(slug)) {
    console.error(`[browser-cache] Waiting for in-flight browser launch for ${slug}`);
    return _inflight.get(slug);
  }
  const launch = (async () => {
    try {
      const { browser, context } = await getAuthContext(slug, false);
      // Evict LRU entry if at capacity (skip held browsers)
      if (_cache.size >= BROWSER_MAX) {
        for (const [evictSlug, evictEntry] of _cache.entries()) {
          if ((_holds.get(evictSlug) || 0) > 0) continue;
          clearTimeout(evictEntry.idleTimer);
          _cache.delete(evictSlug);
          if (evictEntry.browser) evictEntry.browser.close().catch(() => {});
          console.error(`[browser-cache] Evicted ${evictSlug} (cache limit ${BROWSER_MAX})`);
          break;
        }
      }
      _cache.set(slug, { browser, context, idleTimer: null });
      _scheduleCleanup(slug);
      console.error(`[browser-cache] Launched new browser for ${slug}`);
      return { browser, context, cached: false };
    } finally {
      _inflight.delete(slug);
    }
  })();
  _inflight.set(slug, launch);
  return launch;
}

// ─── Session management ───────────────────────────────────────────────────────

function isAuthenticated(page, protectedUrl) {
  try {
    const u = new URL(page.url());
    return u.hostname === new URL(protectedUrl).hostname && !u.pathname.startsWith("/login");
  } catch (_) { return false; }
}

async function getAuthContext(slug, headless) {
  const cfg         = getPluginConfig(slug);
  const protectedUrl = cfg.protected_url;
  const targetUrl    = cfg.target_url;
  const authJson     = getAuthJson(slug);

  if (fs.existsSync(authJson)) {
    let stored;
    try { stored = JSON.parse(fs.readFileSync(authJson, "utf8")); } catch (_) {}
    if (stored) {
      const browser  = await chromium.launch({ headless: headless !== false });
      const context  = await browser.newContext({ storageState: stored });
      const page     = await context.newPage();
      await page.goto(protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(1500);
      if (isAuthenticated(page, protectedUrl)) {
        await page.close();
        console.error(`[auth:${slug}] Session restored from auth.json`);
        return { browser, context };
      }
      await browser.close();
      console.error(`[auth:${slug}] Stored session expired — starting manual login`);
    }
  } else {
    console.error(`[auth:${slug}] No auth.json — starting manual login`);
  }

  const isCI = process.env.CI || process.env.DISPLAY === "" || (!process.env.DISPLAY && process.platform === "linux");
  if (isCI) throw new Error(`[auth:${slug}] Cannot open login browser in headless/CI environment. Pre-generate auth.json and place it at ${authJson}`);

  console.error(`[auth:${slug}] Opening login browser — waiting for user to authenticate...`);
  const loginBrowser = await chromium.launch({ headless: false });
  const loginCtx     = await loginBrowser.newContext();
  const loginPage    = await loginCtx.newPage();
  await loginPage.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
  try {
    await loginPage.waitForURL(
      url => url.href.startsWith(protectedUrl) && !url.href.includes("/login"),
      { timeout: 300000 }
    );
  } catch (_) {
    await loginBrowser.close();
    throw new Error("Authentication timed out after 5 minutes. Please try again.");
  }

  const state = await loginCtx.storageState();
  fs.mkdirSync(path.dirname(authJson), { recursive: true, mode: 0o700 });
  fs.writeFileSync(authJson, JSON.stringify(state, null, 2), { encoding: "utf8", mode: 0o600 });
  console.error(`[auth:${slug}] Session saved to auth.json — closing login browser`);
  await loginBrowser.close();

  console.error(`[auth:${slug}] Relaunching authenticated browser...`);
  const browser  = await chromium.launch({ headless: headless !== false });
  const context  = await browser.newContext({ storageState: state });
  const page     = await context.newPage();
  await page.goto(protectedUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  if (!isAuthenticated(page, protectedUrl)) {
    await browser.close();
    throw new Error("Authenticated navigation failed after login — unexpected error.");
  }
  await page.close();
  console.error(`[auth:${slug}] Authenticated context ready`);
  return { browser, context };
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

module.exports = { getCachedBrowser, holdBrowser, releaseBrowserHold, isAuthenticated, getAuthContext, gracefulShutdown };
