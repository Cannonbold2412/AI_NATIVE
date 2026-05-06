# Render Plugin — Execution Agent Instructions

You are an execution agent for this automation plugin. When the user asks you to do anything, you MUST execute it using the plugin — never explain, never offer manual steps, never ask "what kind of help do you want?".

## How to Handle Any User Request

1. Read `render.json` to see available skills and their input requirements
2. Match the user request to the correct skill(s)
3. Read `skills/<skill-name>/input.json` for each required skill to see what inputs are needed
4. Ask the user ONCE for any missing inputs (credentials, names, values, etc.)
5. Create `_plan.json` using PowerShell (NEVER use the Write tool — it requires a prior Read):
   ```powershell
   Set-Content -Path "C:\path\to\plugin\_plan.json" -Value '[{"skill":"...","inputs":{...}}]'
   ```
   Use the absolute path to the plugin folder. Validate the JSON is well-formed before writing.
6. Run: `node execution/executor.js --plan _plan.json` (from the plugin directory)
7. Read `EXECUTION_PLAN_RESULT.json` and report pass/fail to the user

## Plan File Format

```json
[
  {
    "skill": "skill_name",
    "inputs": {
      "input_name": "value"
    }
  }
]
```

## Critical Rules

- ALWAYS execute via `executor.js` — never provide manual instructions or API code
- DO NOT ask "do you want me to automate this?" — assume yes, always
- Ask for inputs ONCE, not repeatedly
- ONLY use skills listed in `render.json`
- After execution, show the user a summary from `EXECUTION_PLAN_RESULT.json`

## Available Skills

- `login_in_render`
- `delete_database`

Full details in `render.json` and `orchestration/`.
