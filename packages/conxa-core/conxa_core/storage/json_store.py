"""Filesystem JSON persistence for sessions and compiled skill packages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conxa_core.config import settings
from conxa_core.db import db_get, db_set, db_delete, db_list


def skills_dir() -> Path:
    p = settings.data_dir / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_skill(skill_id: str, document: dict[str, Any]) -> Path:
    is_update = read_skill(skill_id) is not None
    db_set("skills", skill_id, document)
    path = skills_dir() / f"{skill_id}.json"
    try:
        json_str = json.dumps(document, indent=2, ensure_ascii=False)
        # Strip lone surrogates (Windows recording artifacts) to keep the file valid UTF-8
        json_str = json_str.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")
        path.write_text(json_str, encoding="utf-8")
    except OSError:
        pass
    if is_update:
        try:
            from conxa_core.storage.plugin_store import invalidate_workflow_test_by_skill  # noqa: PLC0415
            invalidate_workflow_test_by_skill(skill_id)
        except Exception:  # noqa: BLE001
            pass
    return path


def read_skill(skill_id: str) -> dict[str, Any] | None:
    data = db_get("skills", skill_id)
    if data is not None:
        return data
    path = skills_dir() / f"{skill_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_skill(skill_id: str) -> bool:
    db_delete("skills", skill_id)
    path = skills_dir() / f"{skill_id}.json"
    if path.is_file():
        path.unlink()
    return True


def list_skill_summaries() -> list[dict[str, Any]]:
    """Return newest-first summaries for skills."""
    db_items = db_list("skills")
    if db_items:
        out: list[dict[str, Any]] = []
        for doc in db_items:
            skill_id = doc.get("meta", {}).get("id") or ""
            meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
            skills_raw = doc.get("skills") or []
            block0 = skills_raw[0] if isinstance(skills_raw, list) and skills_raw and isinstance(skills_raw[0], dict) else {}
            steps = block0.get("steps") if isinstance(block0.get("steps"), list) else []
            out.append({
                "skill_id": skill_id,
                "title": str(meta.get("title") or skill_id),
                "version": int(meta.get("version") or 1),
                "step_count": len(steps),
                "modified_at": 0.0,
            })
        return list(reversed(out))
    # File fallback for local dev
    out = []
    base = skills_dir()
    paths = [p for p in base.glob("*.json") if p.is_file()]
    paths.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in paths:
        skill_id = path.stem
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
        skills_raw = doc.get("skills") or []
        block0 = skills_raw[0] if isinstance(skills_raw, list) and skills_raw and isinstance(skills_raw[0], dict) else {}
        steps = block0.get("steps") if isinstance(block0.get("steps"), list) else []
        out.append({
            "skill_id": skill_id,
            "title": str(meta.get("title") or skill_id),
            "version": int(meta.get("version") or 1),
            "step_count": len(steps),
            "modified_at": path.stat().st_mtime,
        })
    return out
