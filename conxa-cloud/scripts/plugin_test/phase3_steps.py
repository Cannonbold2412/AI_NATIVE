from __future__ import annotations

from pathlib import Path

from .common import Bundle, PhaseResult, load_json, referenced_vars, selector_looks_generic


def _validate_skill(skill_dir: Path) -> list[str]:
    issues: list[str] = []
    rel = skill_dir.name
    execution = load_json(skill_dir / "execution.json")
    recovery = load_json(skill_dir / "recovery.json")
    input_spec = load_json(skill_dir / "input.json")

    declared_inputs = {i.get("name") for i in (input_spec if isinstance(input_spec, list) else input_spec.get("inputs", []))}

    for idx, step in enumerate(execution, start=1):
        tag = f"{rel}/execution.json[step-{idx}]"
        stype = step.get("type")
        sel = step.get("selector", "")

        if stype in {"click", "fill", "assert_visible"}:
            if not sel:
                issues.append(f"{tag}: missing selector for {stype}")
            elif selector_looks_generic(sel):
                issues.append(f"{tag}: overly generic selector '{sel}'")
        elif stype == "scroll":
            if not step.get("delta_y") and not sel:
                issues.append(f"{tag}: scroll needs non-zero delta_y or selector")
        elif stype == "navigate":
            if not step.get("url"):
                issues.append(f"{tag}: navigate missing url")
        elif stype == "fill" and "value" not in step:
            issues.append(f"{tag}: fill missing value")

        for var in referenced_vars(step):
            if var not in declared_inputs:
                issues.append(f"{tag}: variable {{{{{var}}}}} not declared in input.json")

    visuals_dir = skill_dir / "visuals"
    for entry in recovery.get("steps", []):
        ref = entry.get("visual_ref")
        if ref and not (skill_dir / ref).exists():
            issues.append(f"{rel}/recovery.json[step_id={entry.get('step_id')}]: visual_ref missing on disk: {ref}")

    return issues


def run(bundle: Bundle) -> PhaseResult:
    failures: list[str] = []
    total_steps = 0
    for skill_dir in bundle.skills:
        try:
            execution = load_json(skill_dir / "execution.json")
            total_steps += len(execution)
        except Exception:
            pass
        try:
            failures.extend(_validate_skill(skill_dir))
        except Exception as e:
            failures.append(f"{skill_dir.name}: validation crashed — {e}")

    passing = max(0, total_steps - len(failures))
    return PhaseResult(
        name="Phase 3 Steps",
        passed=len(failures) == 0,
        details=failures,
        extras={"passing": passing, "total": total_steps},
    )
