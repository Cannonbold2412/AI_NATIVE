# How skill package generation works

This document explains the current `skill-pack` pipeline in enough detail for another AI agent to trace the code, predict the outputs, and modify the system safely.

The implementation is centered on three layers:

| Layer | Location | Job |
| --- | --- | --- |
| API | `app/api/skill_pack_routes.py` | Accept build/export/list/read/delete requests |
| Builder | `app/services/skill_pack_builder.py` | Parse raw JSON, call the structuring LLM, validate, compile, and assemble package artifacts |
| Storage | `app/storage/skill_packages.py` | Maintain `output/skill_package/<bundle_slug>/` (README, index, engine, workflows), migrate legacy flat layout once into `legacy/` |

There is also an optional prose-generation helper in `app/llm/skill_pack_llm.py`, but the main build path does not use it today.

## Mental model

The system is intentionally split into:

1. `Raw recording JSON`
2. `LLM structuring`
3. `Deterministic validation and compilation`
4. `Artifact generation`
5. `Persistence / export`

Only the LLM is allowed to interpret messy event logs. Everything after that is deterministic and restrictive.

That design matters:

- The LLM can infer intent, merge noise, and generalize literal values into placeholders.
- The compiler does not trust arbitrary automation emitted by the LLM.
- Runtime execution is limited to a small allowed step vocabulary.

## End-to-end flow

```text
Raw JSON text
  -> _parse_json_text
  -> _extract_steps
  -> structure_steps_with_llm
      -> _call_structuring_llm
      -> _validate_structured_output
  -> _package_title + _slugify_name
  -> parse_inputs
  -> compile_execution
  -> _validate_execution_plan
  -> generate_recovery
  -> build_manifest
  -> generate_skill_markdown
  -> _collect_visual_assets
  -> write_skill_package_files
  -> HTTP response / ZIP export
```

## What gets created

A **named bundle** (`bundle_slug`) is stored under:

```text
output/skill_package/<bundle_slug>/
  README.md
  index.json
  engine/
    orchestrator.ts (when present in repo engine/)
    execution.ts
    recovery.ts
    logging.ts
    config.ts
  workflows/
    <workflow_slug>/
      skill.md
      execution.json
      recovery.json
      inputs.json
      manifest.json
      visuals/
        Image_0.png|jpg|jpeg|gif|webp
        Image_<n>.png|jpg|jpeg|gif|webp
```

The **`bundle_slug`** is the folder you choose when building/appending (`POST /skill-pack/build` sends `bundle_name`, default **`default`**). **`workflow_slug`** is the slugified workflow name inside that bundle.

## Primary HTTP API

