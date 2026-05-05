# Phase 2 Brief — render-plugin

You (Claude) will execute this plugin at runtime, so you are the right judge of
whether it is intelligible. Read the files below, then write your verdict to
`PHASE2_RESULT.json` in this same directory.

## Files to read
- `README.md`
- `orchestration/index.md`
- `orchestration/planner.md`
- `skills\generated_skill/manifest.json` (skill: **generated_skill**)
  - description: Delete a database on Render dashboard
  - inputs: ['user_email', 'user_password', 'db_name']
  - SKILL.md: `skills\generated_skill/SKILL.md`
  - execution: `skills\generated_skill/execution.json`
  - recovery: `skills\generated_skill/recovery.json`

## Sample task
For each skill, imagine a user asks you to execute it with these sample inputs:

```json
{
  "user_email": "<sample-user_email>",
  "user_password": "<sample-user_password>",
  "db_name": "<sample-db_name>"
}
```

Plan which steps you'd execute and confirm the recovery strategy is intelligible.

## Required output
Write `PHASE2_RESULT.json` with this exact schema:

```json
{
  "understood": true,
  "planned_steps": ["step 1 description", "step 2 description"],
  "recovery_strategy_clear": true,
  "blockers": []
}
```

- `understood`: can you confidently plan execution from these files?
- `planned_steps`: brief description of the action sequence you'd take
- `recovery_strategy_clear`: do recovery.json anchors/text_variants give you
  enough to recover when a primary selector misses?
- `blockers`: list any ambiguity, missing context, or contradiction
