# LLM Understanding: `build_skill_package`

This document is written for an LLM or coding agent that needs to understand the active skill-package build path in detail.

Primary source file: `app/services/skill_pack_builder.py`

Related files:

- `app/api/skill_pack_routes.py`
- `frontend/src/services/skillPackBuilder.ts`
- `frontend/src/SkillPackBuilderPage.tsx`
- `app/config.py`
- `app/llm/pack_llm_keys.py`
- `app/storage/skill_packages.py`

Generated from the repository state on 2026-05-05.

## One-Sentence Summary

`build_skill_package(json_text, package_name=None, bundle_slug=None, realtime_sink=None)` takes raw workflow JSON text, cleans it, extracts one or more workflows, sends each workflow's sanitized raw steps to one pack-specific structuring LLM call, deterministically compiles the LLM's structured output into runtime artifacts, writes those artifacts under `output/skill_package/<bundle>/workflows/<workflow>/`, refreshes bundle files, and returns a response dictionary plus build logs.

## Most Important Facts

- The core function is synchronous Python.
- The main LLM call is `_call_structuring_llm`.
- There is one structuring LLM request per workflow.
- Multi-workflow payloads are handled sequentially in a normal `for` loop.
- The structuring LLM calls are not batched.
- The structuring LLM calls are not parallel.
- API-key rotation chooses one pack LLM key per attempt; it does not fan out to all keys.
- The SSE API route is async, but it wraps the blocking builder in an executor thread.
- The builder does not call `app/llm/anchor_vision_llm.py`.
- Recovery generation in this path is deterministic, not LLM-based.
- Visual screenshots are collected for output/recovery references, but screenshots are removed before the structuring LLM request.

## Public Entry Point

```python
def build_skill_package(
    json_text: str,
    package_name: str | None = None,
    *,
    bundle_slug: str | None = None,
    realtime_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    with skill_pack_build_log_scope(realtime_sink=realtime_sink) as build_log:
        try:
            return _build_skill_package_transaction(json_text, package_name, bundle_slug, build_log)
        except SkillPackBuildUserError:
            raise
        except ValueError as exc:
            raise SkillPackBuildUserError(str(exc), list(build_log)) from exc
```

Inputs:

| Argument | Type | Meaning |
|---|---:|---|
| `json_text` | `str` | Raw JSON text from UI/API. Must parse to object or array. |
| `package_name` | `str | None` | Optional workflow folder name hint. Applied directly only for single-workflow builds. |
| `bundle_slug` | `str | None` | Optional bundle folder name under `output/skill_package/`; normalizes to `default` if omitted. |
| `realtime_sink` | callable | Optional callback that receives each build-log row as it happens. Used by SSE streaming routes. |

Return type: `dict[str, Any]`.

Errors: validation and LLM failures are wrapped into `SkillPackBuildUserError`, preserving `build_log`.

## Full Call Graph

Normal successful path:

```text
build_skill_package
  -> skill_pack_build_log_scope
  -> _build_skill_package_transaction
      -> _prepare_skill_package_payload
          -> _parse_json_text
          -> _package_title
          -> _source_session_id
          -> preprocess_plugin_json
          -> preprocess_skill_pack_declarations
      -> _resolve_bundle_slug
          -> slugify_skill_bundle_name
          -> validate_bundle_slug
      -> _log_persist_phase_start
      -> _compile_skill_package_payloads
          -> _enumerate_raw_workflows
          -> for each RawWorkflow, sequentially:
              -> _compile_workflow_payload
                  -> structure_steps_with_llm
                      -> sanitize_raw_steps_for_llm
                      -> _call_structuring_llm
                      -> _validate_structured_output
                          -> _canonical_step
                          -> _validate_selector
                  -> parse_inputs
                  -> compile_execution
                  -> _validate_execution_plan
                  -> build_manifest
                  -> generate_skill_markdown
                  -> _collect_visual_assets
                  -> _generate_recovery_with_visuals
                      -> _write_visual_assets_to_temp_dir
                      -> generate_recovery
                          -> compile_execution
                          -> _build_recovery_entry
                          -> _validate_recovery_entries
                  -> _serialize_workflow_artifacts
      -> _persist_compiled_workflows
          -> _persist_skill_package_artifacts
              -> write_skill_package_files
              -> _build_plugin_index_json
      -> _refresh_bundle_runtime_files
          -> _write_bundle_index
          -> _build_plugin_index_json
      -> _format_build_skill_package_result
```