Routes live in `app/api/skill_pack_routes.py`.

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/skill-pack/build` | Build a workflow into `bundle_name` (default `default`): `{ "json_text", optional "package_name", "bundle_name" }` |
| `POST` | `/skill-pack/bundles/{bundle}/build` | Same as build, bundle taken from path |
| `POST` | `/skill-pack/bundles/{bundle}/append` | Append another workflow JSON into that bundle |
| `GET` | `/skill-pack/packages` | List bundles (each has `workflows[]` metadata) |
| `GET` | `/skill-pack/bundles/{bundle}` | Read flattened file map for the whole bundle |
| `GET` | `/skill-pack/bundles/{bundle}/workflows/{workflow}` | Read bundle root + one workflow (legacy-style key layout) |
| `DELETE` | `/skill-pack/bundles/{bundle}` | Delete an entire bundle directory |
| `PATCH` | `/skill-pack/bundles/{bundle}` | Rename a bundle |
| `DELETE` | `/skill-pack/bundles/{bundle}/workflows/{workflow}` | Remove one workflow folder |
| `PATCH` | `/skill-pack/bundles/{bundle}/workflows/{workflow}` | Rename one workflow folder |
| `POST` | `/skill-pack/export` | Build a ZIP from provided file bodies (`bundle_name` optional, default `default`) |
| `GET` | `/skill-pack/bundles/{bundle}/download` | ZIP entire bundle from disk |

The frontend wrapper is `frontend/src/api/workflowApi.ts`.

## Step 1: Parse the incoming JSON

`build_skill_package(json_text)` starts with `_parse_json_text`.

Behavior:

- Parses the raw string with `json.loads`.
- Rejects invalid JSON with `ValueError("Invalid JSON: ...")`.
- Requires the root value to be either an object or an array.
- Rejects scalar roots such as strings, numbers, booleans, or `null`.

At this stage there is no workflow-specific interpretation yet.

## Step 2: Extract candidate step objects

`_extract_steps(payload)` tries to find recording-like step dictionaries without assigning meaning to them.

Accepted shapes:

- If the JSON root is a list, each object item in that list is treated as a raw step.
- If the root is an object, it first checks these direct step-array keys:
  - `steps`
  - `actions`
  - `events`
  - `recorded_events`
  - `interactions`
  - `workflow_steps`
- If those are absent, it searches nested containers under:
  - `skills`
  - `workflows`
  - `flows`
  - `scenarios`
  - `recordings`
- If still nothing is found, it recurses through object values.

Important constraints:

- Only dictionaries survive extraction.
- Arrays of primitives are ignored.
- The function is intentionally permissive because the input recordings can vary a lot.

If no raw step objects are found, the build fails with `No workflow steps detected in JSON.`

## Step 3: LLM structuring

`structure_steps_with_llm(raw_steps)` is the semantic conversion stage.

It calls `_call_structuring_llm(raw_steps)`, then validates the result with `_validate_structured_output`.

### Purpose of the structuring LLM

The LLM converts noisy browser logs into a normalized workflow with a narrow schema:

- infer the goal
- remove focus/wait noise
- merge redundant steps
- keep only allowed action types
- replace hardcoded values with placeholders like `{{user_email}}`

### Current structured step types

The current prompt and validator support:

- `navigate`
- `fill`
- `click`
- `scroll`

This is important because older docs may imply only `navigate`, `fill`, and `click`. That is no longer true.

### Prompt contract

The system prompt in `app/services/skill_pack_builder.py` tells the model to:

- remove focus and wait actions
- fold redundant scroll jitter into purposeful `scroll` steps
- infer user intent
- replace hardcoded values with placeholders
- emit JSON only

Expected output shape:

```json
{
  "goal": "Human-readable workflow goal",
  "steps": [
    { "type": "navigate", "url": "https://example.com/login" },
    { "type": "fill", "selector": "input[name=email]", "value": "{{user_email}}" },
    { "type": "click", "selector": "text=Sign in" },
    { "type": "scroll", "selector": "text=Load more reviews" },
    { "type": "scroll", "delta_y": 480 }
  ]
}
```

### Environment configuration

Configuration comes from `app/config.py`. The settings class uses `env_prefix="SKILL_"`, so the builder-specific fields map to variables like `SKILL_PACK_LLM_MODEL`.

Relevant settings:

| Setting field | Typical env var | Meaning |
| --- | --- | --- |
| `pack_llm_enabled` | `SKILL_PACK_LLM_ENABLED` | Enables/disables LLM structuring |
| `pack_llm_endpoint` | `SKILL_PACK_LLM_ENDPOINT` | OpenAI-compatible base URL or chat-completions URL |
| `pack_llm_model` | `SKILL_PACK_LLM_MODEL` | Model name |
| `pack_llm_api_key` | `SKILL_PACK_LLM_API_KEY` | Single bearer key |
| `pack_llm_api_keys` | `SKILL_PACK_LLM_API_KEYS` | Comma-separated rotating key pool |
| `pack_llm_timeout_ms` | `SKILL_PACK_LLM_TIMEOUT_MS` | Request timeout, minimum enforced to 360000 ms |
| `pack_llm_structure_temperature` | `SKILL_PACK_LLM_STRUCTURE_TEMPERATURE` | Structuring temperature |
| `pack_llm_structure_max_tokens` | `SKILL_PACK_LLM_STRUCTURE_MAX_TOKENS` | Optional token cap |
| `pack_llm_top_p` | `SKILL_PACK_LLM_TOP_P` | Optional top-p |

Validation/clamping behavior in `Settings`:

- `pack_llm_timeout_ms` is clamped to at least `360000`.
- `pack_llm_structure_temperature` is clamped into `[0.0, 2.0]`.
- `pack_llm_top_p` is normalized to `None` unless it is within `(0.0, 1.0]`.
- `pack_llm_structure_max_tokens` is normalized to `None` unless it is a positive integer.

### Request transport details

The builder uses `urllib.request` directly, not the shared general LLM client.

Behavior:

- `_chat_completions_url()` accepts either a full `/chat/completions` URL or a base endpoint and normalizes it.
- The request body is OpenAI-style chat completions JSON.
- `response_format: { "type": "json_object" }` is sent for most hosts.
- Special case: if the host contains `integrate.api.nvidia.com`, strict JSON mode is omitted because the code comments note repeated upstream timeout issues with that host.

### API key rotation

`app/llm/pack_llm_keys.py` provides round-robin key selection:

- `configured_pack_keys()` returns the CSV key pool if present, otherwise the single key.
- `next_pack_api_key()` rotates through that pool under a lock.

This is only rotation, not parallel fanout.

### Retry behavior

Transient HTTP statuses retried by the builder:

- `502`
- `503`
- `504`

Retry count:

- at most **3** HTTP attempts (initial call + up to two retries) on transient statuses

The retry loop is only for those transient HTTP statuses.

### Parsing the provider response

The response is accepted in two modes:

1. The top-level provider payload itself is already `{ "goal": ..., "steps": ... }`.
2. Otherwise the builder extracts assistant content and parses that content as JSON.

`_parse_strict_json_object()` is fairly forgiving about wrappers:

- accepts raw JSON object text
- can extract the first balanced `{...}` block
- can parse JSON inside fenced code blocks

But it still requires the final parsed result to be a JSON object.

## Step 4: Structured output validation

`_validate_structured_output(structured)` enforces the schema before anything becomes executable.

Global rules:

- `goal` must be non-empty text.
- `steps` must be a list.
- every step must be a JSON object
- the final validated step list must be non-empty

Each step is normalized through `_canonical_step(step, index)`.

### Allowed structured step types

`_ALLOWED_STRUCTURED_TYPES` currently contains:

- `navigate`
- `fill`
- `click`
- `scroll`

Anything else fails immediately.

### Selector validation rules

`_validate_selector(selector, step_type=...)` rejects:

- empty selectors
- XPath selectors
- selectors containing the string `xpath`
- generic selectors like `input`, `button`, `textarea`, `select`

Additional type-specific rules:

- `fill` selectors must match `input[name=...]`
- `click` cannot be bare `button`
- `assert_visible` later reuses the same selector validator, but without the extra `fill`-only rule

### `navigate` validation

Rules:

- requires `url`
- URL must be absolute `http://` or `https://`

