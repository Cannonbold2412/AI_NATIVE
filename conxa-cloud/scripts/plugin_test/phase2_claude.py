from __future__ import annotations

import json
from pathlib import Path

from .common import Bundle, PhaseResult, load_json

BRIEF_FILENAME = "PHASE2_BRIEF.md"
RESULT_FILENAME = "PHASE2_RESULT.json"


def write_brief(bundle: Bundle) -> Path:
    skills = bundle.skills
    skill_lines: list[str] = []
    sample_inputs: dict[str, str] = {}

    for skill_dir in skills:
        rel = skill_dir.relative_to(bundle.root)
        manifest = load_json(skill_dir / "manifest.json")
        skill_lines.append(f"- `{rel}/manifest.json` (skill: **{manifest.get('name')}**)")
        skill_lines.append(f"  - description: {manifest.get('description')}")
        skill_lines.append(f"  - inputs: {[i.get('name') for i in manifest.get('inputs', [])]}")
        skill_lines.append(f"  - SKILL.md: `{rel}/SKILL.md`")
        skill_lines.append(f"  - execution: `{rel}/execution.json`")
        skill_lines.append(f"  - recovery: `{rel}/recovery.json`")
        for i in manifest.get("inputs", []):
            n = i.get("name")
            if n and n not in sample_inputs:
                sample_inputs[n] = f"<sample-{n}>"

    brief = f"""# Phase 2 Brief — {bundle.name}

You (Claude) will execute this plugin at runtime, so you are the right judge of
whether it is intelligible. Read the files below, then write your verdict to
`{RESULT_FILENAME}` in this same directory.

## Files to read
- `README.md`
- `orchestration/index.md`
- `orchestration/planner.md`
{chr(10).join(skill_lines)}

## Sample task
For each skill, imagine a user asks you to execute it with these sample inputs:

```json
{json.dumps(sample_inputs, indent=2)}
```

Plan which steps you'd execute and confirm the recovery strategy is intelligible.

## Required output
Write `{RESULT_FILENAME}` with this exact schema:

```json
{{
  "understood": true,
  "planned_steps": ["step 1 description", "step 2 description"],
  "recovery_strategy_clear": true,
  "blockers": []
}}
```

- `understood`: can you confidently plan execution from these files?
- `planned_steps`: brief description of the action sequence you'd take
- `recovery_strategy_clear`: do recovery.json anchors/text_variants give you
  enough to recover when a primary selector misses?
- `blockers`: list any ambiguity, missing context, or contradiction
"""
    target = bundle.root / BRIEF_FILENAME
    target.write_text(brief, encoding="utf-8")
    return target


def run(bundle: Bundle) -> PhaseResult:
    result_path = bundle.root / RESULT_FILENAME
    if not result_path.exists():
        return PhaseResult(
            name="Phase 2 Claude Live",
            passed=False,
            details=[f"{RESULT_FILENAME} not found — run --prepare, then have Claude write it, then --finalize"],
        )
    try:
        data = load_json(result_path)
    except Exception as e:
        return PhaseResult(name="Phase 2 Claude Live", passed=False, details=[f"invalid JSON: {e}"])

    blockers = data.get("blockers") or []
    passed = bool(data.get("understood")) and bool(data.get("recovery_strategy_clear")) and not blockers
    details: list[str] = []
    if not data.get("understood"):
        details.append("Claude reported understood=false")
    if not data.get("recovery_strategy_clear"):
        details.append("Claude reported recovery_strategy_clear=false")
    for b in blockers:
        details.append(f"blocker: {b}")
    return PhaseResult(
        name="Phase 2 Claude Live",
        passed=passed,
        details=details,
        extras={"planned_steps": data.get("planned_steps", [])},
    )
