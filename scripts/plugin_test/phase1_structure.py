from __future__ import annotations

import json
from pathlib import Path

from .common import Bundle, PhaseResult, load_json

REQUIRED_BUNDLE_FILES = [
    "README.md",
    "auth/auth.json",
    "orchestration/index.md",
    "orchestration/planner.md",
    "orchestration/schema.json",
    "execution/executor.js",
    "execution/recovery.js",
    "execution/tracker.js",
    "execution/validator.js",
]
REQUIRED_SKILL_FILES = [
    "manifest.json",
    "execution.json",
    "recovery.json",
    "input.json",
    "SKILL.md",
]
REQUIRED_MANIFEST_FIELDS = [
    "name",
    "version",
    "entry",
    "execution_mode",
    "recovery_mode",
    "inputs",
]


def run(bundle: Bundle) -> PhaseResult:
    failures: list[str] = []

    for rel in REQUIRED_BUNDLE_FILES:
        if not (bundle.root / rel).exists():
            failures.append(f"missing bundle file: {rel}")

    index_candidates = list(bundle.root.glob("*.json"))
    if not any(p.name.endswith(".json") and p.parent == bundle.root for p in index_candidates):
        failures.append("missing plugin index .json at bundle root")

    skills = bundle.skills
    if not skills:
        failures.append("no skills/ subdirectories found")

    for skill_dir in skills:
        rel_skill = skill_dir.relative_to(bundle.root)
        for f in REQUIRED_SKILL_FILES:
            target = skill_dir / f
            if not target.exists():
                failures.append(f"missing skill file: {rel_skill / f}")
                continue
            if f.endswith(".json"):
                try:
                    load_json(target)
                except json.JSONDecodeError as e:
                    failures.append(f"invalid JSON in {rel_skill / f}: {e}")

        manifest_path = skill_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = load_json(manifest_path)
            except json.JSONDecodeError:
                continue
            for field in REQUIRED_MANIFEST_FIELDS:
                if field not in manifest:
                    failures.append(f"manifest missing field '{field}' in {rel_skill}")
            if manifest.get("execution_mode") != "deterministic":
                failures.append(f"{rel_skill}: execution_mode must be 'deterministic'")
            if manifest.get("recovery_mode") != "tiered":
                failures.append(f"{rel_skill}: recovery_mode must be 'tiered'")
            if not isinstance(manifest.get("inputs"), list):
                failures.append(f"{rel_skill}: inputs must be a list")

    return PhaseResult(
        name="Phase 1 Structure",
        passed=len(failures) == 0,
        details=failures,
    )