## Phase-by-Phase Behavior

### 1. Build log scope starts

`build_skill_package` opens `skill_pack_build_log_scope(realtime_sink=realtime_sink)`.

Effects:

- A mutable `build_log` list is created.
- `skill_pack_log_append(...)` rows are accumulated.
- If `realtime_sink` exists, rows are also emitted live.

Common log row kinds:

- `persist_phase`
- `bundle_compile_outline`
- `workflow_compile_start`
- `workflow_compile_complete`
- `pipeline_phase`
- `llm_request_sent`
- `llm_response_received`
- `llm_http_error`
- `llm_retry`
- `llm_timeout`
- `llm_network_error`
- `llm_response_parsed`

### 2. JSON parse and payload preparation

Function: `_prepare_skill_package_payload(json_text)`

Steps:

1. `_parse_json_text(json_text)` calls `json.loads`.
2. Root must be `dict` or `list`.
3. If root is a `dict`, it captures:
   - title hint via `_package_title(payload)`
   - source session id via `_source_session_id(payload)`
4. Calls `preprocess_plugin_json(payload)`.
5. Restores title/session metadata if preprocessing removed useful hints.
6. Calls `preprocess_skill_pack_declarations(payload)`.

Important cleanup:

- Declaration blocks are removed across the tree:
  - `inputs`
  - `parameters`
  - `params`
  - `variables`

Reason:

- The active generator wants runtime inputs inferred from the LLM-structured output and variable placeholders, not from stale recorder declarations.

### 3. Bundle slug resolution

Function: `_resolve_bundle_slug(explicit)`

Behavior:

- Calls `slugify_skill_bundle_name(explicit)`.
- Defaults empty value to `default`.
- Rejects invalid/reserved names with `validate_bundle_slug`.

Output bundle path is eventually:

```text
output/skill_package/<bundle_slug>/
```

### 4. Raw workflow enumeration

Function: `_compile_skill_package_payloads(payload, package_name=None)`

This calls `_enumerate_raw_workflows(payload)`.

Accepted workflow shapes:

- Root list of step objects.
- Root dict with direct step keys:
  - `steps`
  - `actions`
  - `events`
  - `recorded_events`
  - `interactions`
  - `workflow_steps`
- Root dict with workflow containers:
  - `skills`
  - `workflows`
  - `flows`
  - `scenarios`
  - `recordings`
- Nested dicts containing the above.

Each detected workflow becomes:

```python
RawWorkflow(
    title=<workflow title>,
    payload=<workflow payload>,
    steps=<list of raw step dicts>,
)
```

If no workflow contains steps, the build fails with:

```text
No workflow steps detected in JSON.
```

### 5. Multi-workflow loop

Function: `_compile_skill_package_payloads`

Important behavior:

```python
compiled = []
for index, raw_workflow in enumerate(raw_workflows, start=1):
    explicit_name = package_name if len(raw_workflows) == 1 else None
    compiled.append(_compile_workflow_payload(...))
```

Consequences:

- Sequential compilation.
- No `asyncio.gather`.
- No `Promise.all` on the backend.
- No thread pool for per-workflow compile.
- No LLM batching.
- If there are 3 workflows, the builder makes 3 separate structuring LLM calls, one after another.

### 6. Per-workflow compilation

Function: `_compile_workflow_payload(payload, raw_steps, package_name=None, source_title="")`

Subphases:

1. LLM structure.
2. Deterministic compile.
3. Visual asset collection.
4. Deterministic recovery map generation.
5. JSON serialization.

The function returns a `CompiledWorkflow` dataclass:

```python
CompiledWorkflow(
    name=<workflow_slug>,
    execution_json=<json string>,
    recovery_json=<json string>,
    inputs_json=<json string>,
    manifest_json=<json string>,
    skill_md=<markdown string>,
    inputs=<list of input dicts>,
    step_count=<int>,
    visual_assets=<dict filename -> bytes>,
    used_llm=True,
    warnings=[],
)
```

## LLM Structuring Layer

### Call site

```text
_compile_workflow_payload
  -> structure_steps_with_llm(raw_steps)
      -> sanitize_raw_steps_for_llm(raw_steps)
      -> _call_structuring_llm(sanitized_steps)
      -> _validate_structured_output(structured)
```

### What goes into the LLM

The LLM receives sanitized raw step objects.