### `fill` validation

Rules:

- requires a valid `input[name=...]` selector
- requires non-empty `value`

### `click` validation

Rules:

- requires a non-empty validated selector

There is no requirement that a click selector be `text=...`, but the prompt strongly nudges the LLM that way, and recovery works best for text-based selectors.

### `scroll` validation

Rules:

- may include `selector`
- may include `delta_y`
- may include `delta_x`
- must include at least one of:
  - a non-empty selector
  - a non-zero wheel delta

Details:

- `selector`, when present, is validated using the click-selector rules.
- `delta_y` and `delta_x` must be numeric if present.
- `delta_x` defaults to `0.0`.

This means the LLM can emit either:

- "scroll this element into view"
- "wheel down by N pixels"
- or both in the same step

## Step 5: Package naming

The builder generates the package name in two parts.

### `_package_title(payload, structured)`

It chooses a human title from:

1. `structured["goal"]`
2. otherwise metadata-like containers on the original payload:
   - `meta`
   - `package_meta`
   - `metadata`
   - `package`
   - `workflow`
   - `recording`
   - `session`
3. then title-like keys:
   - `title`
   - `name`
   - `id`
   - `slug`
   - `workflow_name`
   - `workflowName`
4. fallback: `generated_skill`

### `_slugify_name(value)`

