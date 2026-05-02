"""Filesystem persistence for generated skill_package folders."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

WORKFLOW_FILENAMES = (
    "skill.md",
    "execution.json",
    "recovery.json",
    "inputs.json",
    "manifest.json",
)
OBSOLETE_WORKFLOW_FILENAMES = (
    "skill.json",
    "execution.md",
    "execution_plan.json",
)
ENGINE_FILENAMES = (
    "execution.ts",
    "recovery.ts",
    "logging.ts",
    "config.ts",
)
INDEX_FILENAME = "index.json"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PACKAGE_DIRNAME = "skill_package"
VISUAL_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def skill_package_root_dir() -> Path:
    path = PROJECT_ROOT / SKILL_PACKAGE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def skill_package_readme(workflow_slug: str | None = None) -> str:
    """Markdown README for skill_package/: optional workflow_slug narrows paths for ZIP exports."""

    slug = (workflow_slug or "").strip()
    if slug:
        intro = (
            f"This archive includes workflow **`{slug}`** "
            f"(`skill_package/workflows/{slug}/`) and the shared TypeScript engine (`skill_package/engine/`)."
        )
        slug_literal = json.dumps(slug)
        inputs_note = (
            f"Adapt the `inputs` object keys to match `workflows/{slug}/inputs.json`."
        )
    else:
        intro = (
            "Bundled workflows live under `skill_package/workflows/` (one folder per slug). "
            "Where you see **`WORKFLOW_SLUG`**, substitute your workflow folder name (for example `delete_database`). "
            "The engine is copied to `skill_package/engine/`."
        )
        slug_literal = '"WORKFLOW_SLUG"  // rename to match workflows/* directory'
        inputs_note = (
            "Adapt `inputs` to the schema under `workflows/WORKFLOW_SLUG/inputs.json` for each run."
        )

    return f"""# Skill package

{intro}

## Layout

| Location | Purpose |
| --- | --- |
| `skill_package/workflows/` | One subdirectory per workflow (slug matches the folder name) |
| `skill_package/engine/` | Playwright executor, recovery, logging, configuration |
| `skill_package/index.json` | Discovery index for agents to choose a workflow before loading manifests |

Inside each workflow directory:

| File | Role |
| --- | --- |
| `skill.md` | Human-readable procedure |
| `execution.json` | Step plan (`navigate`, `fill`, `click`, `assert_visible`, ...) |
| `recovery.json` | Semantic fallbacks when a locator fails |
| `inputs.json` | Required runtime keys / schema |
| `manifest.json` | Package metadata |
| `visuals/` | Optional screenshots for steps |

## Prerequisites

- Node.js 18 or newer recommended
- Install Playwright in the host application and obtain a Browser `page` (see Playwright docs for your runner)

## Run

```ts
import {{ executeWorkflowForPrompt }} from "./skill_package/engine/execution"

const slug = {slug_literal}

await executeWorkflowForPrompt({{
  page,
  indexPath: "./skill_package/index.json",
  prompt: slug,
  inputs: {{
    user_email: "person@example.com",
  }},
}})
```

{inputs_note}

Placeholders embedded in plans use doubled curly braces around the variable name. For example:

```
{{{{user_email}}}}
```

Those values are substituted from the `inputs` object before execution.

## Execution behaviour

Agents start from `index.json`, load only the selected workflow `manifest.json`, validate `inputs.json` when declared, then execute `execution.json` directly. `README.md` and `skill.md` are documentation/fallback artifacts, not the normal execution source.

Steps are executed in order from `execution.json`. Waits are not implied; visibility guards appear only where the plan specifies `assert_visible`. Use `scroll` steps to reveal lazy-loaded regions: optionally `selector` (`scrollIntoViewIfNeeded`), and/or wheel movement via `delta_y` / `delta_x`.

## Recovery

