# Skill Package JSON - Field Usage Analysis

## Safe to Remove
Fields never read by the current generator path (`build_skill_package` in `app/services/skill_pack_builder.py`, which is the active implementation behind skill package generation):

| Field | Reason |
|-------|--------|
| `inputs` | Removed everywhere by `preprocess_skill_pack_declarations()` before compilation starts. |
| `parameters` | Removed everywhere by `preprocess_skill_pack_declarations()` before compilation starts. |
| `params` | Removed everywhere by `preprocess_skill_pack_declarations()` before compilation starts. |
| `variables` | Removed everywhere by `preprocess_skill_pack_declarations()` before compilation starts. |
| `name` / `id` / `key` / `label` / `input_name` / `inputName` / `field` / `binding` inside removed declaration blocks | These would only matter if declaration blocks survived, but those blocks are deleted first. |

## Must Keep
Fields read and used in output files:

| Field | Used In | Why It Matters |
|-------|---------|----------------|
| One step-list container: `steps` or `actions` or `events` or `recorded_events` or `interactions` or `workflow_steps` | `execution.json`, `input.json`, `manifest.json`, `recovery.json`, `SKILL.md` | Without a recognized step array, no workflow is detected and generation fails. |
| One workflow-container wrapper when batching workflows: `skills` or `workflows` or `flows` or `scenarios` or `recordings` | Same as above for each workflow | These keys are how the builder discovers multiple workflows in one JSON payload. |
| A workflow title field: preferably `title` | `manifest.json`, `SKILL.md`, workflow folder name, bundle index/README | Used to name the generated workflow when `package_name` is not passed explicitly. |
| Raw step semantic fields inside each step object | `execution.json`, `input.json`, `manifest.json`, `recovery.json`, `SKILL.md` | The builder forwards raw steps to the structuring LLM almost unchanged. Whatever fields describe the action, selector, URL, entered text, and intent are what ultimately become all generated artifacts. |
| `meta.source_session_id` or `package_meta.source_session_id` | `visuals/Image_0.*`, `recovery.json` | Used to resolve the launch screenshot and to help resolve relative visual asset paths. |
| `screenshot.full_url` or `screenshot.scroll_url` or `screenshot.element_url` | `visuals/*`, `recovery.json` `visual_ref` entries | These are the first-choice fields for locating stored screenshots for each step. |
| `visual.full_screenshot` or `visual.scroll_screenshot` or `visual.element_snapshot` | `visuals/*`, `recovery.json` `visual_ref` entries | Fallback visual-asset location fields when `screenshot.*` is not present. |
| `signals.visual.full_screenshot` or `signals.visual.scroll_screenshot` or `signals.visual.element_snapshot` | `visuals/*`, `recovery.json` `visual_ref` entries | Alternate fallback visual-asset location fields. |
| `extras.session_id` | `visuals/*`, `recovery.json` `visual_ref` entries | Conditionally required when a step-level visual path is relative and the root session id is missing. |

## Optimized Input JSON
The highest quality JSON with only the fields that actually matter. This is the safest minimal shape if you want both package generation and visual recovery support:

```json
{
  "title": "User login",
  "meta": {
    "source_session_id": "session_123"
  },
  "steps": [
    {
      "type": "navigate",
      "url": "https://example.com/login",
      "screenshot": {
        "full_url": "api/assets?path=launch.png"
      }
    },
    {
      "type": "fill",
      "selector": "input[name=email]",
      "value": "{{user_email}}",
      "screenshot": {
        "full_url": "api/assets?path=step-1.png"
      }
    },
    {
      "type": "fill",
      "selector": "input[name=password]",
      "value": "{{password}}",
      "screenshot": {
        "full_url": "api/assets?path=step-2.png"
      }
    },
    {
      "type": "click",
      "selector": "text=Sign in",
      "screenshot": {
        "full_url": "api/assets?path=step-3.png"
      }
    }
  ]
}
```

## Token Savings
- Original size: 45 distinct source-side field names/aliases referenced by the generator path
- Optimized size: 9 distinct fields in the minimal recommended JSON above
- Reduction: 80%

## Notes
- No function named `generate_skill_package` exists in the current file set. The active generator is `build_skill_package()` in [skill_pack_builder.py](/c:/Users/Lenovo/Desktop/AI_NATIVE/app/services/skill_pack_builder.py:1621).
- The biggest optimization is removing all declaration blocks: `inputs`, `parameters`, `params`, and `variables`. They are explicitly stripped before any compilation logic runs.
- Most step fields are not read by deterministic Python code; they matter because `structure_steps_with_llm()` sends raw step objects to the LLM after removing only `screenshot`, `visual`, `signals.visual`, and `extras.session_id` from the LLM copy.
- Because of that, arbitrary step fields that help describe user intent are not universally safe to remove, even if Python never names them directly.
- Visual fields are conditionally needed. If you do not care about `visuals/` assets or `recovery.json` `visual_ref` links, you can omit `meta.source_session_id`, `screenshot.*`, `visual.*`, `signals.visual.*`, and `extras.session_id`.
- If you always provide `title` at the workflow level, the alternate title aliases (`name`, `id`, `slug`, `workflow_name`, `workflowName`, and metadata-carried titles) become unnecessary.
