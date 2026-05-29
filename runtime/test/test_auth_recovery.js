"use strict";
// Pure-node tests for Phase 5: auth-failure detection + refreshSession stub.
// Run with: node runtime/test/test_auth_recovery.js

const assert = require("assert");
const { isAuthFailure } = require("../run");

let passed = 0;
let failed = 0;

async function test(label, fn) {
  try {
    await fn();
    console.log(`  ✓ ${label}`);
    passed++;
  } catch (e) {
    console.error(`  ✗ ${label}`);
    console.error(`    ${e.message}`);
    failed++;
  }
}

function makePage(url, title = "My App") {
  return {
    url: () => url,
    title: async () => title,
  };
}

(async () => {
  console.log("isAuthFailure detection:");

  await test("login path → auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://app.example.com/login")), true);
  });

  await test("signin path → auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://app.example.com/signin?redirect=/dashboard")), true);
  });

  await test("session-expired path → auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://app.example.com/session-expired")), true);
  });

  await test("auth path → auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://app.example.com/auth/challenge")), true);
  });

  await test("normal dashboard path → not auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://dashboard.render.com/services")), false);
  });

  await test("title 'Sign in to Render' → auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://render.com/other", "Sign in to Render")), true);
  });

  await test("title 'Session Expired' → auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://app.example.com/", "Session Expired")), true);
  });

  await test("normal page title → not auth failure", async () => {
    assert.equal(await isAuthFailure(makePage("https://app.example.com/dashboard", "Dashboard")), false);
  });

  await test("login in subpath of legitimate URL → not auth failure", async () => {
    // /app/login-history should NOT match — regex requires login at end, /, or ?
    assert.equal(await isAuthFailure(makePage("https://app.example.com/settings/login-history")), false);
  });

  console.log("\nrefreshSession headless mode:");
  const { refreshSession } = require("../auth_manager");

  await test("headless → returns ok:false session_expired without hanging", async () => {
    const origDisplay  = process.env.DISPLAY;
    const origWayland  = process.env.WAYLAND_DISPLAY;
    const origPlatform = process.platform;
    delete process.env.DISPLAY;
    delete process.env.WAYLAND_DISPLAY;
    Object.defineProperty(process, "platform", { value: "linux", configurable: true });
    const result = await refreshSession("acme", "https://example.com/login", null, "/tmp");
    Object.defineProperty(process, "platform", { value: origPlatform, configurable: true });
    if (origDisplay)  process.env.DISPLAY = origDisplay;
    if (origWayland)  process.env.WAYLAND_DISPLAY = origWayland;
    assert.equal(result.ok, false);
    assert.equal(result.session_expired, true);
    assert.ok(result.login_url);
    assert.ok(result.message);
  });

  await test("attempt limit exceeded → ok:false without trying browser", async () => {
    // Call 4 times (limit is 3) to trigger the attempt guard
    const origPlatform = process.platform;
    Object.defineProperty(process, "platform", { value: "linux", configurable: true });
    delete process.env.DISPLAY;
    const company = `test-limit-${Date.now()}`;
    for (let i = 0; i < 4; i++) {
      await refreshSession(company, "https://example.com/login", null, "/tmp");
    }
    // 4th call: attempt counter > 3, should hit the limit message
    const result = await refreshSession(company, "https://example.com/login", null, "/tmp");
    Object.defineProperty(process, "platform", { value: origPlatform, configurable: true });
    assert.equal(result.ok, false);
    assert.match(result.message, /3 times|limit|escalat/i);
  });

  const total = passed + failed;
  console.log(`\n${passed}/${total} passed`);
  process.exit(failed > 0 ? 1 : 0);
})();