This uses `_normalize_name()`:

- inserts underscores on camelCase boundaries
- replaces non-word characters with underscores
- lowercases everything
- prefixes names that start with digits with `input_`

Examples:

- `Customer Onboarding` -> `customer_onboarding`
- `Delete-Database!` -> `delete_database`

That slug becomes the workflow directory name and the manifest `name`.

## Step 6: Input inference

`parse_inputs(payload)` derives runtime inputs for placeholder substitution.

In the normal `build_skill_package()` path, it is called with the validated structured object, not with the original raw recording.

That distinction matters.

### Placeholder discovery

The function serializes the payload to JSON text and scans for:

```text
{{ variable_name }}
```

using `_VAR_PATTERN`.

Each match is normalized through `_normalize_name()`.

### Declared input discovery

It also looks for declared inputs inside these keys:

- `inputs`
- `parameters`
- `params`
- `variables`

And input names may come from:

- `name`
- `id`
- `key`
- `label`
- `input_name`
- `inputName`
- `field`
- `binding`

In the main build path, these declared inputs only matter if the structured object itself includes such fields. In practice, placeholders in step values are the main source.

### Sensitive input detection

Names are marked `sensitive: true` if they contain any of these hints:

- `password`
- `passcode`
- `passwd`
- `secret`
- `token`
- `api_key`
- `apikey`
- `private_key`
- `credential`
- `auth`
- `otp`
- `pin`

### Output format

`parse_inputs()` returns a list like:

```json
[
  {
    "name": "user_email",
    "type": "string",
    "description": "Enter user email"
  },
  {
    "name": "password",
    "type": "string",
    "description": "Enter password",
    "sensitive": true
  }
]
```

The builder serializes that as:

```json
{
  "inputs": [ ... ]
}
```

into `inputs.json`.

## Step 7: Execution-plan compilation

`compile_execution(structured_steps)` turns validated structured steps into runtime steps.

Allowed runtime types are:

- `navigate`
- `fill`
- `click`
- `scroll`
- `assert_visible`

`assert_visible` is not an LLM-authored structured step. It is compiler-inserted.

### Why compilation exists

The structured steps are already validated, but compilation adds runtime intent:

- injects safety guards
- deduplicates immediate duplicate plan entries
- converts structured steps into the final runtime vocabulary

### Safety augmentation rules

The compiler inserts extra guards in two cases.

#### Destructive clicks

Before a click whose selector text suggests a destructive action, it inserts:

```json
{ "type": "assert_visible", "selector": "<same selector>" }
```

Destructive text heuristics are based on selector text containing:

- `delete`
- `remove`
- `destroy`
- `drop`
- `archive`
- `reset`
- `disable`
- `revoke`

#### Login clicks

After a click whose selector text suggests login, it inserts:

```json
{ "type": "assert_visible", "selector": "text=Dashboard" }
```

Login text heuristics:

- `sign in`
- `signin`
- `log in`
- `login`

This is a simple heuristic, not a configurable workflow-specific success detector.

### Duplicate suppression

`_append_step()` skips an appended step if it is exactly equal to the immediately previous step.

This only removes adjacent exact duplicates.

## Step 8: Execution-plan validation

`_validate_execution_plan(plan)` validates the compiled runtime plan again.

It enforces:

- the plan is non-empty
- every step type is in `_ALLOWED_EXECUTION_TYPES`
- `fill`, `click`, `assert_visible`, and `scroll` selectors remain valid
- `navigate` URLs remain absolute HTTP(S)
- no wait steps exist
- no XPath survives serialization
- at least one `fill` step exists
- at least one `click` step exists

That last rule is important: workflows that only navigate and scroll, or only click without any fill, are rejected by the current builder.

### Scroll validation at runtime-plan level

For `scroll` the validator checks again that:

- `delta_y` is numeric if present
- `delta_x` is numeric if present
- there is either a selector or a non-zero wheel movement

## Step 9: Recovery-map generation

`generate_recovery(structured_steps)` derives `recovery.json`.

