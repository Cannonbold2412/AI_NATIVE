const childProcess = require("child_process");
const path = require("path");

function extractFirstJsonArray(raw) {
  const text = String(raw || "");
  let start = -1;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (start === -1) {
      if (char === "[") {
        start = index;
        depth = 1;
      }
      continue;
    }
    if (escape) {
      escape = false;
      continue;
    }
    if (char === "\\") {
      escape = true;
      continue;
    }
    if (char === '"') {
      inString = !inString;
      continue;
    }
    if (inString) {
      continue;
    }
    if (char === "[") {
      depth += 1;
      continue;
    }
    if (char === "]") {
      depth -= 1;
      if (depth === 0) {
        const candidate = text.slice(start, index + 1);
        return JSON.parse(candidate);
      }
    }
  }
  throw new Error("Claude output did not contain a valid JSON array.");
}

function main() {
  const input = process.argv.slice(2).join(" ").trim();
  if (!input) {
    throw new Error("Usage: render <request>");
  }

  const claudeResult = childProcess.spawnSync("claude", [input], {
    encoding: "utf8",
    shell: false,
  });
  if (claudeResult.error) {
    throw claudeResult.error;
  }
  if (claudeResult.status !== 0) {
    process.stderr.write(claudeResult.stderr || "");
    throw new Error(`claude exited with code ${claudeResult.status}`);
  }

  const plan = extractFirstJsonArray(claudeResult.stdout);
  const bridgePath = path.join(__dirname, "bridge", "run.js");
  const bridgeResult = childProcess.spawnSync(process.execPath, [bridgePath, JSON.stringify(plan)], {
    encoding: "utf8",
    stdio: "inherit",
    shell: false,
  });
  if (bridgeResult.error) {
    throw bridgeResult.error;
  }
  if (bridgeResult.status !== 0) {
    throw new Error(`bridge/run.js exited with code ${bridgeResult.status}`);
  }
}

main();
