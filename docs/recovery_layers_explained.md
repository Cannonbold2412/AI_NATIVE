# Recovery Layers - Exact Behavior

## What "recovery" means here

There are two separate pieces:

1. Compile-time recovery generation in [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1187)
2. Runtime recovery layer execution scaffold in [skill_packages.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/storage/skill_packages.py:120)

The first one is implemented. The second one is now partially implemented: deterministic fallbacks are wired, while LLM and vision are still placeholders.

## Runtime layer order

The generated runtime file `execution/recovery.js` now defines this order:

- Layer `1`: selector alternatives / text-variant fallback
- Layer `2`: anchors
- Layer `3`: LLM intent recovery
- Layer `4`: vision recovery
- Layer `0`: terminal failure state after all layers are exhausted

Source: [skill_packages.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/storage/skill_packages.py:123)

There is also a `runRecovery(ctx)` sequencer that tries layers `1 -> 2 -> 3 -> 4` in order and only emits layer `0` when every layer returns no usable recovery result.

## What each runtime layer does today

### Layer 1

Intent: try deterministic selector-based fallbacks first.

Actual implementation today:

- Sends a tracker event: ``${ctx.skill}:${ctx.step}:1``
- Loads the matching recovery entry from `recovery.json`
- Returns a `selector_fallback` payload with:
  - `selector_context.primary`
  - `selector_context.alternatives`
  - `fallback.text_variants` converted into `text="..."` selector candidates
- Deduplicates candidates

Source: [skill_packages.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/storage/skill_packages.py:133)

### Layer 2

Intent: fall back to semantic anchors after selector variants.

Actual implementation today:

- Sends a tracker event: ``${ctx.skill}:${ctx.step}:2``
- Loads the matching recovery entry from `recovery.json`
- Returns an `anchor_fallback` payload with:
  - normalized `anchors`
  - fallback `role`
- Returns `null` only if both anchors and role are absent

Source: [skill_packages.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/storage/skill_packages.py:137)

### Layer 3

Intent: use an LLM after deterministic fallbacks fail.

Actual implementation today:

- Sends a tracker event: ``${ctx.skill}:${ctx.step}:3``
- Returns `null`
- Does not call any LLM yet

Source: [skill_packages.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/storage/skill_packages.py:140)

### Layer 4

Intent: use vision last.

Actual implementation today:

- Sends a tracker event: ``${ctx.skill}:${ctx.step}:4``
- Returns `null`
- Does not yet compare the current screenshot with `visual_ref`

Source: [skill_packages.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/storage/skill_packages.py:143)

### Layer 0

This is not a recovery attempt. It is the final failure path.

Actual implementation today:

- Sends tracker event: ``${ctx.skill}:${ctx.step}:0``
- Throws `All recovery layers exhausted for <skill>:<step>`

Source: [skill_packages.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/storage/skill_packages.py:145)

## What is fully implemented today

The compile-time side builds the recovery data that runtime layer 1, layer 2, and eventually layer 4 consume.

For every compiled `fill` or `click` step, `generate_recovery()` emits one recovery entry into `recovery.json`.

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1187)

Each entry contains:

- `step_id`: the compiled step number
- `intent`: normalized action label like `click_sign_in` or `fill_email`
- `target.text`: text derived from the selector
- `target.role`: `"textbox"` for fill steps, otherwise empty
- `anchors`: prioritized labels such as `"Login"`, `"Danger Zone"`, or the target text
- `fallback.text_variants`: label variants such as `["Sign in", "Log in"]`
- `fallback.role`: usually `"textbox"` for fill
- `selector_context.primary`: the primary selector
- `selector_context.alternatives`: alternates such as normalized `text=...` or `input[name=...]`
- `visual_ref`: `visuals/Image_<step>.<ext>` when a matching stored image exists
- `visual_metadata`: whether a visual asset is available
- `recovery_metadata`: mode and action type metadata

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1098)

## How the compile-time recovery fields are derived

### `intent`

Built from step type plus a humanized selector target.

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:990)

### `anchors`

Rules:

- Add `"Login"` when target text looks login-related
- Add `"Danger Zone"` when target text looks destructive
- Add the target text itself for `fill` and `click`
- Deduplicate and keep at most 4

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1066)

### `fallback.text_variants`

Rules:

- Start with the target text
- Add hardcoded alternates for certain intents:
  - `Delete` <-> `Remove`
  - `Sign in` <-> `Log in`
  - `Continue` <-> `Next`
  - `Save` <-> `Update`
- Remove generic labels
- Keep at most 4

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:996)

### `selector_context.alternatives`

Rules:

- If primary selector is `text=...`, add a normalized text selector variant
- For fill steps, extract and add `input[name="..."]`
- Remove duplicates and unsafe selectors

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1043)

### `visual_ref`

Rules:

- Look for `visuals/Image_<step_id>` with `.png`, `.jpg`, `.jpeg`, or `.webp`
- If found, include `visual_ref`
- Mark `visual_metadata.available = true`

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1089)

## Validation rules

Before `recovery.json` is accepted, the builder enforces:

- Exactly one recovery entry per compiled `fill` or `click` step
- `intent` must exist
- `anchors` must be non-empty and non-generic
- `fallback.text_variants` must be non-empty and non-generic
- `selector_context.primary` must exist
- `selector_context.alternatives` must be a list of valid selectors
- No recovery entry may include `"validation"` or `"scroll"` data
- `visual_ref` must match the actual step image if present

Source: [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1138)

## Bottom line

Recovery currently works like this:

- `recovery.json` generation is real and strict
- Runtime sequencing is real: `1 -> 2 -> 3 -> 4`
- Tracker events are emitted per attempted layer
- Layer 1 returns selector and text-variant candidates
- Layer 2 returns anchor and role fallback data
- Layers 3 and 4 are still TODO placeholders
- If layers 1 and 2 produce nothing and layers 3 and 4 return `null`, the flow ends in layer 0 with an exception