It calls `compile_execution()` internally, then walks the compiled plan.

Only `fill` and `click` steps get recovery entries.

`navigate`, `scroll`, and `assert_visible` do not.

### Recovery entry structure

Each recovery entry looks like:

```json
{
  "step_id": 2,
  "intent": "click_sign_in",
  "target": {
    "text": "Sign in",
    "type": "button",
    "section": "login form"
  },
  "anchors": [],
  "fallback": {
    "text_variants": ["Sign in", "Log in"],
    "visual_hint": "visible button"
  }
}
```

Fields are derived as follows:

- `step_id`: 1-based index in the compiled execution plan
- `intent`: normalized slug from step type + target text/type
- `target.text`: extracted from the selector when possible
- `target.type`: `field` for fill, `button` otherwise
- `target.section`: heuristic section label such as `danger zone` or `login form`
- `anchors`: extra spatial/context hints
- `fallback.text_variants`: small list of alternative visible labels
- `fallback.visual_hint`: coarse visual cue such as `text input`, `red button`, or `visible button`

### Recovery text-variant heuristics

Examples:

- `Delete` may generate `["Delete", "Remove"]`
- login labels may generate `["Sign in", "Log in"]`
- `Continue` may generate `["Continue", "Next"]`
- `Save` may generate `["Save", "Update"]`

These are not model-generated; they are code heuristics.

## Step 10: Manifest generation

`build_manifest(inputs, package_name)` creates:

```json
{
  "name": "customer_onboarding",
  "version": "1.0.0",
  "inputs": [
    { "name": "user_email", "type": "string" },
    { "name": "password", "type": "string", "sensitive": true }
  ]
}
```

Notes:

- Version is hard-coded to `1.0.0`.
- Only compact input metadata is stored.
- Descriptions are not copied into the manifest.

## Step 11: Human-readable `skill.md`

`generate_skill_markdown(package_name, structured_steps, inputs)` creates a deterministic markdown summary.

Current structure:

- `# <package_name>`
- `## Inputs`
- `## Steps`

### Inputs section

Each input becomes a bullet:

```md
- `{{user_email}}`: Enter user email.
```

Sensitive fields get an added sentence:

```md
Keep this value secure.
```

### Steps section

Each validated structured step is rewritten through `_instruction_for_step()`.

Important behavior:

- It describes structured steps, not the compiled plan.
- Compiler-inserted `assert_visible` steps do not appear here.
- `scroll` steps do appear here.

Examples of generated phrasing:

- `navigate` to a login-like URL may become `Open login page`
- `fill` with `{{user_email}}` may become `Enter {{user_email}} in email`
- `click` with `text=Submit` may become `Click "Submit"`
- selector-based scroll may become `Scroll to reveal Load more reviews`
- wheel scroll may become `Wheel scroll (Δy=480)`

### Optional LLM markdown generator

`app/llm/skill_pack_llm.py` contains `generate_skill_markdown_with_llm(summary)`.

Current status:

- it can generate a richer `skill.md`
- it uses the same pack LLM endpoint/model family
- it is not called by `build_skill_package()`
- the shipping build path uses only deterministic markdown generation

If you wire it in later, document that separately because it changes output stability.

## Step 12: Visual asset collection

The builder can persist screenshots into `visuals/`.

This happens through `_collect_visual_assets(payload)`.

### Source session discovery

`_source_session_id(payload)` looks in:

- `meta.source_session_id`
- `package_meta.source_session_id`

### Where step images can come from

For each extracted raw step, the builder looks for screenshot-like data in:

- `step.screenshot.full_url`
- `step.screenshot.scroll_url`
- `step.screenshot.element_url`
- `step.signals.visual.full_screenshot`
- `step.signals.visual.scroll_screenshot`
- `step.signals.visual.element_snapshot`
- `step.visual.full_screenshot`
- `step.visual.scroll_screenshot`
- `step.visual.element_snapshot`

### Path normalization rules

The builder:

- extracts a relative path from the URL or raw path-like value
- rejects absolute paths and parent traversal
- may prefix with `sessions/<session_id>/...`

