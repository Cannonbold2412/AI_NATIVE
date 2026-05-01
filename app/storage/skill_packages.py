"""Filesystem persistence for generated skill-package folders."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings

PACKAGE_FILENAMES = ("skill.md", "skill.json", "inputs.json", "manifest.json")
LEGACY_PACKAGE_FILENAMES = ("input.json",)


def skill_packages_dir() -> Path:
    path = settings.data_dir / "skill_packages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def skill_package_dir(package_name: str) -> Path:
    return skill_packages_dir() / package_name


def write_skill_package_files(package_name: str, files: dict[str, str]) -> Path:
    path = skill_package_dir(package_name)
    path.mkdir(parents=True, exist_ok=True)
    for filename in PACKAGE_FILENAMES:
        content = files.get(filename)
        if content is None:
            continue
        (path / filename).write_text(content, encoding="utf-8")
    return path


def list_skill_package_summaries() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    base = skill_packages_dir()
    paths = [path for path in base.iterdir() if path.is_dir()]
    paths.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in paths:
        present_files = [filename for filename in PACKAGE_FILENAMES if (path / filename).is_file()]
        if "inputs.json" not in present_files and (path / "input.json").is_file():
            present_files.append("input.json")
        if not present_files:
            continue
        out.append(
            {
                "package_name": path.name,
                "modified_at": path.stat().st_mtime,
                "files": present_files,
            }
        )
    return out


def read_skill_package_files(package_name: str) -> dict[str, str] | None:
    path = skill_package_dir(package_name)
    if not path.is_dir():
        return None
    out: dict[str, str] = {}
    for filename in PACKAGE_FILENAMES:
        file_path = path / filename
        if file_path.is_file():
            out[filename] = file_path.read_text(encoding="utf-8")
    if "inputs.json" not in out:
        legacy_file = path / "input.json"
        if legacy_file.is_file():
            out["inputs.json"] = legacy_file.read_text(encoding="utf-8")
    return out or None


def delete_skill_package(package_name: str) -> bool:
    path = skill_package_dir(package_name)
    if not path.is_dir():
        return False
    shutil.rmtree(path)
    return True
