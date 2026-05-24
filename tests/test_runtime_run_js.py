from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_runtime_execute_step_uses_frame_locator_for_iframe_steps() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    repo = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(
        """
        const assert = require("assert");
        const { executeStep } = require("./app/storage/plugin_templates/runtime/run.js");

        const calls = [];
        class FakeLocator {
          constructor(scope, selector) {
            this.scope = scope;
            this.selector = selector;
          }
          first() { return this; }
          last() { return this; }
          async waitFor() { calls.push(["waitFor", this.scope, this.selector]); }
          async fill(value) { calls.push(["fill", this.scope, this.selector, value]); }
          async click() { calls.push(["click", this.scope, this.selector]); }
        }
        class FakeRoot {
          constructor(scope) { this.scope = scope; }
          locator(selector) {
            calls.push(["locator", this.scope, selector]);
            return new FakeLocator(this.scope, selector);
          }
          frameLocator(selector) {
            calls.push(["frameLocator", this.scope, selector]);
            return new FakeRoot(`${this.scope} >> ${selector}`);
          }
        }
        const page = new FakeRoot("page");
        page.keyboard = { press: async () => {} };
        page.waitForTimeout = async () => {};
        page.evaluate = async () => {};
        page.screenshot = async () => Buffer.from("");

        (async () => {
          const frame = {
            chain: [{
              selector: 'iframe[id="object-builder-ui"]',
              fallback_selectors: ['iframe[data-test-id="object-builder-ui-iframe"]'],
            }],
          };
          await executeStep(page, { type: "fill", selector: 'input[name="firstname"]', value: "Ada", frame }, {});
          await executeStep(page, { type: "click", selector: 'text="Create"', frame }, {});
          await executeStep(page, { type: "click", selector: 'text="Main"' }, {});

          assert.deepStrictEqual(calls[0], ["frameLocator", "page", 'iframe[id="object-builder-ui"]']);
          assert(calls.some(row => row[0] === "fill" && row[1].includes('iframe[id="object-builder-ui"]') && row[2] === 'input[name="firstname"]'));
          assert(calls.some(row => row[0] === "click" && row[1].includes('iframe[id="object-builder-ui"]') && row[2] === 'text="Create"'));
          assert(calls.some(row => row[0] === "click" && row[1] === "page" && row[2] === 'text="Main"'));
        })().catch(err => {
          console.error(err);
          process.exit(1);
        });
        """
    )

    result = subprocess.run(
        [node, "-e", script],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
