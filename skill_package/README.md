# Skill package

Bundled workflows live under `skill_package/workflows/` (one folder per slug). Where you see **`WORKFLOW_SLUG`**, substitute your workflow folder name (for example `delete_database`). The engine is copied to `skill_package/engine/`.

## Layout

| Location | Purpose |
| --- | --- |
| `skill_package/workflows/` | One subdirectory per workflow (slug matches the folder name) |
| `skill_package/engine/` | Playwright executor, recovery, logging, configuration |
| `skill_package/index.json` | Discovery index for agents to choose a workflow before loading manifests |

Inside each workflow directory:

| File | Role |
| --- | --- |
| `skill.md` | Human-readable procedure |
| `execution.json` | Step plan (`navigate`, `fill`, `click`, `assert_visible`, ...) |
| `recovery.json` | Semantic fallbacks when a locator fails |
| `inputs.json` | Required runtime keys / schema |
| `manifest.json` | Package metadata |
| `visuals/` | Optional screenshots for steps |

## Prerequisites

- Node.js 18 or newer recommended
- Install Playwright in the host application and obtain a Browser `page` (see Playwright docs for your runner)

## Run

```ts
import { executeWorkflowForPrompt } from "./skill_package/engine/execution"

const slug = "WORKFLOW_SLUG"  // rename to match workflows/* directory

await executeWorkflowForPrompt({
  page,
  indexPath: "./skill_package/index.json",
  prompt: slug,
  inputs: {
    user_email: "person@example.com",
  },
})
```

Adapt `inputs` to the schema under `workflows/WORKFLOW_SLUG/inputs.json` for each run.

Placeholders embedded in plans use doubled curly braces around the variable name. For example:

```
{{user_email}}
```

Those values are substituted from the `inputs` object before execution.

## Execution behaviour

Agents start from `index.json`, load only the selected workflow `manifest.json`, validate `inputs.json` when declared, then execute `execution.json` directly. `README.md` and `skill.md` are documentation/fallback artifacts, not the normal execution source.

Steps are executed in order from `execution.json`. Waits are not implied; visibility guards appear only where the plan specifies `assert_visible`. Use `scroll` steps to reveal lazy-loaded regions: optionally `selector` (`scrollIntoViewIfNeeded`), and/or wheel movement via `delta_y` / `delta_x`.

## Recovery

If a step fails, the engine retries once on the primary locator, then tries alternates from `recovery.json` (text variants derived at package build time). Optional LLM assist is controlled in `skill_package/engine/config.ts` (disabled by default).
