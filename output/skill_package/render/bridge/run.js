const { executeWorkflow } = require("../engine/executor");

function validateEntry(entry, index) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
    throw new Error(`Plan entry ${index + 1} must be an object.`);
  }
  if (!entry.workflow || typeof entry.workflow !== "string") {
    throw new Error(`Plan entry ${index + 1} requires a workflow string.`);
  }
  if (entry.inputs !== undefined && (typeof entry.inputs !== "object" || entry.inputs === null || Array.isArray(entry.inputs))) {
    throw new Error(`Plan entry ${index + 1} inputs must be an object when provided.`);
  }
}

async function main() {
  const raw = process.argv[2];
  let plan;
  try {
    plan = JSON.parse(raw);
  } catch (error) {
    throw new Error("Invalid JSON plan.");
  }
  if (!Array.isArray(plan)) {
    throw new Error("Plan JSON must be an array.");
  }
  for (let index = 0; index < plan.length; index += 1) {
    const entry = plan[index];
    validateEntry(entry, index);
    await executeWorkflow(entry.workflow, entry.inputs || {});
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
