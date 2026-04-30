"""Filesystem JSON persistence for sessions and compiled skill packages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings


def skills_dir() -> Path:
    p = settings.data_dir / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_skill(skill_id: str, document: dict[str, Any]) -> Path:
    path = skills_dir() / f"{skill_id}.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_skill(skill_id: str) -> dict[str, Any] | None:
    path = skills_dir() / f"{skill_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_skill(skill_id: str) -> bool:
    path = skills_dir() / f"{skill_id}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def list_skill_summaries() -> list[dict[str, Any]]:
    """Return newest-first summaries for skills under ``data_dir/skills``."""
    out: list[dict[str, Any]] = []
    base = skills_dir()
    paths = [p for p in base.glob("*.json") if p.is_file()]
    paths.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in paths:
        skill_id = path.stem
        try:
            raw = path.read_text(encoding="utf-8")
            doc = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue
        meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
        skills_raw = doc.get("skills") or []
        block0 = skills_raw[0] if isinstance(skills_raw, list) and skills_raw and isinstance(skills_raw[0], dict) else {}
        steps = block0.get("steps") if isinstance(block0.get("steps"), list) else []
        n_steps = len(steps)
        out.append(
            {
                "skill_id": skill_id,
                "title": str(meta.get("title") or skill_id),
                "version": int(meta.get("version") or 1),
                "step_count": n_steps,
                "modified_at": path.stat().st_mtime,
            }
        )
    return out