If a step fails, the engine retries once on the primary locator, then tries alternates from `recovery.json` (text variants derived at package build time). Optional LLM assist is controlled in `skill_package/engine/config.ts` (disabled by default).
"""


def read_engine_files() -> dict[str, str]:
    source_dir = PROJECT_ROOT / "engine"
    return {
        filename: (source_dir / filename).read_text(encoding="utf-8")
        for filename in ENGINE_FILENAMES
        if (source_dir / filename).is_file()
    }


def _workflow_manifest_summary(path: Path) -> dict[str, str] | None:
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        return None
    description = ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if isinstance(manifest, dict):
        description = str(manifest.get("description") or "").strip()
    if not description:
        description = f"Run the {path.name.replace('_', ' ')} workflow."
    return {
        "name": path.name,
        "description": description,
        "manifest": f"/skills/{path.name}/manifest.json",
    }


def write_skill_package_index(root: Path | None = None) -> Path:
    package_root = root or skill_package_root_dir()
    workflows_root = package_root / "workflows"
    workflows_root.mkdir(parents=True, exist_ok=True)
    workflows: list[dict[str, str]] = []
    for path in sorted(workflows_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir():
            continue
        summary = _workflow_manifest_summary(path)
        if summary is not None:
            workflows.append(summary)
    index_path = package_root / INDEX_FILENAME
    index_path.write_text(
        json.dumps({"workflows": workflows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index_path


def ensure_skill_package_scaffold() -> Path:
    root = skill_package_root_dir()
    (root / "workflows").mkdir(parents=True, exist_ok=True)
    engine_dir = root / "engine"
    engine_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in read_engine_files().items():
        (engine_dir / filename).write_text(content, encoding="utf-8")
    (root / "README.md").write_text(skill_package_readme(), encoding="utf-8")
    write_skill_package_index(root)
    return root


def skill_packages_dir() -> Path:
    path = ensure_skill_package_scaffold() / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def skill_package_dir(package_name: str) -> Path:
    return skill_packages_dir() / package_name


def _clear_visual_assets(visuals_dir: Path) -> None:
    for child in visuals_dir.iterdir():
        if not child.is_file() or child.name.startswith("."):
            continue
        child.unlink()


def _read_visual_asset_bytes(workflow_dir: Path) -> dict[str, bytes]:
    visuals_dir = workflow_dir / "visuals"
    if not visuals_dir.is_dir():
        return {}
    out: dict[str, bytes] = {}
    for child in sorted(visuals_dir.iterdir()):
        if not child.is_file() or child.name.startswith("."):
            continue
        if child.suffix.lower() not in VISUAL_IMAGE_SUFFIXES:
            continue
        out[child.name] = child.read_bytes()
    return out


def read_skill_package_visual_asset_bytes(package_name: str) -> dict[str, bytes]:
    return _read_visual_asset_bytes(skill_package_dir(package_name))


def write_skill_package_files(
    package_name: str,
    files: dict[str, str],
    *,
    visual_assets: dict[str, bytes] | None = None,
) -> Path:
    ensure_skill_package_scaffold()
    path = skill_package_dir(package_name)
    path.mkdir(parents=True, exist_ok=True)
    visuals_dir = path / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    for filename in OBSOLETE_WORKFLOW_FILENAMES:
        stale_file = path / filename
        if stale_file.is_file():
            stale_file.unlink()
    for filename in WORKFLOW_FILENAMES:
        content = files.get(filename)
        if content is None:
            continue
        (path / filename).write_text(content, encoding="utf-8")
    _clear_visual_assets(visuals_dir)
    for filename, content in sorted((visual_assets or {}).items()):
        safe_name = Path(filename).name
        if not safe_name or safe_name.startswith("."):
            continue
        if Path(safe_name).suffix.lower() not in VISUAL_IMAGE_SUFFIXES:
            continue
        (visuals_dir / safe_name).write_bytes(content)
    write_skill_package_index()
    return path


def list_skill_package_summaries() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    paths: list[Path] = []
    seen: set[str] = set()
    for path in skill_packages_dir().iterdir():
        if not path.is_dir() or path.name in seen:
            continue
        seen.add(path.name)
        paths.append(path)
    paths.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in paths:
        present_files = [filename for filename in WORKFLOW_FILENAMES if (path / filename).is_file()]
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


def _read_visual_assets(workflow_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for filename, content in _read_visual_asset_bytes(workflow_dir).items():
        out[f"visuals/{filename}"] = base64.standard_b64encode(content).decode("ascii")
    return out


def read_skill_package_files(package_name: str) -> dict[str, str] | None:
    path = skill_package_dir(package_name)
    if not path.is_dir():
        return None
    root = ensure_skill_package_scaffold()
    out: dict[str, str] = {}
    readme_path = root / "README.md"
    if readme_path.is_file():
        out["README.md"] = readme_path.read_text(encoding="utf-8")
    index_path = root / INDEX_FILENAME
    if index_path.is_file():
        out[INDEX_FILENAME] = index_path.read_text(encoding="utf-8")
    engine_root = root / "engine"
    for filename in ENGINE_FILENAMES:
        engine_file = engine_root / filename
        if engine_file.is_file():
            out[f"engine/{filename}"] = engine_file.read_text(encoding="utf-8")
    for filename in WORKFLOW_FILENAMES:
        wf_path = path / filename
        if wf_path.is_file():
            out[filename] = wf_path.read_text(encoding="utf-8")
    out.update(_read_visual_assets(path))
    return out or None


def delete_skill_package(package_name: str) -> bool:
    path = skill_package_dir(package_name)
    if not path.is_dir():
        return False
    shutil.rmtree(path)
    write_skill_package_index()
    return True
