from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
GENERIC_SELECTORS = {"button", "input", "div", "span", "a", "form"}


@dataclass
class PhaseResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)
    score: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Bundle:
    name: str
    root: Path

    @property
    def skills(self) -> list[Path]:
        skills_dir = self.root / "skills"
        if not skills_dir.is_dir():
            return []
        return sorted(p for p in skills_dir.iterdir() if p.is_dir())


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_bundle(plugin_name: str, project_root: Path) -> Bundle:
    candidate = project_root / "output" / "skill_package" / plugin_name
    if not candidate.is_dir():
        raise FileNotFoundError(f"Bundle not found: {candidate}")
    return Bundle(name=plugin_name, root=candidate)


def referenced_vars(payload: Any) -> set[str]:
    return {m.strip() for m in VAR_PATTERN.findall(json.dumps(payload, ensure_ascii=False))}


def selector_looks_generic(selector: str) -> bool:
    s = (selector or "").strip()
    if not s:
        return True
    if s.startswith("//"):
        return True
    return s.lower() in GENERIC_SELECTORS
