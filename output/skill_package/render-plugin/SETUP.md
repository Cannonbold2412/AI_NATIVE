# Render Plugin — Setup Guide

## What This Plugin Does

This is an automation plugin that runs real workflows on services you use. It uses browser automation (Playwright) to execute recorded workflows.

## Prerequisites (one-time setup)

1. **Node.js** (v18+) installed — https://nodejs.org
2. **Claude Code** CLI installed — `npm install -g @anthropic-ai/claude-code`
3. Unzip the plugin folder anywhere (e.g., `~/plugins/render`)

## Installation

```bash
cd render
npm install          # installs Playwright
npx playwright install chromium   # downloads Chromium browser
```

## Running with Claude (Recommended)

```bash
cd render
claude   # opens Claude Code in this folder
```

Then tell Claude what you want to do. Examples:
- *"Execute task X"*
- *"Run the workflow with these inputs"*

Claude will:
1. Read the plugin files to understand available skills
2. Ask for any missing inputs
3. Generate a `_plan.json` file
4. Run `node execution/executor.js --plan _plan.json`
5. Report results from `EXECUTION_PLAN_RESULT.json`

## Running Manually (Without Claude)

### Single skill
```bash
node execution/executor.js --skill skill_name --inputs inputs.json
```

### Multiple skills (plan mode)
```bash
node execution/executor.js --plan plan.json
```

### Debug mode (see browser)
```bash
node execution/executor.js --plan plan.json --headless 0
```

## File Format Examples

### inputs.json
```json
{
  "user_email": "you@example.com",
  "user_password": "password",
  "resource_name": "my-resource"
}
```

### plan.json
```json
[
  {
    "skill": "login",
    "inputs": { "user_email": "you@example.com", "user_password": "pass" }
  },
  {
    "skill": "delete_resource",
    "inputs": { "user_email": "you@example.com", "user_password": "pass", "resource_name": "my-resource" }
  }
]
```

## Results

After execution, check:
- `EXECUTION_RESULT.json` — single skill result
- `EXECUTION_PLAN_RESULT.json` — multiple skill result

## Troubleshooting

**Browser won't open**: Make sure Playwright Chromium is installed: `npx playwright install chromium`

**Skill fails with 'element not found'**: The UI may have changed. Recovery layers will attempt to fix it. If it still fails, the skill may need re-recording.

**Credentials errors**: Verify your inputs.json has correct values for all required fields.
