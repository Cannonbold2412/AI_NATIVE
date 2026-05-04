const fs = require("fs");
const path = require("path");

function workflowDir(name) {
  return path.join(__dirname, "..", "workflows", name);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function interpolate(value, inputs) {
  if (typeof value !== "string") return value;
  return value.replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (_, key) => String(inputs[key] ?? ""));
}

function formatStep(step, inputs) {
  const rendered = {};
  for (const [key, value] of Object.entries(step || {})) {
    rendered[key] = interpolate(value, inputs);
  }
  return rendered;
}

async function executeWorkflow(name, inputs = {}) {
  const executionPath = path.join(workflowDir(name), "execution.json");
  if (!fs.existsSync(executionPath)) {
    throw new Error(`Unknown workflow: ${name}`);
  }
  const steps = readJson(executionPath);
  if (!Array.isArray(steps)) {
    throw new Error(`execution.json for ${name} must be a JSON array.`);
  }
  console.log(`[executor] workflow=${name}`);
  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    const rendered = formatStep(step, inputs);
    console.log(`[executor] step ${index + 1}: ${JSON.stringify(rendered)}`);
  }
}

module.exports = { executeWorkflow };
