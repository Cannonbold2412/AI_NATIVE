"""Filesystem persistence for generated automation plugin bundles.

Layout (per bundle):

  output/skill_package/<bundle_slug>-plugin/
    <bundle_slug>.json           machine-readable plugin index
    README.md                    human-readable docs
    auth/
      auth.json                  authentication config
      credentials.example.json   credential template
    skills/
      <workflow_slug>/
        SKILL.md, manifest.json, execution.json, input.json, recovery.json
        visuals/  tests/
    orchestration/
      index.md, planner.md, schema.json
    execution/
      executor.js, recovery.js, tracker.js, validator.js
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app.services.skill_pack_build_log import (
    skill_pack_log_append,
    skill_pack_text_metrics,
)
from app.storage.skill_package_formatters import (
    format_auth_json_text,
    format_credentials_example_json_text,
    format_plugin_index_json as _format_plugin_index_json,
    format_plugin_readme_text as _format_plugin_readme_text,
    format_test_cases_stub_json_text,
    infer_auth_config,
)
from app.storage.skill_package_templates import (
    EXECUTOR_JS as _EXECUTOR_JS,
    ORCHESTRATION_SCHEMA_JSON as _ORCHESTRATION_SCHEMA_JSON,
    PACKAGE_JSON as _PACKAGE_JSON,
    RECOVERY_JS as _RECOVERY_JS,
    TRACKER_JS as _TRACKER_JS,
    VALIDATOR_JS as _VALIDATOR_JS,
    orchestration_index_md as _orchestration_index_md,
    orchestration_planner_md as _orchestration_planner_md,
)

WORKFLOW_FILENAMES = ("execution.json", "recovery.json", "input.json", "manifest.json")
OBSOLETE_WORKFLOW_FILENAMES = (
    "skill.md",
    "skill.json",
    "execution.md",
    "execution_plan.json",
    "inputs.json",
)

SKILLS_SUBDIR = "skills"
WORKFLOWS_SUBDIR = "workflows"  # kept for legacy migration only
RESERVED_WORKFLOW_FOLDER_NAMES = frozenset({"packages", SKILLS_SUBDIR, WORKFLOWS_SUBDIR})
RESERVED_PACKAGE_BUNDLE_ROOTS = frozenset({"packages"})
FIXED_PACKAGE_ROOT = Path("output") / "skill_package"

VISUAL_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
BUNDLE_ROOT_STATE_FILENAME = ".skill_bundle_root"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_RUNTIME_DIRS = ("auth", "orchestration", "execution")
BUNDLE_RUNTIME_FILES = (
    "auth/auth.json",
    "auth/credentials.example.json",
    "orchestration/index.md",
    "orchestration/planner.md",
    "orchestration/schema.json",
    "execution/executor.js",
    "execution/recovery.js",
    "execution/tracker.js",
    "execution/validator.js",
)
STALE_BUNDLE_DIRS = ("engine", "bridge", "claude", ".opencode", ".codex")

CONTAINER_LEGACY_NAMES = frozenset(
    {
        WORKFLOWS_SUBDIR,
        SKILLS_SUBDIR,
        "engine",
        "bridge",
        "index.json",
        "skill.json",
        "package.json",
        "index.js",
        "README.md",
        "install.js",
        "install.bat",
        "claude",
    }
)

RESERVED_BUNDLE_SLUGS = frozenset(
    {
        WORKFLOWS_SUBDIR,
        SKILLS_SUBDIR,
        "engine",
        "bridge",
        "packages",
    }
)

_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^a-zA-Z0-9]+")
_BUNDLE_INDEX_FILENAMES = ("README.md",)
_EXECUTION_RUNTIME_FILES = {
    "executor.js": _EXECUTOR_JS,
    "recovery.js": _RECOVERY_JS,
    "tracker.js": _TRACKER_JS,
    "validator.js": _VALIDATOR_JS,
}

# ──────────────────────────────────────────────────────────────────────────────
# Bundle helpers
# ──────────────────────────────────────────────────────────────────────────────


def _slugify_package_bundle_root_segment(raw: str) -> str:
    text = _CAMEL_BOUNDARY.sub(r"\1_\2", str(raw or "").strip())
    text = _NON_WORD.sub("_", text).strip("_").lower()
    if not text:
        return "skill_package"
    if text[0].isdigit():
        text = f"bundle_{text}"
    if text in RESERVED_PACKAGE_BUNDLE_ROOTS:
        return "skill_package"
    return text


def _persisted_package_bundle_root_slug() -> str | None:
    path = PROJECT_ROOT / BUNDLE_ROOT_STATE_FILENAME
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if validate_package_bundle_root_slug(raw):
        return raw
    return None


def validate_package_bundle_root_slug(name: str) -> bool:
    if not name or Path(name).name != name:
        return False
    if name in RESERVED_PACKAGE_BUNDLE_ROOTS:
        return False
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*", name))


def package_bundle_root_name() -> str:
    """POSIX path segment for the shared container (parent of bundle folders)."""
    return FIXED_PACKAGE_ROOT.as_posix()


def rename_package_bundle_root(new_slug: str) -> str:
    raise ValueError("Bundle root is fixed to output/skill_package.")


def skill_package_root_dir() -> Path:
    """Filesystem container holding one directory per skill package bundle."""
    path = PROJECT_ROOT / FIXED_PACKAGE_ROOT
    path.mkdir(parents=True, exist_ok=True)
    maybe_migrate_legacy_container_layout(path)
    return path


def _sanitize_segment(name: str) -> str:
    return Path(str(name or "").strip()).name


def validate_bundle_slug(name: str) -> bool:
    n = _sanitize_segment(name)
    if not n or not re.fullmatch(r"[a-z][a-z0-9_]*", n):
        return False
    if n in RESERVED_BUNDLE_SLUGS:
        return False
    return True


def _bundle_folder_name(slug: str) -> str:
    """On-disk directory name for a bundle: ``{slug}-plugin``."""
    return f"{slug}-plugin"


def _slug_from_folder_name(folder_name: str) -> str | None:
    """Reverse of _bundle_folder_name; returns slug or None if not a plugin folder."""
    if not folder_name.endswith("-plugin"):
        return None
    slug = folder_name[: -len("-plugin")]
    if not slug or not validate_bundle_slug(slug):
        return None
    return slug


def _write_execution_runtime_files(bundle_root: Path) -> None:
    execution_dir = bundle_root / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in _EXECUTION_RUNTIME_FILES.items():
        (execution_dir / filename).write_text(content, encoding="utf-8")
    (bundle_root / "package.json").write_text(_PACKAGE_JSON, encoding="utf-8")


def _container_has_nested_bundles(container: Path) -> bool:
    for p in container.iterdir():
        if not p.is_dir():
            continue
        # Detect new-layout plugin folders ({slug}-plugin with skills/ subdir)
        if p.name.endswith("-plugin") and (p / SKILLS_SUBDIR).is_dir():
            return True
        # Detect old-layout nested bundles
        if not p.name.endswith("-plugin") and p.name not in RESERVED_BUNDLE_SLUGS and p.name != "engine":
            if (p / WORKFLOWS_SUBDIR).is_dir():
                return True
    return False


def maybe_migrate_legacy_container_layout(container: Path) -> None:
    """Move flat ``container/workflows`` + ``container/engine`` into ``legacy`` once."""
    if not container.is_dir():
        return
    if _container_has_nested_bundles(container):
        return
    wf = container / WORKFLOWS_SUBDIR
    if not wf.is_dir():
        return
    if not any(p.is_dir() and _workflow_manifest_summary(p) is not None for p in wf.iterdir()):
        return
    legacy = container / "legacy"
    if legacy.exists():
        return
    legacy.mkdir(parents=True, exist_ok=True)
    for name in (WORKFLOWS_SUBDIR, "engine", "bridge", "claude"):
        src = container / name
        if src.exists():
            shutil.move(str(src), str(legacy / name))
    for fname in ("README.md", "index.json", "skill.json", "package.json", "index.js", "install.js", "install.bat"):
        src = container / fname
        if src.is_file():
            shutil.move(str(src), str(legacy / fname))


def bundle_root_dir(bundle_slug: str) -> Path | None:
    name = _sanitize_segment(bundle_slug)
    if not name or not validate_bundle_slug(name):
        return None
    return skill_package_root_dir() / _bundle_folder_name(name)


def ensure_bundle_scaffold(bundle_slug: str) -> Path:
    """Ensure ``<container>/<bundle>-plugin/`` exists with execution/, orchestration/, auth/, skills/."""
    name = _sanitize_segment(bundle_slug)
    if not name or not validate_bundle_slug(name):
        raise ValueError(f'Invalid bundle name "{bundle_slug}".')
    root = skill_package_root_dir() / _bundle_folder_name(name)
    root.mkdir(parents=True, exist_ok=True)

    (root / SKILLS_SUBDIR).mkdir(parents=True, exist_ok=True)
    for dirname in BUNDLE_RUNTIME_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)

    _write_execution_runtime_files(root)
    (root / "orchestration" / "schema.json").write_text(_ORCHESTRATION_SCHEMA_JSON + "\n", encoding="utf-8")
    _write_bundle_orchestration(root, name)

    for stale_dir in STALE_BUNDLE_DIRS:
        candidate = root / stale_dir
        if candidate.is_dir():
            shutil.rmtree(candidate)
    return root


def skill_package_root_posix(bundle_slug: str) -> str:
    return f"{package_bundle_root_name()}/{_bundle_folder_name(_sanitize_segment(bundle_slug))}"


def format_plugin_index_json(bundle_slug: str, skills: list[dict[str, str]]) -> str:
    return _format_plugin_index_json(_sanitize_segment(bundle_slug), skills)


def format_plugin_readme_text(bundle_slug: str, skills: list[dict[str, str]]) -> str:
    return _format_plugin_readme_text(_sanitize_segment(bundle_slug), skills)


# ──────────────────────────────────────────────────────────────────────────────
# Internal skill discovery helpers
# ──────────────────────────────────────────────────────────────────────────────


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
        "manifest": f"skills/{path.name}/manifest.json",
    }


def _workflow_package_dirs(bundle_root: Path) -> list[Path]:
    return [path for path, _summary in _workflow_package_entries(bundle_root)]


def _workflow_package_entries(bundle_root: Path) -> list[tuple[Path, dict[str, str]]]:
    by_name: dict[str, tuple[Path, dict[str, str]]] = {}
    skills_parent = bundle_root / SKILLS_SUBDIR
    if skills_parent.is_dir():
        for path in skills_parent.iterdir():
            if not path.is_dir():
                continue
            summary = _workflow_manifest_summary(path)
            if summary is not None:
                by_name[path.name] = (path, summary)
    return [by_name[key] for key in sorted(by_name)]


def _workflow_summaries(bundle_root: Path) -> list[dict[str, str]]:
    return [summary for _path, summary in _workflow_package_entries(bundle_root)]


def _all_inputs_for_bundle(bundle_root: Path) -> list[dict[str, str]]:
    """Aggregate all inputs across all skills in a bundle (for auth inference)."""
    all_inputs: list[dict[str, str]] = []
    for skill_dir in _workflow_package_dirs(bundle_root):
        input_path = skill_dir / "input.json"
        if not input_path.is_file():
            continue
        try:
            data = json.loads(input_path.read_text(encoding="utf-8"))
            raw = data.get("inputs") if isinstance(data, dict) else data
            if isinstance(raw, list):
                all_inputs.extend(item for item in raw if isinstance(item, dict))
        except (OSError, json.JSONDecodeError):
            pass
    return all_inputs


def _write_bundle_index(bundle_root: Path, bundle_slug: str) -> None:
    skills = _workflow_summaries(bundle_root)
    (bundle_root / f"{_sanitize_segment(bundle_slug)}.json").write_text(
        format_plugin_index_json(bundle_slug, skills), encoding="utf-8"
    )
    (bundle_root / "README.md").write_text(
        format_plugin_readme_text(bundle_slug, skills), encoding="utf-8"
    )
    # Auth files
    all_inputs = _all_inputs_for_bundle(bundle_root)
    auth_dict = infer_auth_config(all_inputs)
    sensitive = [i for i in all_inputs if i.get("sensitive")]
    auth_dir = bundle_root / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "auth.json").write_text(format_auth_json_text(auth_dict), encoding="utf-8")
    (auth_dir / "credentials.example.json").write_text(
        format_credentials_example_json_text(sensitive), encoding="utf-8"
    )


def _write_bundle_orchestration(bundle_root: Path, bundle_slug: str) -> None:
    skills = _workflow_summaries(bundle_root)
    skill_names = [s["name"] for s in skills]
    plugin_name = _sanitize_segment(bundle_slug).replace("_", " ").title()
    orch_dir = bundle_root / "orchestration"
    orch_dir.mkdir(parents=True, exist_ok=True)
    (orch_dir / "index.md").write_text(
        _orchestration_index_md(plugin_name, bundle_slug, skill_names), encoding="utf-8"
    )
    (orch_dir / "planner.md").write_text(
        _orchestration_planner_md(bundle_slug), encoding="utf-8"
    )
    (orch_dir / "schema.json").write_text(_ORCHESTRATION_SCHEMA_JSON + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Workflow dir resolution
# ──────────────────────────────────────────────────────────────────────────────


def resolve_workflow_dir(bundle_slug: str, workflow_slug: str) -> Path | None:
    """Return skills/<workflow_slug>/ under the bundle, or None if not found."""
    br = bundle_root_dir(bundle_slug)
    if br is None or not br.is_dir():
        return None
    name = _sanitize_segment(workflow_slug)
    if not name:
        return None
    canonical = br / SKILLS_SUBDIR / name
    if canonical.is_dir():
        return canonical
    return None


def skill_package_dir(bundle_slug: str, workflow_slug: str) -> Path:
    """Canonical path for skills/<workflow_slug>/ (creates scaffold)."""
    root = ensure_bundle_scaffold(bundle_slug)
    return root / SKILLS_SUBDIR / _sanitize_segment(workflow_slug)


# ──────────────────────────────────────────────────────────────────────────────
# Visual asset helpers
# ──────────────────────────────────────────────────────────────────────────────


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


def read_skill_package_visual_asset_bytes(bundle_slug: str, workflow_slug: str) -> dict[str, bytes]:
    path = resolve_workflow_dir(bundle_slug, workflow_slug)
    if path is None:
        return {}
    return _read_visual_asset_bytes(path)


def _sanitize_bundle_relative_path(rel: str) -> str | None:
    """Return a safe relative path under a bundle or workflow folder, or None if unsafe."""
    raw = str(rel or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        return None
    parts: list[str] = []
    for segment in Path(raw).parts:
        seg = str(segment).strip()
        if not seg or seg == "." or seg == "..":
            return None
        if seg.startswith("."):
            pass  # Allow hidden roots like .opencode/skills/name/SKILL.md
        parts.append(seg)
    if not parts:
        return None
    return str(Path(*parts).as_posix())


def _log_written_text_file(path: str, content: str, started_at: float) -> None:
    skill_pack_log_append(
        {
            "kind": "file_written",
            "path": path,
            **skill_pack_text_metrics(content),
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    )


def _log_written_binary_file(path: str, content: bytes, started_at: float) -> None:
    skill_pack_log_append(
        {
            "kind": "file_written",
            "path": path,
            "bytes": len(content),
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _remove_file_if_present(path: Path) -> None:
    if path.is_file():
        path.unlink()


def _remove_obsolete_workflow_files(workflow_dir: Path) -> None:
    for filename in OBSOLETE_WORKFLOW_FILENAMES:
        _remove_file_if_present(workflow_dir / filename)


def _write_workflow_text_files(
    workflow_dir: Path,
    files: dict[str, str],
    *,
    log_prefix: str,
) -> None:
    for filename, content in sorted(files.items()):
        if content is None:
            continue
        destination = workflow_dir / filename
        started_at = time.perf_counter()
        _write_text(destination, content)
        _log_written_text_file(f"{log_prefix}/{filename}", content, started_at)


def _workflow_has_visual_assets(visuals_dir: Path) -> bool:
    return any(
        child.is_file() and not child.name.startswith(".") and child.suffix.lower() in VISUAL_IMAGE_SUFFIXES
        for child in visuals_dir.iterdir()
    )


def _write_workflow_visual_assets(
    visuals_dir: Path,
    visual_assets: dict[str, bytes] | None,
    *,
    log_prefix: str,
) -> None:
    if _workflow_has_visual_assets(visuals_dir):
        return

    for filename, content in sorted((visual_assets or {}).items()):
        safe_name = Path(filename).name
        if not safe_name or safe_name.startswith("."):
            continue
        if Path(safe_name).suffix.lower() not in VISUAL_IMAGE_SUFFIXES:
            continue

        destination = visuals_dir / safe_name
        if destination.exists():
            continue

        started_at = time.perf_counter()
        destination.write_bytes(content)
        _log_written_binary_file(f"{log_prefix}/visuals/{safe_name}", content, started_at)


def _write_extra_bundle_files(
    bundle_root: Path | None,
    extra_bundle_files: dict[str, str] | None,
    *,
    log_prefix: str,
) -> None:
    if bundle_root is None:
        return

    for relative_path, content in sorted((extra_bundle_files or {}).items()):
        safe_relative_path = _sanitize_bundle_relative_path(relative_path)
        if safe_relative_path is None:
            continue

        destination = bundle_root / safe_relative_path
        try:
            destination.relative_to(bundle_root)
        except ValueError:
            continue

        started_at = time.perf_counter()
        _write_text(destination, content)
        _log_written_text_file(f"{log_prefix}/{safe_relative_path}", content, started_at)


def _refresh_bundle_artifacts(bundle_slug: str, bundle_root: Path, bundle_posix: str) -> None:
    started_at = time.perf_counter()
    _write_bundle_index(bundle_root, bundle_slug)
    skill_pack_log_append(
        {
            "kind": "bundle_artifact_updated",
            "path": f"{bundle_posix}/{_sanitize_segment(bundle_slug)}.json",
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    )

    started_at = time.perf_counter()
    _write_bundle_orchestration(bundle_root, bundle_slug)
    skill_pack_log_append(
        {
            "kind": "bundle_artifact_updated",
            "path": f"{bundle_posix}/orchestration/index.md",
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    )


def _refresh_bundle_artifacts_for_slug(bundle_slug: str, bundle_root: Path) -> None:
    _refresh_bundle_artifacts(bundle_slug, bundle_root, skill_package_root_posix(bundle_slug))


# ──────────────────────────────────────────────────────────────────────────────
# Write lock
# ──────────────────────────────────────────────────────────────────────────────

_bundle_write_locks: dict[str, threading.Lock] = {}
_bundle_write_lock_registry = threading.Lock()


@contextmanager
def _bundle_write_lock(bundle_slug: str):
    """Serialize filesystem updates that rebuild bundle index for one bundle."""
    key = _sanitize_segment(bundle_slug)
    with _bundle_write_lock_registry:
        lock = _bundle_write_locks.setdefault(key, threading.Lock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


# ──────────────────────────────────────────────────────────────────────────────
# Core write
# ──────────────────────────────────────────────────────────────────────────────


def _write_skill_package_files_core(
    bundle_slug: str,
    workflow_slug: str,
    files: dict[str, str],
    *,
    visual_assets: dict[str, bytes] | None = None,
    extra_bundle_files: dict[str, str] | None = None,
) -> Path:
    bundle_root = ensure_bundle_scaffold(bundle_slug)
    workflow_name = _sanitize_segment(workflow_slug)
    if not workflow_name:
        raise ValueError("Invalid workflow folder name.")
    bundle_posix = skill_package_root_posix(bundle_slug)
    workflow_dir = bundle_root / SKILLS_SUBDIR / workflow_name
    workflow_dir.mkdir(parents=True, exist_ok=True)

    visuals_dir = workflow_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "tests").mkdir(parents=True, exist_ok=True)

    workflow_log_prefix = f"{bundle_posix}/skills/{workflow_name}"
    _remove_obsolete_workflow_files(workflow_dir)
    _write_workflow_text_files(workflow_dir, files, log_prefix=workflow_log_prefix)
    _write_workflow_visual_assets(visuals_dir, visual_assets, log_prefix=workflow_log_prefix)
    _write_extra_bundle_files(bundle_root, extra_bundle_files, log_prefix=bundle_posix)
    _refresh_bundle_artifacts_for_slug(bundle_slug, bundle_root)
    return workflow_dir


def write_skill_package_files(
    bundle_slug: str,
    workflow_slug: str,
    files: dict[str, str],
    *,
    visual_assets: dict[str, bytes] | None = None,
    extra_bundle_files: dict[str, str] | None = None,
) -> Path:
    with _bundle_write_lock(bundle_slug):
        return _write_skill_package_files_core(
            bundle_slug,
            workflow_slug,
            files,
            visual_assets=visual_assets,
            extra_bundle_files=extra_bundle_files,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Display / label helpers
# ──────────────────────────────────────────────────────────────────────────────


def _auto_manifest_fallback_description(workflow_slug: str) -> str:
    return f"Run the {workflow_slug.replace('_', ' ')} workflow."


def _workflow_folder_display_label(package_dir: Path, workflow_slug: str) -> str:
    manifest_path = package_dir / "manifest.json"
    manifest_desc = ""
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_desc = str(data.get("description") or "").strip()
        except (json.JSONDecodeError, OSError):
            manifest_desc = ""
    auto = _auto_manifest_fallback_description(workflow_slug)
    if manifest_desc and manifest_desc != auto:
        return manifest_desc
    skill_path = package_dir / "SKILL.md"
    if skill_path.is_file():
        try:
            lines = skill_path.read_text(encoding="utf-8").splitlines()
            first = lines[0].strip() if lines else ""
            if first.startswith("#"):
                cand = first.lstrip("#").strip()
                if cand and cand.replace(" ", "_") != workflow_slug and cand != workflow_slug:
                    return cand
        except OSError:
            pass
    return workflow_slug


def _bundle_has_workflows(bundle_root: Path) -> bool:
    return bool(_workflow_package_entries(bundle_root))


def _bundle_runtime_file_keys(bundle_slug: str) -> list[str]:
    return [f"{_sanitize_segment(bundle_slug)}.json", "README.md", *BUNDLE_RUNTIME_FILES]


def _read_text_file_if_present(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _read_bundle_runtime_files(bundle_root: Path, bundle_slug: str) -> dict[str, str]:
    files: dict[str, str] = {}

    for filename in (f"{_sanitize_segment(bundle_slug)}.json", *_BUNDLE_INDEX_FILENAMES):
        content = _read_text_file_if_present(bundle_root / filename)
        if content is not None:
            files[filename] = content

    for dirname in BUNDLE_RUNTIME_DIRS:
        directory = bundle_root / dirname
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                files[f"{dirname}/{path.name}"] = path.read_text(encoding="utf-8")

    return files


def _read_workflow_text_files(workflow_dir: Path, *, prefix: str = "") -> dict[str, str]:
    files: dict[str, str] = {}
    for filename in WORKFLOW_FILENAMES:
        content = _read_text_file_if_present(workflow_dir / filename)
        if content is not None:
            files[f"{prefix}{filename}"] = content

    skill_md = _read_text_file_if_present(workflow_dir / "SKILL.md")
    if skill_md is not None:
        files[f"{prefix}SKILL.md"] = skill_md

    test_cases = _read_text_file_if_present(workflow_dir / "tests" / "test-cases.json")
    if test_cases is not None:
        files[f"{prefix}tests/test-cases.json"] = test_cases
    return files


def _workflow_present_files(workflow_dir: Path) -> list[str]:
    return [filename for filename in WORKFLOW_FILENAMES if (workflow_dir / filename).is_file()]


def _workflow_extra_file_keys(bundle_root: Path, workflow_slug: str) -> list[str]:
    workflow_dir = bundle_root / SKILLS_SUBDIR / workflow_slug
    return [
        f"{SKILLS_SUBDIR}/{workflow_slug}/{extra}"
        for extra in ("SKILL.md", "tests/test-cases.json")
        if (workflow_dir / extra).is_file()
    ]


def _workflow_listing_metadata(workflow_dir: Path) -> dict[str, object]:
    workflow_slug = workflow_dir.name
    return {
        "workflow_slug": workflow_slug,
        "display_label": _workflow_folder_display_label(workflow_dir, workflow_slug),
        "modified_at": workflow_dir.stat().st_mtime,
        "files": _workflow_present_files(workflow_dir),
    }


def _bundle_file_keys(bundle_root: Path, bundle_slug: str, workflows_meta: list[dict[str, object]]) -> list[str]:
    file_keys = _bundle_runtime_file_keys(bundle_slug)
    for workflow_meta in workflows_meta:
        workflow_slug = str(workflow_meta["workflow_slug"])
        for filename in workflow_meta["files"]:  # type: ignore[arg-type]
            file_keys.append(f"{SKILLS_SUBDIR}/{workflow_slug}/{filename}")
        file_keys.extend(_workflow_extra_file_keys(bundle_root, workflow_slug))
    return file_keys


# ──────────────────────────────────────────────────────────────────────────────
# List / read (API-facing)
# ──────────────────────────────────────────────────────────────────────────────


def list_skill_bundle_summaries() -> list[dict[str, object]]:
    """One entry per bundle directory under the container."""
    container = skill_package_root_dir()
    out: list[dict[str, object]] = []
    for path in sorted(container.iterdir(), key=lambda p: p.name):
        if not path.is_dir():
            continue
        slug = _slug_from_folder_name(path.name)
        if slug is None:
            continue
        workflow_entries = _workflow_package_entries(path)
        if not workflow_entries:
            continue
        workflow_paths = [workflow_path for workflow_path, _summary in workflow_entries]
        workflow_paths.sort(key=lambda wp: wp.stat().st_mtime_ns, reverse=True)
        max_mtime = max(wp.stat().st_mtime for wp in workflow_paths)
        workflows_meta = [_workflow_listing_metadata(wp) for wp in workflow_paths]
        out.append(
            {
                "package_name": slug,
                "modified_at": max_mtime,
                "workflows": workflows_meta,
                "files": _bundle_file_keys(path, slug, workflows_meta),
            }
        )
    out.sort(key=lambda row: float(row["modified_at"]), reverse=True)
    return out


def list_skill_package_summaries() -> list[dict[str, object]]:
    """Backward-compatible alias: returns bundle summaries (not per-workflow rows)."""
    return list_skill_bundle_summaries()


def _read_visual_assets(workflow_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for filename, content in _read_visual_asset_bytes(workflow_dir).items():
        out[f"visuals/{filename}"] = base64.standard_b64encode(content).decode("ascii")
    return out


def read_skill_package_bundle_files(bundle_slug: str) -> dict[str, str] | None:
    """Flatten bundle tree: skills/<wf>/<file>, execution/*, orchestration/*, auth/*, index files."""
    root = bundle_root_dir(bundle_slug)
    if root is None or not root.is_dir():
        return None

    out = _read_bundle_runtime_files(root, bundle_slug)
    for wf_path in _workflow_package_dirs(root):
        wf_name = wf_path.name
        prefix = f"{SKILLS_SUBDIR}/{wf_name}/"
        out.update(_read_workflow_text_files(wf_path, prefix=prefix))
        for vk, vv in _read_visual_assets(wf_path).items():
            out[prefix + vk] = vv

    return out or None


def read_skill_package_files(bundle_slug: str, workflow_slug: str) -> dict[str, str] | None:
    """Single-workflow overlay: bundle runtime files plus unprefixed workflow files + visuals/."""
    root = bundle_root_dir(bundle_slug)
    if root is None or not root.is_dir():
        return None
    wf_dir = resolve_workflow_dir(bundle_slug, workflow_slug)
    if wf_dir is None:
        return None

    out = _read_bundle_runtime_files(root, bundle_slug)
    out.update(_read_workflow_text_files(wf_dir))
    out.update(_read_visual_assets(wf_dir))
    return out or None


# ──────────────────────────────────────────────────────────────────────────────
# CRUD operations
# ──────────────────────────────────────────────────────────────────────────────


def delete_skill_package_bundle(bundle_slug: str) -> bool:
    root = bundle_root_dir(bundle_slug)
    if root is None or not root.is_dir():
        return False
    shutil.rmtree(root)
    return True


def rename_skill_package_bundle(old_slug: str, new_slug: str) -> None:
    old = _sanitize_segment(old_slug)
    new = _sanitize_segment(new_slug)
    if old != old_slug or new != new_slug or not old or not new:
        raise ValueError("Invalid bundle name.")
    if not validate_bundle_slug(new):
        raise ValueError(f'Invalid bundle name "{new_slug}".')
    if old == new:
        return
    old_root = bundle_root_dir(old)
    if old_root is None or not old_root.is_dir():
        raise FileNotFoundError(old_slug)
    new_root = skill_package_root_dir() / _bundle_folder_name(new)
    if new_root.exists():
        raise ValueError(f'A skill package named "{new}" already exists.')
    old_root.rename(new_root)
    _remove_file_if_present(new_root / f"{old}.json")
    with _bundle_write_lock(new):
        _refresh_bundle_artifacts_for_slug(new, new_root)


def delete_skill_package_workflow(bundle_slug: str, workflow_slug: str) -> bool:
    path = resolve_workflow_dir(bundle_slug, workflow_slug)
    if path is None or not path.is_dir():
        return False
    shutil.rmtree(path)
    root = bundle_root_dir(bundle_slug)
    if root and root.is_dir():
        with _bundle_write_lock(bundle_slug):
            _refresh_bundle_artifacts_for_slug(bundle_slug, root)
    return True


def rename_skill_package_workflow(bundle_slug: str, old_workflow: str, new_workflow: str) -> None:
    old = _sanitize_segment(old_workflow)
    new_s = _sanitize_segment(new_workflow)
    if old != old_workflow or new_s != new_workflow or not old or not new_s:
        raise ValueError("Invalid workflow folder name.")
    if new_s in RESERVED_WORKFLOW_FOLDER_NAMES:
        raise ValueError(f'Reserved name "{new_workflow}" cannot be used.')
    if old == new_s:
        return
    ensure_bundle_scaffold(bundle_slug)
    old_path = resolve_workflow_dir(bundle_slug, old)
    if old_path is None or not old_path.is_dir():
        raise FileNotFoundError(old_workflow)
    new_parent = (bundle_root_dir(bundle_slug) or Path()) / SKILLS_SUBDIR
    new_path = new_parent / new_s
    if new_path.exists():
        raise ValueError(f'A workflow folder named "{new_s}" already exists.')
    old_path.rename(new_path)
    manifest_path = new_path / "manifest.json"
    if manifest_path.is_file():
        try:
            parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            parsed["name"] = new_s
            manifest_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    root = bundle_root_dir(bundle_slug)
    if root:
        with _bundle_write_lock(bundle_slug):
            _refresh_bundle_artifacts_for_slug(bundle_slug, root)