Then it resolves the asset through `app.editor.assets.resolve_skill_asset`.

### What gets copied

- launch image, if found: `Image_0.<ext>`
- per-step images: `Image_<step_index>.<ext>`

Allowed suffixes:

- `.png`
- `.jpg`
- `.jpeg`
- `.gif`
- `.webp`

Unsupported or missing assets are silently skipped.

## Step 13: Persist to disk

`write_skill_package_files(bundle_slug, workflow_slug, files, ...)` in `app/storage/skill_packages.py` writes one workflow and refreshes that bundle’s `index.json` and `README.md`.

### Scaffold behavior

`ensure_bundle_scaffold(bundle_slug)` guarantees:

- `output/skill_package/<bundle_slug>/`
- `workflows/`
- `engine/` (copy from repo `engine/`)
- `README.md` (bundle-wide)

The engine files are copied from the repo-level `engine/` directory:

- `orchestrator.ts`
- `execution.ts`
- `recovery.ts`
- `logging.ts`
- `config.ts`

This means every persisted package shares the latest engine snapshot from the repository at write time.

### Workflow files written

The builder writes:

- `skill.md`
- `execution.json`
- `recovery.json`
- `inputs.json`
- `manifest.json`

### Obsolete files removed

These legacy files are deleted from the workflow folder if present:

- `skill.json`
- `execution.md`
- `execution_plan.json`

Those legacy response/export fields are no longer emitted or accepted; generated packages use the canonical workflow files only.

### Visuals directory behavior

- `visuals/` is always created
- existing non-hidden image files are cleared before rewriting
- new visual assets are written with sanitized basenames

## Builder response shape

`build_skill_package()` returns:

| Key | Meaning |
| --- | --- |
| `name` | workflow folder slug |
| `bundle_slug` | bundle directory under `output/skill_package/` |
| `skill_md` | generated markdown |
| `execution_json` | serialized runtime plan |
| `recovery_json` | serialized recovery map |
| `inputs_json` | serialized inputs payload |
| `manifest_json` | serialized manifest |
| `input_count` | number of inferred inputs |
| `step_count` | number of compiled execution steps |
| `used_llm` | always `true` in the current build path |
| `warnings` | currently always `[]` |

## ZIP export flow

ZIP building lives in `build_skill_package_zip(...)`.

Two entry points use it:

- `POST /skill-pack/export` (optional `bundle_name` for path prefix inside the ZIP)
- `GET /skill-pack/bundles/{bundle}/download` (full bundle tree from disk)

### Required export inputs

Strictly required:

- non-empty `skill_md`
- non-empty `inputs_json`
- non-empty `manifest_json`
- non-empty `execution_json`
- non-empty `recovery_json`

### ZIP contents

`POST /skill-pack/export` uses `output/skill_package/<bundle>/` as the logical root (`<bundle>` from `bundle_name`, default `default`). The archive includes:

- `<root>/README.md`
- `<root>/<index>.json`
- `<root>/engine/*.ts`
- `<root>/workflows/<workflow_slug>/skill.md`
- `<root>/workflows/<workflow_slug>/execution.json`
- `<root>/workflows/<workflow_slug>/recovery.json`
- `<root>/workflows/<workflow_slug>/inputs.json`
- `<root>/workflows/<workflow_slug>/manifest.json`

Workflow `visuals/`:

- populated when assets exist under that workflow folder on disk
- otherwise `<root>/workflows/<workflow_slug>/visuals/.gitkeep`

The export ZIP filename is derived from the bundle path and workflow slug, e.g. `output_skill_package_<bundle>_<workflow>.zip`.

`GET /skill-pack/bundles/{bundle}/download` zips the on-disk bundle tree as-is under `output/skill_package/<bundle>/`.

## Runtime execution model

The generated package is meant to be executed by the TypeScript engine under `engine/`.

### Execution entry point

`engine/execution.ts` exports:

```ts
executeWorkflow({
  page,
  executionPath,
  recoveryPath,
  inputs,
  config
})
```

### Placeholder substitution

