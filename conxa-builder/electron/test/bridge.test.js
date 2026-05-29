"use strict";
/** Plain-node tests for the JSON-RPC bridge correlation logic. */

const assert = require("assert");
const { Bridge } = require("../bridge");

function makeBridge() {
  const written = [];
  const events = [];
  let counter = 0;
  const bridge = new Bridge(
    (line) => written.push(line),
    (ev) => events.push(ev),
    () => `id-${++counter}`
  );
  return { bridge, written, events };
}

(async function run() {
  // 1. call() writes a framed request and resolves on the matching result.
  {
    const { bridge, written } = makeBridge();
    const p = bridge.call("ping", { x: 1 });
    assert.strictEqual(written.length, 1);
    const sent = JSON.parse(written[0]);
    assert.strictEqual(sent.type, "ping");
    assert.strictEqual(sent.id, "id-1");
    bridge.handleLine(JSON.stringify({ id: "id-1", type: "result", result: { ok: true } }));
    assert.deepStrictEqual(await p, { ok: true });
    assert.strictEqual(bridge.pendingCount, 0);
  }

  // 2. errors reject with code + message.
  {
    const { bridge } = makeBridge();
    const p = bridge.call("compile", {});
    bridge.handleLine(
      JSON.stringify({ id: "id-1", type: "error", code: "no_events", message: "nope" })
    );
    await p.then(
      () => assert.fail("should reject"),
      (err) => {
        assert.strictEqual(err.code, "no_events");
        assert.strictEqual(err.message, "nope");
      }
    );
  }

  // 3. events fan out and do not touch pending calls.
  {
    const { bridge, events } = makeBridge();
    const p = bridge.call("compile", {});
    bridge.handleLine(JSON.stringify({ type: "event", id: "id-1", phase: "pipeline_start" }));
    assert.strictEqual(events.length, 1);
    assert.strictEqual(events[0].phase, "pipeline_start");
    assert.strictEqual(bridge.pendingCount, 1); // still waiting
    bridge.handleLine(JSON.stringify({ id: "id-1", type: "result", result: 42 }));
    assert.strictEqual(await p, 42);
  }

  // 4. unknown/old ids and malformed lines are ignored safely.
  {
    const { bridge } = makeBridge();
    bridge.handleLine("not json");
    bridge.handleLine(JSON.stringify({ id: "ghost", type: "result", result: 1 }));
    bridge.handleLine("");
    assert.strictEqual(bridge.pendingCount, 0);
  }

  // 5. rejectAll clears in-flight calls (backend crash).
  {
    const { bridge } = makeBridge();
    const p = bridge.call("build_plugin", {});
    bridge.rejectAll("backend exited (code 1)");
    await p.then(
      () => assert.fail("should reject"),
      (err) => assert.match(err.message, /backend exited/)
    );
    assert.strictEqual(bridge.pendingCount, 0);
  }

  console.log("bridge.test.js: all assertions passed");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