Function: `sanitize_raw_steps_for_llm`

For each raw step:

- Deep copy the step.
- Remove `screenshot`.
- Remove `visual`.
- Remove `signals.visual`.
- Remove `extras.session_id`.

These removals reduce payload size and avoid sending heavy screenshot/session data.

The user message is minified JSON:

```json
{
  "raw_steps": [
    {
      "type": "navigate",
      "url": "https://example.test/login"
    },
    {
      "type": "fill",
      "selector": "input[name=email]",
      "value": "me@example.test"
    }
  ]
}
```

Actual body sends this as a string in `messages[1].content`.

### LLM HTTP request

Function: `_call_structuring_llm(raw_steps)`

Configuration fields:

- `settings.pack_llm_enabled`
- `settings.pack_llm_endpoint`
- `settings.pack_llm_model`
- `settings.pack_llm_api_key`
- `settings.pack_llm_api_keys`
- `settings.pack_llm_timeout_ms`
- `settings.pack_llm_structure_temperature`
- `settings.pack_llm_structure_max_tokens`
- `settings.pack_llm_top_p`

Default values from `app/config.py` include:

- `pack_llm_enabled = True`
- `pack_llm_timeout_ms = 360000`
- `pack_llm_structure_temperature = 0.0`
- `pack_llm_structure_max_tokens = None`
- `pack_llm_top_p = None`

Endpoint normalization:

- `_chat_completions_url(endpoint)` appends `/v1/chat/completions` when needed.

Request method:

- Blocking synchronous `urllib.request.urlopen(req, timeout=_timeout_s)`.

Request headers:

```text
Content-Type: application/json
Authorization: Bearer <pack_key>   # only if configured
```

API key behavior:

- `next_pack_api_key()` selects one key.
- With multiple `SKILL_PACK_LLM_API_KEYS`, keys rotate round-robin between attempts/calls.
- It does not call all keys in parallel.

Request body shape:

```json
{
  "model": "<settings.pack_llm_model>",
  "messages": [
    {
      "role": "system",
      "content": "<_STRUCTURING_SYSTEM_PROMPT>"
    },
    {
      "role": "user",
      "content": "{\"raw_steps\":[...]}"
    }
  ],
  "temperature": 0.0,
  "response_format": {
    "type": "json_object"
  }
}
```

Optional fields:

- `max_tokens` is included when `pack_llm_structure_max_tokens` is not `None`.
- `top_p` is included when `pack_llm_top_p` is not `None`.

Special case:

- If endpoint host contains `integrate.api.nvidia.com`, `response_format` is omitted.
- Reason in code comment: NVIDIA gateway showed repeated HTTP 504 around 300s with strict JSON mode.

### Structuring system prompt intent

The system prompt tells the LLM to:

- Convert messy browser interaction logs into structured steps.
- Remove focus and wait actions.
- Never output `wait`.
- Fold redundant scroll jitter into purposeful `scroll`.
- Merge redundant steps.
- Infer user intent.
- Replace hardcoded values with variables like `{{user_email}}`.
- Use only allowed output step types:
  - `navigate`
  - `fill`
  - `click`
  - `scroll`
  - `check`
- Prefer text selectors for buttons.
- Prefer `input[name="..."]` for fields.
- Never output generic `input`, generic `button`, or XPath.
- Output JSON only.

Note: the validator accepts a slightly wider set than the prompt: `navigate`, `fill`, `type`, `click`, `select`, `focus`, `scroll`, `check`.

### Retry behavior

Constants:

```python
_PACK_LLM_TRANSIENT_HTTP = frozenset({502, 503, 504})
max_tries = 3
```

Behavior:

- Up to 3 POST attempts total.
- Retries only for HTTP 502, 503, 504.
- No retry for timeout/network exceptions in the current code path; those are logged and raised immediately.
- No retry for invalid JSON response.
- No retry for validation failure after the LLM response is parsed.

Log events:

- Before each attempt: `llm_request_sent`
- On HTTP success: `llm_response_received`
- On transient retryable HTTP error: `llm_http_error`, then `llm_retry`
- On timeout: `llm_timeout`
- On network/transport error: `llm_network_error`
- After raw provider JSON parse: `llm_response_parsed`

### LLM response parsing

After HTTP success:

1. Raw response body is decoded as UTF-8.
2. `json.loads(raw)` parses provider response.
3. If response itself contains top-level `goal` and `steps`, use it directly.
4. Otherwise, `_extract_llm_content(response)` extracts chat-completion content:
   - `choices[0].message.content`
   - or text chunks from content arrays
   - or `choices[0].text`
5. `_parse_strict_json_object(content)` parses the JSON object.

`_parse_strict_json_object` is forgiving about:

- Leading/trailing prose.
- Markdown code fences.
- A balanced `{ ... }` JSON object embedded inside text.

It still requires the final parsed value to be a JSON object.

### Expected LLM structured output

```json
{
  "goal": "Sign in and delete a database",
  "steps": [
    {
      "type": "navigate",
      "url": "https://example.test/login"
    },
    {
      "type": "fill",
      "selector": "input[name=email]",
      "value": "{{user_email}}"
    },
    {
      "type": "fill",
      "selector": "input[name=password]",
      "value": "{{user_password}}"
    },
    {
      "type": "click",
      "selector": "text=Sign in"
    },
    {
      "type": "check",
      "kind": "url",
      "pattern": "/dashboard"
    }
  ]
}
```

### Structured output validation

Function: `_validate_structured_output(structured)`

Requirements:

- `goal` must be present and non-empty.
- `steps` must be a list.
- Every step must be a JSON object.
- At least one executable step must exist.

Each step passes through `_canonical_step(step, index)`.

Step rules:

#### `navigate`

- Requires absolute HTTP(S) URL.
- Output:

```json
{ "type": "navigate", "url": "https://..." }
```

#### `fill` / `type`

- Requires valid selector.
- Requires non-empty value.
- Fill selector must use `input[name=...]`.
- Output:

```json
{ "type": "fill", "selector": "input[name=email]", "value": "{{user_email}}" }
```

#### `click`

- Requires valid non-generic selector.
- XPath is rejected.
- Generic `button` is rejected.
- Output:

```json
{ "type": "click", "selector": "text=Sign in" }
```

#### `select`

- Requires valid selector.
- Optional `value`.

#### `focus`

- Requires valid selector.

#### `scroll`

- Requires selector and/or non-zero wheel delta.
- `delta_y` and `delta_x` must be numeric if present.
- If selector is present, it is validated like a click selector.

Valid examples:

```json
{ "type": "scroll", "selector": "text=Load more" }
```

```json
{ "type": "scroll", "delta_y": 480 }
```

#### `check`

Allowed kinds:

- `url`
- `url_exact`
- `snapshot`
- `selector`
- `text`

Rules:

- `url` requires `pattern`.
- `url_exact` requires `url`.
- `snapshot` accepts numeric `threshold`.
- `selector` requires valid selector.
- `text` requires non-empty `text`.

## Deterministic Compile

After the LLM returns valid structured steps, no more LLM interpretation is used in the active builder path.

### Input parsing

Function: `parse_inputs(payload)`

It scans JSON for variable placeholders:

```text
{{user_email}}
{{user_password}}
```

Regex:

```python
_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
```

Each variable becomes:

```json
{
  "name": "user_email",
  "type": "string",
  "description": "Enter user email"
}
```

Sensitive inputs are marked when the normalized name contains hints:

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

### Execution compilation

Function: `compile_execution(structured_steps)`

Behavior:

- Reads `structured_steps["steps"]`.
- Canonicalizes each step again.
- Deduplicates adjacent identical steps via `_append_step`.
- Returns a list of runtime action dictionaries.

Then `_validate_execution_plan(plan)` enforces:

- Plan must not be empty.
- Step type must be allowed.
- At least one `fill` or `type` step must exist.
- At least one `click` step must exist.
- Fill selectors must use `input[name=...]`.
- Click/select/focus/scroll selectors must be valid.
- Navigate URLs must be absolute HTTP(S).
- Check steps must have required fields.
- Wait steps are rejected.
- XPath is rejected.
- Generic selectors are rejected.

Important consequence:

- A workflow with only navigation and clicking will fail because at least one fill and one click are required.

### Manifest generation

Function: `build_manifest(inputs, package_name, description="")`

Output shape:

```json
{
  "name": "delete_database",
  "description": "Sign in and delete a database",
  "version": "1.0.0",
  "entry": {
    "execution": "./execution.json",
    "recovery": "./recovery.json",
    "input": "./input.json"
  },
  "execution_mode": "deterministic",
  "recovery_mode": "tiered",
  "vision_enabled": true,
  "llm_required": false,
  "inputs": [
    {
      "name": "user_email",
      "type": "string"
    }
  ]
}
```

