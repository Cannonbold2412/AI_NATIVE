"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const { loadInstallId } = require("../install_identity");
const { runPlan } = require("../run");

let passed = 0;
let failed = 0;

async function test(label, fn) {
  try {
    await fn();
    console.log(`  ✓ ${label}`);
    passed++;
  } catch (e) {
    console.error(`  ✗ ${label}`);
    console.error(`    ${e.stack || e.message}`);
    failed++;
  }
}

function makeClickPage() {
  return {
    locator(selector) {
      return {
        first() {
          return {
            async click() {
              if (selector === "#primary") throw new Error("primary missing");
            },
            async waitFor() {},
          };
        },
        last() {
          return this.first();
        },
      };
    },
    async waitForTimeout() {},
  };
}

(async () => {
  console.log("dashboard telemetry:");

  await test("install id is persisted and reused", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "conxa-install-id-"));
    try {
      const first = loadInstallId(dir);
      const second = loadInstallId(dir);
      assert.equal(first, second);
      assert.match(first, /^[A-Za-z0-9_-]{12,96}$/);
      assert.equal(fs.readFileSync(path.join(dir, "identity", "install_id"), "utf8").trim(), first);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  await test("fallback selector recovery emits selector telemetry", async () => {
    const events = [];
    const result = await runPlan(
      makeClickPage(),
      [{
        type: "click",
        selector: "#primary",
        target: {
          primary_selector: "#primary",
          fallback_selectors: ["#fallback"],
        },
      }],
      {},
      0,
      "workflow-a",
      { tracker: { emit: (event, fields) => events.push({ event, ...fields }) }, observerMs: 0 },
    );

    assert.equal(result.recoveredSteps, 1);
    assert.deepEqual(events.filter((event) => event.event === "rec_ok"), [
      { event: "rec_ok", si: 0, sc: "selector" },
    ]);
  });

  const total = passed + failed;
  console.log(`\n${passed}/${total} passed`);
  process.exit(failed > 0 ? 1 : 0);
})();