The runtime interpolates `{{name}}` placeholders in:

- `navigate.url`
- `fill.selector`
- `fill.value`
- `click.selector`
- `scroll.selector`
- `assert_visible.selector`

If an input is missing, runtime throws an error immediately.

### Runtime behavior per step type

- `navigate`: `page.goto(..., waitUntil: "domcontentloaded")`, retried once on failure
- `fill`: `locator.fill(...)`
- `click`: `locator.click(...)`
- `scroll`: optional `locator.scrollIntoViewIfNeeded(...)` plus optional `mouse.wheel(...)`
- `assert_visible`: `locator.waitFor({ state: "visible" })`

### Recovery behavior

The runtime:

- loads `recovery.json`
- for each action step, retries the primary selector
- then tries alternate `text=...` selectors derived from `fallback.text_variants`
- can optionally attempt LLM-assisted recovery, but `maybeLlmRecoveryAssist()` is currently a stub returning `[]`

Important limitation:

- alternate selectors are only generated for primary selectors that are already text-based
- non-text selectors do not benefit much from the current recovery engine

## Read/list/delete behavior

`app/storage/skill_packages.py` also provides non-build management helpers.

### List

`list_skill_bundle_summaries()` (exposed via `GET /skill-pack/packages` as `packages`):

- scans direct child directories of `output/skill_package/`
- each entry is one **bundle**; nested `workflows/` holds workflow folders with manifests
- sorts bundles by newest workflow modification time descending

Each row contains:

- `package_name` — the bundle slug
- `modified_at`
- `workflows` — per-workflow metadata (`workflow_slug`, labels, file list)
- `files` — flattened search keys for UI (e.g. `workflows/foo/skill.md`)

### Read

- `read_skill_package_bundle_files(bundle_slug)` — full bundle as a flat key map (`README.md`, `engine/...`, `workflows/<slug>/...`).
- `read_skill_package_files(bundle_slug, workflow_slug)` — bundle README/index/engine plus **unprefixed** keys for one workflow (`skill.md`, `visuals/...`).

### Delete

- `delete_skill_package_bundle(bundle_slug)` removes the entire bundle directory.
- `delete_skill_package_workflow(bundle_slug, workflow_slug)` removes one workflow folder and refreshes `index.json`.

## Important invariants

If you change the system, keep these aligned together:

1. `_STRUCTURING_SYSTEM_PROMPT`
2. `_ALLOWED_STRUCTURED_TYPES`
3. `_canonical_step()`
4. `_ALLOWED_EXECUTION_TYPES`
5. `_validate_execution_plan()`
6. `engine/execution.ts` parser and executor
7. `generate_skill_markdown()` phrasing logic if the new step should appear in docs
8. `generate_recovery()` if the new step should influence fallback behavior

If one of those moves and the others do not, the builder will either reject valid outputs, emit invalid plans, or generate packages the runtime cannot execute.

## Current limitations and gotchas

- The build path requires the LLM. There is no deterministic fallback structurer.
- `build_skill_package()` rejects workflows without at least one `fill` and one `click`.
- Success validation for login is hard-coded to `text=Dashboard`.
- Recovery is heuristic and strongest for text-based selectors.
- `skill.md` is deterministic and concise; it is not a full natural-language agent spec.
- `scroll` is fully supported in builder and runtime even if older docs or callers assume otherwise.
- Visual assets are best-effort. Missing images do not fail the build.

## Fast reasoning checklist for future edits

When debugging or extending this system, verify these questions in order:

1. Did `_extract_steps()` actually find step dictionaries in the incoming JSON?
2. Did the LLM emit only supported structured step types?
3. Did selectors satisfy the builder's narrow rules?
4. Did input placeholders normalize to the names the runtime will receive?
5. Did compilation inject extra `assert_visible` steps that affect step numbering?
6. Does `recovery.json` still line up with compiled step IDs?
7. Does `engine/execution.ts` support every step type present in `execution.json`?
8. Are persisted files and ZIP exports using the same canonical artifacts?

If you answer those eight questions, you can usually localize the bug quickly.