Important:

- `llm_required` is `false` in the generated manifest.
- This means runtime execution should be deterministic and should not require the pack structuring LLM.

### Skill markdown generation

Function: `generate_skill_markdown(package_name, structured_steps, inputs, document_title=None)`

Output:

- Heading from `document_title` or humanized package name.
- Inputs list.
- Human-readable ordered steps.

This function is deterministic.

There is a separate file `app/llm/skill_pack_llm.py` containing `generate_skill_markdown_with_llm`, but the active `build_skill_package` path shown here does not call it.

## Visual Asset Handling

Function: `_collect_visual_assets(payload)`

Inputs:

- Original cleaned workflow payload, not the sanitized LLM payload.

Sources:

- Screenshot URLs/paths in step fields.
- Visual fields in `signals.visual` or `step.visual`.
- Session event assets found through `source_session_id`.

Output:

```python
dict[str, bytes]
```

Example filenames:

- `Image_0.png`
- `Image_1.png`
- `Image_2.jpg`

Important:

- These image bytes are written into package visuals.
- They can be referenced by recovery entries.
- They are not sent to `_call_structuring_llm`.

## Recovery Map Generation

Function path:

```text
_generate_recovery_with_visuals(structured, visual_assets)
  -> create temp directory
  -> _write_visual_assets_to_temp_dir
  -> generate_recovery(structured, visuals_dir)
```

`generate_recovery` behavior:

1. Calls `compile_execution(structured_steps)` again.
2. Iterates compiled steps.
3. Keeps only recovery-eligible action types from `RECOVERY_ACTION_TYPES`.
4. Builds one entry per eligible step using `_build_recovery_entry`.
5. Validates all entries with `_validate_recovery_entries`.

Recovery entry shape:

```json
{
  "step_id": 3,
  "intent": "click_sign_in",
  "target": {
    "text": "Sign in",
    "role": ""
  },
  "anchors": [
    {
      "text": "Login",
      "priority": 1
    },
    {
      "text": "Sign in",
      "priority": 2
    }
  ],
  "fallback": {
    "text_variants": ["Sign in", "Log in"],
    "role": ""
  },
  "selector_context": {
    "primary": "text=Sign in",
    "alternatives": ["text=\"Sign in\""]
  },
  "visual_metadata": {
    "step_id": 3,
    "source": "stored_step_visual",
    "available": true
  },
  "recovery_metadata": {
    "mode": "tiered",
    "action_type": "click",
    "generated_by": "skill_pack_builder"
  },
  "visual_ref": "visuals/Image_3.png"
}
```

Recovery validation rejects:

- Missing entries for recovery-eligible steps.
- Missing or generic anchors.
- Missing fallback text variants.
- Invalid selectors.
- Recovery entries containing validation data.
- Recovery entries containing scroll data.
- Mismatched `visual_ref`.

Important distinction:

- `app/llm/anchor_vision_llm.py` can generate vision anchors through multimodal LLM calls in other compile paths.
- `build_skill_package` does not call that module.
- The recovery map here uses deterministic text/selector heuristics plus stored visual references.

## Serialization

Function: `_serialize_workflow_artifacts`

Returns four JSON strings:

```python
(
    inputs_json,
    manifest_json,
    execution_json,
    recovery_json,
)
```

Shapes:

```json
{
  "inputs": [...]
}
```

```json
{
  "name": "...",
  "description": "...",
  "version": "1.0.0",
  "entry": { ... },
  "execution_mode": "deterministic",
  "recovery_mode": "tiered",
  "vision_enabled": true,
  "llm_required": false,
  "inputs": [...]
}
```

```json
[
  { "type": "navigate", "url": "https://..." },
  { "type": "fill", "selector": "input[name=email]", "value": "{{user_email}}" },
  { "type": "click", "selector": "text=Sign in" }
]
```

```json
{
  "steps": [...]
}
```

## Persistence

Function: `_persist_skill_package_artifacts(compiled, bundle_slug)`

Calls:

```python
write_skill_package_files(
    bundle_slug,
    compiled.name,
    _workflow_file_payload(compiled),
    visual_assets=compiled.visual_assets,
)
```

Workflow file payload:

