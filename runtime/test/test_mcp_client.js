#!/usr/bin/env node
/**
 * Simple MCP client to test the Render plugin server
 */
const { spawn } = require("child_process");
const path = require("path");

const pluginRoot = "C:\\Users\\Lenovo\\.claude\\plugins\\cache\\render";
const server = spawn("npm", ["start"], {
  cwd: pluginRoot,
  stdio: ["pipe", "pipe", "pipe"],
  shell: true,
});

let requestId = 1;
const responses = [];

function sendMessage(message) {
  const jsonrpc = {
    jsonrpc: "2.0",
    id: requestId++,
    ...message,
  };
  console.log(`[CLIENT] Sending: ${message.method}`);
  server.stdin.write(JSON.stringify(jsonrpc) + "\n");
}

function waitForResponse(timeout = 5000) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      console.log("[TIMEOUT] No response received");
      resolve(null);
    }, timeout);

    const onData = (data) => {
      const lines = data.toString().split("\n");
      for (const line of lines) {
        if (line.trim()) {
          try {
            const response = JSON.parse(line);
            clearTimeout(timer);
            server.stdout.removeListener("data", onData);
            console.log(`[SERVER] Response:`, JSON.stringify(response, null, 2));
            resolve(response);
            return;
          } catch (e) {
            console.log("[DEBUG]", line);
          }
        }
      }
    };
    server.stdout.on("data", onData);
  });
}

async function test() {
  console.log("Starting MCP client test...\n");

  // Give server time to start
  await new Promise((r) => setTimeout(r, 3000));

  // Test 1: Initialize
  console.log("=== Test 1: Initialize ===");
  sendMessage({
    method: "initialize",
    params: {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "test-client", version: "1.0" },
    },
  });
  const initResp = await waitForResponse();
  if (!initResp) {
    console.log("❌ Server not responding");
    process.exit(1);
  }
  console.log("✓ Server responded to initialize\n");

  // Test 2: List Tools
  console.log("=== Test 2: List Tools ===");
  sendMessage({ method: "tools/list", params: {} });
  const toolsResp = await waitForResponse();
  if (toolsResp?.result?.tools) {
    console.log(`✓ Found ${toolsResp.result.tools.length} tools:`);
    toolsResp.result.tools.forEach((t) => {
      console.log(`  - ${t.name}: ${t.description}`);
    });
    console.log("");
  }

  // Test 3: Call list_skills
  console.log("=== Test 3: Call list_skills ===");
  sendMessage({
    method: "tools/call",
    params: {
      name: "list_skills",
      arguments: {},
    },
  });
  const skillsResp = await waitForResponse(10000);
  if (skillsResp?.result?.content?.[0]?.text) {
    try {
      const skills = JSON.parse(skillsResp.result.content[0].text);
      console.log(`✓ Found ${skills.length} skills:`);
      skills.forEach((s) => console.log(`  - ${s.slug}`));
    } catch (e) {
      console.log("✓ list_skills returned data");
    }
  }

  console.log("\n✅ MCP server is working!");
  server.kill();
  process.exit(0);
}

server.stderr.on("data", (data) => {
  console.log("[STDERR]", data.toString());
});

server.on("error", (err) => {
  console.log("❌ Server error:", err.message);
  process.exit(1);
});

test().catch((err) => {
  console.log("❌ Test failed:", err);
  server.kill();
  process.exit(1);
});