```python
{
    "execution.json": compiled.execution_json,
    "recovery.json": compiled.recovery_json,
    "input.json": compiled.inputs_json,
    "manifest.json": compiled.manifest_json,
    "SKILL.md": compiled.skill_md,
    "tests/test-cases.json": format_test_cases_stub_json_text(compiled.inputs),
}
```

Expected output layout:

```text
output/skill_package/<bundle_slug>/
  README.md
  <bundle_slug>.json
  package.json
  install.js
  orchestration/
    index.md
    planner.md
    schema.json
  engine/
    executor.js
    recovery.js
    tracker.js
    validator.js
  auth/
    auth.json
    credentials.example.json
  workflows/
    <workflow_slug>/
      SKILL.md
      execution.json
      recovery.json
      input.json
      manifest.json
      tests/
        test-cases.json
      visuals/
        Image_0.png
        Image_1.png
```

After writing all workflows:

```text
_refresh_bundle_runtime_files
  -> _write_bundle_index
  -> _build_plugin_index_json
```

This refreshes bundle-level index/runtime metadata.

## Final Result Dictionary

Function: `_format_build_skill_package_result`

Important behavior:

- The returned dictionary is based on the first persisted workflow.
- For multi-workflow builds, all workflow names are included in `workflow_names`.
- `skill_md` in the result is the bundle entry markdown from `orchestration/index.md`, not necessarily the per-workflow `SKILL.md`.

Shape:

```json
{
  "name": "delete_database",
  "bundle_slug": "default",
  "index_json": "{...}",
  "execution_json": "[...]",
  "recovery_json": "{...}",
  "inputs_json": "{...}",
  "manifest_json": "{...}",
  "input_count": 2,
  "step_count": 7,
  "used_llm": true,
  "warnings": [],
  "skill_md": "...",
  "workflow_names": ["delete_database"],
  "build_log": [...]
}
```

## API Routes

File: `app/api/skill_pack_routes.py`

### Non-streaming build

Route:

```text
POST /skill-pack/build
```

Handler:

```python
def post_build_skill_pack(body: SkillPackBuildBody) -> dict[str, Any]:
    return build_skill_package(
        body.json_text,
        package_name=body.package_name,
        bundle_slug=body.bundle_name,
    )
```

Body model:

```python
class SkillPackBuildBody(BaseModel):
    json_text: str
    package_name: str | None = None
    bundle_name: str = "default"
```

### Bundle-specific non-streaming build

Route:

```text
POST /skill-pack/bundles/{bundle_slug}/build
```

Uses path `bundle_slug` instead of `body.bundle_name`.

### Streaming build

Route:

```text
POST /skill-pack/build/stream
```

Handler:

```text
post_build_skill_pack_stream
  -> StreamingResponse(_skill_pack_build_sse_events(...))
```

Internal async generator:

```text
_skill_pack_build_sse_events
  -> creates SimpleQueue
  -> realtime_sink(entry) puts ("log", entry) into queue
  -> runner() calls blocking build_skill_package(..., realtime_sink=realtime_sink)
  -> asyncio.get_running_loop().run_in_executor(None, runner)
  -> while true:
       kind, data = await asyncio.to_thread(q.get)
       yield SSE log/done/error event
```

SSE events:

```json
{ "event": "log", "entry": { "...": "..." } }
```

```json
{ "event": "done", "result": { "...": "..." } }
```

```json
{ "event": "error", "message": "...", "build_log": [...] }
```

Important:

- The HTTP route is async.
- The builder itself remains synchronous.
- The blocking builder runs in an executor thread.
- The async generator waits for queue messages with `asyncio.to_thread(q.get)`.

## Frontend Path

File: `frontend/src/services/skillPackBuilder.ts`

Function:

```ts
export async function buildSkillPackage(
  jsonText: string,
  packageName?: string,
  bundleName?: string,
  options?: BuildSkillPackageOptions,
): Promise<SkillPackBuildResult>
```

Frontend behavior:

1. `parseJsonSource(jsonText)`
2. `validateSource(payload)`
3. Build request body:

```ts
const body = {
  json_text: JSON.stringify(payload),
  ...(packageName ? { package_name: packageName } : {}),
  ...(bundleName ? { bundle_name: bundleName } : {}),
}
```

4. If `options.onLog` exists:
   - use streaming endpoint.
5. Otherwise:
   - use non-streaming endpoint.
6. Normalize backend result into `SkillPackBuildResult`.

Frontend parallelism note:

- `frontend/src/SkillPackBuilderPage.tsx` may fetch selected source workflows with `Promise.all`.
- That happens before build.
- It does not make backend `build_skill_package` compile workflows in parallel.

## Sync / Async / Parallel / Batched Truth Table

| Question | Answer |
|---|---|
| Is `build_skill_package` async? | No. It is synchronous. |
| Is `_call_structuring_llm` async? | No. It uses blocking `urllib.request.urlopen`. |
| Is the streaming API route async? | Yes. It is an async FastAPI route returning `StreamingResponse`. |
| Does streaming make compilation async internally? | No. It runs blocking compilation in an executor thread. |
| Are multiple workflows compiled in parallel? | No. They are compiled sequentially. |
| Are multiple workflows sent in one batched LLM request? | No. One LLM request per workflow. |
| Are LLM requests retried? | Yes, only HTTP 502/503/504, up to 3 attempts total. |
| Are retries parallel? | No. Retries are sequential. |
| Are multiple API keys used in parallel for pack structuring? | No. One key is selected per attempt by round-robin. |
| Does `app/llm/client.py` support parallel fanout? | Yes, for `anchor_vision`, but this is not used by `build_skill_package`. |
| Does recovery call an LLM? | No, not in this path. |
| Does generated runtime require LLM? | Manifest says `llm_required: false`. |

## Failure Modes

### Input failures

- Invalid JSON.
- JSON root is not object or array.
- No workflow steps detected.
- Invalid bundle slug.

### LLM configuration failures

- `settings.pack_llm_enabled` is false.
- `settings.pack_llm_endpoint` is empty.
- `settings.pack_llm_model` is empty.

### LLM request failures

- HTTP failure.
- Timeout.
- URL/network error.
- Provider returns invalid JSON.
- Provider returns valid JSON but not usable structured object.

### LLM structured output failures

- Missing `goal`.
- Missing `steps`.
- Empty `steps`.
- Non-object step.
- Unsupported step type.
- Navigate URL is not absolute HTTP(S).
- Fill selector does not use `input[name=...]`.
- Missing selector.
- Generic selector such as `input` or `button`.
- XPath selector.
- Check step missing required field.
- Scroll step missing selector and non-zero delta.

### Execution validation failures

- Execution plan empty.
- Contains `wait`.
- Contains XPath.
- Missing at least one click.
- Missing at least one fill/type.
- Bad selector.
- Invalid check/scroll/navigate values.

### Recovery validation failures

- Missing recovery entry for a recovery-eligible step.
- Recovery entry missing anchors.
- Generic anchor labels.
- Missing fallback text variants.
- Invalid selector alternatives.
- Contains validation data.
- Contains scroll data.
- Invalid visual ref.

## Do Not Confuse These Paths

### `build_skill_package` path

Uses:

- `app/services/skill_pack_builder.py`
- Pack-specific `_call_structuring_llm`
- `settings.pack_llm_*`
- deterministic recovery generation

Does not use:

- `app/llm/client.call_llm`
- `app/llm/anchor_vision_llm.py`
- multimodal image LLM calls
- generic `settings.llm_*` for structuring

### Anchor vision path

File: `app/llm/anchor_vision_llm.py`

This path:

- Uses screenshots.
- Calls `call_llm("anchor_vision", ...)`.
- Uses `settings.llm_*`.
- Can fan out in parallel across keys through `app/llm/client.py` when `settings.llm_parallel_fanout_anchor_vision` is true.

This path is relevant to other compile/recovery systems, but not to the active `build_skill_package` implementation documented here.

## Minimal Mental Model

For one workflow:

```text
raw JSON text
  -> parse JSON
  -> remove noisy declarations
  -> extract raw steps
  -> remove screenshots/visuals before LLM
  -> POST sanitized raw steps to pack LLM
  -> receive { goal, steps }
  -> validate/canonicalize steps
  -> infer inputs from {{variables}}
  -> compile execution.json
  -> build manifest.json
  -> build SKILL.md
  -> collect screenshots from original payload
  -> build deterministic recovery.json
  -> write files to output/skill_package/<bundle>/workflows/<workflow>/
  -> refresh bundle index/runtime files
  -> return result + build_log
```

For multiple workflows:

```text
workflow 1: full sequence above
workflow 2: full sequence above
workflow 3: full sequence above
...
```

No backend batching or backend parallelism is added between those workflows.
