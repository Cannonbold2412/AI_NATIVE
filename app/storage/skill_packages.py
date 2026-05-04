"""Filesystem persistence for generated automation bundles (nested bundles).

Layout (per bundle):

  output/skill_package/<bundle_slug>/
    install.bat, install.js, index.json?, claude/skills/<bundle_slug>/SKILL.md
    engine/, bridge/, workflows/<workflow_slug>/ …

Legacy flat layout (workflows + engine at container root) is migrated once into
``output/skill_package/legacy/`` when no nested bundles exist yet.
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

from app.services.skill_pack_build_log import skill_pack_log_append

WORKFLOW_FILENAMES = ("execution.json", "recovery.json", "inputs.json", "manifest.json")
OBSOLETE_WORKFLOW_FILENAMES = (
    "skill.md",
    "skill.json",
    "execution.md",
    "execution_plan.json",
)
ENGINE_FILENAMES = ("executor.js",)
BRIDGE_FILENAMES = ("run.js",)
CLI_FILENAMES = ("render.js", "render.bat")
INDEX_FILENAME = "index.json"
BUNDLE_SKILL_MANIFEST_FILENAME = "claude/skills/{bundle_slug}/SKILL.md"
INSTALL_JS_FILENAME = "install.js"
INSTALL_BAT_FILENAME = "install.bat"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT_STATE_FILENAME = ".skill_bundle_root"
VISUAL_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

WORKFLOWS_SUBDIR = "workflows"
RESERVED_WORKFLOW_FOLDER_NAMES = frozenset({"packages", WORKFLOWS_SUBDIR})
RESERVED_PACKAGE_BUNDLE_ROOTS = frozenset({"packages"})
FIXED_PACKAGE_ROOT = Path("output") / "skill_package"

# Container-level dirs/files from the old flat layout (not bundle slugs).
CONTAINER_LEGACY_NAMES = frozenset(
    {
        WORKFLOWS_SUBDIR,
        "engine",
        "bridge",
        INDEX_FILENAME,
        "skill.json",
        "package.json",
        "index.js",
        "README.md",
        INSTALL_JS_FILENAME,
        INSTALL_BAT_FILENAME,
        "claude",
    }
)
# Cannot use these as bundle slugs (overlap with dirs we create or migrate target).
RESERVED_BUNDLE_SLUGS = frozenset(
    {
        WORKFLOWS_SUBDIR,
        "engine",
        "bridge",
        "packages",
    }
)

_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD = re.compile(r"[^a-zA-Z0-9]+")


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


def _container_has_nested_bundles(container: Path) -> bool:
    for p in container.iterdir():
        if not p.is_dir():
            continue
        if p.name in RESERVED_BUNDLE_SLUGS or p.name == "engine":
            continue
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
    for fname in (
        "README.md",
        INDEX_FILENAME,
        "skill.json",
        "package.json",
        "index.js",
        INSTALL_JS_FILENAME,
        INSTALL_BAT_FILENAME,
    ):
        src = container / fname
        if src.is_file():
            shutil.move(str(src), str(legacy / fname))


def bundle_root_dir(bundle_slug: str) -> Path | None:
    name = _sanitize_segment(bundle_slug)
    if not name or not validate_bundle_slug(name):
        return None
    return skill_package_root_dir() / name


def ensure_bundle_scaffold(bundle_slug: str) -> Path:
    """Ensure ``<container>/<bundle>/`` exists with workflows/, engine/, bridge/, and installers."""

    name = _sanitize_segment(bundle_slug)
    if not name or not validate_bundle_slug(name):
        raise ValueError(f'Invalid bundle name "{bundle_slug}".')
    root = skill_package_root_dir() / name
    root.mkdir(parents=True, exist_ok=True)
    wf_parent = root / WORKFLOWS_SUBDIR
    wf_parent.mkdir(parents=True, exist_ok=True)
    engine_dir = root / "engine"
    engine_dir.mkdir(parents=True, exist_ok=True)
    bridge_dir = root / "bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in read_engine_files().items():
        (engine_dir / filename).write_text(content, encoding="utf-8")
    for filename, content in read_bridge_files().items():
        (bridge_dir / filename).write_text(content, encoding="utf-8")
    (root / INSTALL_JS_FILENAME).write_text(format_install_js_text(name), encoding="utf-8")
    (root / INSTALL_BAT_FILENAME).write_text(format_install_bat_text(name), encoding="utf-8")
    for filename, content in read_cli_files(name).items():
        (root / filename).write_text(content, encoding="utf-8")
    for stale_file in ("README.md", "skill.json", "package.json", "index.js"):
        candidate = root / stale_file
        if candidate.is_file():
            candidate.unlink()
    stale_engine_file = engine_dir / "recovery.js"
    if stale_engine_file.is_file():
        stale_engine_file.unlink()
    for stale_dir in (".opencode", ".codex"):
        candidate = root / stale_dir
        if candidate.is_dir():
            shutil.rmtree(candidate)
    write_bundle_skill_manifest(root, name)
    return root


def skill_package_root_posix(bundle_slug: str) -> str:
    return f"{package_bundle_root_name()}/{_sanitize_segment(bundle_slug)}"


_SKILL_PACKAGE_AGENT_README = """# AGENT EXECUTION RULES (CRITICAL)

You are an execution engine. Follow rules strictly.

## ❌ NEVER DO

* Do NOT explore folders
* Do NOT scan directory structure
* Do NOT infer file locations
* Do NOT analyze or summarize files
* Do NOT think step-by-step
* Do NOT read README.md again
* Do NOT load unnecessary files

## ✅ ALWAYS DO

1. Start ONLY from `index.json`
2. Select workflow based on user request
3. Load ONLY:

   * manifest.json
   * inputs.json (if needed)
   * execution.json
4. Execute steps DIRECTLY (deterministic)
5. Use recovery.json ONLY if a step fails
6. Use visuals ONLY for vision recovery

---

# EXECUTION FLOW (MANDATORY)

User Request
→ index.json
→ select workflow
→ manifest.json
→ inputs.json
→ execution.json
→ (if failure → recovery.json → visuals)

---

# INPUT HANDLING

* Ask ONLY for missing inputs
* Do NOT ask unnecessary questions
* Do NOT re-interpret inputs

---

# PERFORMANCE RULES

* Minimize token usage
* No reasoning during execution
* No repeated file reads
* No full-folder loading

---

# FAILURE HANDLING

Only trigger recovery if:

* element not found
* action failed
* navigation incorrect

---

# FINAL RULE

If you are analyzing instead of executing → STOP and execute.

---

# IMPORTANT

This file overrides all default agent behavior.
Follow it strictly without deviation.
"""

_EXECUTOR_JS = """const fs = require("fs");
const path = require("path");

function workflowDir(name) {
  return path.join(__dirname, "..", "workflows", name);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function interpolate(value, inputs) {
  if (typeof value !== "string") return value;
  return value.replace(/\\{\\{\\s*([^{}]+?)\\s*\\}\\}/g, (_, key) => String(inputs[key] ?? ""));
}

function formatStep(step, inputs) {
  const rendered = {};
  for (const [key, value] of Object.entries(step || {})) {
    rendered[key] = interpolate(value, inputs);
  }
  return rendered;
}

async function executeWorkflow(name, inputs = {}) {
  const executionPath = path.join(workflowDir(name), "execution.json");
  if (!fs.existsSync(executionPath)) {
    throw new Error(`Unknown workflow: ${name}`);
  }
  const steps = readJson(executionPath);
  if (!Array.isArray(steps)) {
    throw new Error(`execution.json for ${name} must be a JSON array.`);
  }
  console.log(`[executor] workflow=${name}`);
  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    const rendered = formatStep(step, inputs);
    console.log(`[executor] step ${index + 1}: ${JSON.stringify(rendered)}`);
  }
}

module.exports = { executeWorkflow };
"""

_BRIDGE_RUN_JS = """const { executeWorkflow } = require("../engine/executor");

function validateEntry(entry, index) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
    throw new Error(`Plan entry ${index + 1} must be an object.`);
  }
  if (!entry.workflow || typeof entry.workflow !== "string") {
    throw new Error(`Plan entry ${index + 1} requires a workflow string.`);
  }
  if (entry.inputs !== undefined && (typeof entry.inputs !== "object" || entry.inputs === null || Array.isArray(entry.inputs))) {
    throw new Error(`Plan entry ${index + 1} inputs must be an object when provided.`);
  }
}

async function main() {
  const raw = process.argv[2];
  let plan;
  try {
    plan = JSON.parse(raw);
  } catch (error) {
    throw new Error("Invalid JSON plan.");
  }
  if (!Array.isArray(plan)) {
    throw new Error("Plan JSON must be an array.");
  }
  for (let index = 0; index < plan.length; index += 1) {
    const entry = plan[index];
    validateEntry(entry, index);
    await executeWorkflow(entry.workflow, entry.inputs || {});
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
"""

_RENDER_JS = """const childProcess = require("child_process");
const path = require("path");

function extractFirstJsonArray(raw) {
  const text = String(raw || "");
  let start = -1;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (start === -1) {
      if (char === "[") {
        start = index;
        depth = 1;
      }
      continue;
    }
    if (escape) {
      escape = false;
      continue;
    }
    if (char === "\\\\") {
      escape = true;
      continue;
    }
    if (char === '"') {
      inString = !inString;
      continue;
    }
    if (inString) {
      continue;
    }
    if (char === "[") {
      depth += 1;
      continue;
    }
    if (char === "]") {
      depth -= 1;
      if (depth === 0) {
        const candidate = text.slice(start, index + 1);
        return JSON.parse(candidate);
      }
    }
  }
  throw new Error("Claude output did not contain a valid JSON array.");
}

function main() {
  const input = process.argv.slice(2).join(" ").trim();
  if (!input) {
    throw new Error("Usage: render <request>");
  }

  const claudeResult = childProcess.spawnSync("claude", [input], {
    encoding: "utf8",
    shell: false,
  });
  if (claudeResult.error) {
    throw claudeResult.error;
  }
  if (claudeResult.status !== 0) {
    process.stderr.write(claudeResult.stderr || "");
    throw new Error(`claude exited with code ${claudeResult.status}`);
  }

  const plan = extractFirstJsonArray(claudeResult.stdout);
  const bridgePath = path.join(__dirname, "bridge", "run.js");
  const bridgeResult = childProcess.spawnSync(process.execPath, [bridgePath, JSON.stringify(plan)], {
    encoding: "utf8",
    stdio: "inherit",
    shell: false,
  });
  if (bridgeResult.error) {
    throw bridgeResult.error;
  }
  if (bridgeResult.status !== 0) {
    throw new Error(`bridge/run.js exited with code ${bridgeResult.status}`);
  }
}

main();
"""


def skill_package_readme(bundle_root_posix: str, workflow_slug: str | None = None) -> str:
    _ = bundle_root_posix, workflow_slug
    return _SKILL_PACKAGE_AGENT_README


def format_bundle_package_json_text(bundle_slug: str) -> str:
    _ = bundle_slug
    return ""


def format_bundle_index_js_text(bundle_slug: str, *, description: str | None = None) -> str:
    _ = bundle_slug, description
    return ""


def format_install_js_text(bundle_slug: str) -> str:
    name = _sanitize_segment(bundle_slug)
    description = "Render automation workflows" if name == "render" else f"{name.replace('_', ' ').title()} automation workflows"
    registration_block = "\n".join(
        [
            f"# {name}",
            "",
            f"* **{name}** (~/.claude/skills/{name}/SKILL.md) - {description}. Trigger: /{name}",
            "",
            "When the user:",
            "",
            f"* mentions {name.replace('_', ' ')} automation tasks",
            f"* OR uses /{name}",
            "",
            "Invoke:",
            f'skill: "{name}"',
        ]
    )
    return (
        "const fs = require(\"fs\");\n"
        "const os = require(\"os\");\n"
        "const path = require(\"path\");\n\n"
        "const skillName = "
        + json.dumps(name)
        + ";\n"
        "const claudeRoot = path.join(os.homedir(), \".claude\");\n"
        "const source = path.join(__dirname, \"claude\", \"skills\", skillName);\n"
        "const target = path.join(claudeRoot, \"skills\", skillName);\n"
        "const claudeCandidates = [path.join(claudeRoot, \"CLAUDE.md\"), path.join(claudeRoot, \"Claude.md\")];\n"
        "const claudePath = claudeCandidates.find((candidate) => fs.existsSync(candidate)) || claudeCandidates[0];\n"
        "const renderBlock = "
        + json.dumps(registration_block)
        + ";\n\n"
        "console.log(`Source skill path: ${source}`);\n"
        "console.log(`Target skill path: ${target}`);\n"
        "console.log(`CLAUDE.md path: ${claudePath}`);\n"
        "fs.mkdirSync(path.dirname(target), { recursive: true });\n"
        "fs.cpSync(source, target, { recursive: true, force: true });\n"
        "const existing = fs.existsSync(claudePath) ? fs.readFileSync(claudePath, \"utf8\") : \"\";\n"
        "if (!existing.includes(`# ${skillName}`) && !existing.includes(`skill: \\\"${skillName}\\\"`)) {\n"
        "  const next = existing.trimEnd() ? `${existing.trimEnd()}\\n\\n${renderBlock}\\n` : `${renderBlock}\\n`;\n"
        "  fs.mkdirSync(path.dirname(claudePath), { recursive: true });\n"
        "  fs.writeFileSync(claudePath, next, \"utf8\");\n"
        "  console.log(`Registered ${skillName} in ${claudePath}`);\n"
        "} else {\n"
        "  console.log(`${skillName} block already present in ${claudePath}`);\n"
        "}\n"
    )


def format_install_bat_text(bundle_slug: str) -> str:
    _ = _sanitize_segment(bundle_slug)
    return (
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "echo Installing Render Skill...\r\n"
        "node install.js\r\n"
        "echo Done!\r\n"
        "pause\r\n"
    )


def format_render_js_text(bundle_slug: str) -> str:
    _ = _sanitize_segment(bundle_slug)
    return _RENDER_JS


def format_render_bat_text(bundle_slug: str) -> str:
    _ = _sanitize_segment(bundle_slug)
    return (
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "node \"%~dp0render.js\" %*\r\n"
    )


def read_engine_files() -> dict[str, str]:
    return {
        "executor.js": _EXECUTOR_JS,
    }


def read_bridge_files() -> dict[str, str]:
    return {"run.js": _BRIDGE_RUN_JS}


def read_cli_files(bundle_slug: str) -> dict[str, str]:
    return {
        "render.js": format_render_js_text(bundle_slug),
        "render.bat": format_render_bat_text(bundle_slug),
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
        "manifest": f"workflows/{path.name}/manifest.json",
    }


def _workflow_package_dirs(bundle_root: Path) -> list[Path]:
    by_name: dict[str, Path] = {}
    wf_parent = bundle_root / WORKFLOWS_SUBDIR
    if wf_parent.is_dir():
        for path in wf_parent.iterdir():
            if path.is_dir() and _workflow_manifest_summary(path) is not None:
                by_name[path.name] = path
    for path in sorted(bundle_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.name in ("engine", WORKFLOWS_SUBDIR):
            continue
        if path.name in by_name:
            continue
        if _workflow_manifest_summary(path) is not None:
            by_name[path.name] = path
    return [by_name[key] for key in sorted(by_name)]


def write_skill_package_index(bundle_root: Path) -> Path:
    workflows_list: list[dict[str, str]] = []
    for path in _workflow_package_dirs(bundle_root):
        summary = _workflow_manifest_summary(path)
        if summary is not None:
            workflows_list.append(summary)
    index_path = bundle_root / INDEX_FILENAME
    index_path.write_text(
        json.dumps({"workflows": workflows_list}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index_path


def _default_bundle_skill_description(bundle_slug: str) -> str:
    base = bundle_slug.replace("_", " ").strip()
    if not base:
        return "Automation skills"
    return f"{base.title()} automation skills"


def format_bundle_skill_manifest_text(bundle_slug: str, workflows: list[dict[str, str]] | None = None) -> str:
    name = _sanitize_segment(bundle_slug)
    rows = workflows or []
    listing = json.dumps(
        [{"workflow": row["name"], "description": row["description"]} for row in rows],
        ensure_ascii=False,
        indent=2,
    )
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {name.replace('_', ' ').title()} automation workflows\n"
        "---\n\n"
        f"You are a workflow planner for a {name.replace('_', ' ').title()} automation system.\n\n"
        "## TASK\n\n"
        "Convert user request into JSON workflow steps.\n\n"
        "## OUTPUT FORMAT (STRICT)\n\n"
        "Return ONLY JSON. No explanations.\n\n"
        "Example:\n"
        "[\n"
        '{ "workflow": "delete_database" }\n'
        "]\n\n"
        "## AVAILABLE WORKFLOWS\n\n"
        "Dynamically insert all workflows from workflows/ folder:\n\n"
        f"{listing}\n\n"
        "## RULES\n\n"
        "* Use ONLY listed workflows\n"
        "* DO NOT hallucinate workflows\n"
        "* DO NOT explain anything\n"
        "* DO NOT output text outside JSON\n"
    )


def write_bundle_skill_manifest(root: Path, bundle_slug: str) -> Path:
    workflows = [summary for path in _workflow_package_dirs(root) if (summary := _workflow_manifest_summary(path)) is not None]
    path = root / BUNDLE_SKILL_MANIFEST_FILENAME.format(bundle_slug=_sanitize_segment(bundle_slug))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_bundle_skill_manifest_text(bundle_slug, workflows), encoding="utf-8")
    return path


def resolve_workflow_dir(bundle_slug: str, workflow_slug: str) -> Path | None:
    """Return workflows/<workflow_slug>/ under the bundle, or legacy bundle/<slug>."""

    br = bundle_root_dir(bundle_slug)
    if br is None or not br.is_dir():
        return None
    name = _sanitize_segment(workflow_slug)
    if not name:
        return None
    canonical = br / WORKFLOWS_SUBDIR / name
    if canonical.is_dir():
        return canonical
    legacy = br / name
    if legacy.is_dir() and name not in ("engine", WORKFLOWS_SUBDIR):
        return legacy
    return None


def skill_package_dir(bundle_slug: str, workflow_slug: str) -> Path:
    """Canonical path for workflows/<workflow_slug>/ (creates scaffold)."""

    root = ensure_bundle_scaffold(bundle_slug)
    return root / WORKFLOWS_SUBDIR / _sanitize_segment(workflow_slug)


def _clear_visual_assets(visuals_dir: Path) -> None:
    return


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
            # Allow hidden roots like .opencode/skills/name/SKILL.md
            pass
        parts.append(seg)
    if not parts:
        return None
    return str(Path(*parts).as_posix())


_PLUGIN_HYPHEN_COLLAPSE = re.compile(r"-+")


def _plugin_hyphen_segment(raw: str) -> str:
    """Must match ``hyphen_skill_plugin_name`` / ``skill_package_agent_plugin_name`` in skill_pack_builder."""

    base = str(raw or "").strip().lower().replace("_", "-")
    base = _PLUGIN_HYPHEN_COLLAPSE.sub("-", base).strip("-")
    if not base:
        base = "generated-skill"
    if len(base) > 64:
        base = base[:64].strip("-")
    return base or "generated-skill"


def _bundle_workflow_plugin_hyphen(bundle_slug: str, workflow_slug: str) -> str:
    return _plugin_hyphen_segment(f"{bundle_slug}_{workflow_slug}")


def _safe_agent_plugin_hyphen(name: str) -> bool:
    n = str(name or "").strip()
    return bool(n) and len(n) <= 64 and bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", n))


def _clear_bundle_agent_plugin_skill_folders(bundle_root: Path, hyphen_skill_name: str) -> None:
    """Remove only ``skills/<hyphen>/`` under each agent root (other workflows stay intact)."""

    if not _safe_agent_plugin_hyphen(hyphen_skill_name):
        return
    safe = hyphen_skill_name.strip()
    for root_name in (".claude",):
        d = bundle_root / root_name / "skills" / safe
        if d.is_dir():
            shutil.rmtree(d)


def _clear_legacy_workflow_agent_plugins(workflow_dir: Path) -> None:
    """Remove agent plugin dirs from pre-bundle-root layout (under workflows/<wf>/)."""

    for name in (".opencode", ".claude", ".codex"):
        root = workflow_dir / name
        if root.is_dir():
            shutil.rmtree(root)


def _collect_agent_plugin_files(workflow_dir: Path) -> dict[str, str]:
    """Legacy: SKILL.md under workflow/.opencode| .claude | .codex (older builds)."""

    out: dict[str, str] = {}
    for name in (".opencode", ".claude", ".codex"):
        base = workflow_dir / name
        if not base.is_dir():
            continue
        for skill_file in base.rglob("SKILL.md"):
            if not skill_file.is_file():
                continue
            rel = skill_file.relative_to(workflow_dir).as_posix()
            out[rel] = skill_file.read_text(encoding="utf-8")
    return out


def _collect_bundle_agent_plugin_files(bundle_root: Path) -> dict[str, str]:
    """SKILL.md under bundle/claude (current layout)."""

    out: dict[str, str] = {}
    for name in ("claude",):
        base = bundle_root / name
        if not base.is_dir():
            continue
        for skill_file in base.rglob("SKILL.md"):
            if not skill_file.is_file():
                continue
            rel = skill_file.relative_to(bundle_root).as_posix()
            out[rel] = skill_file.read_text(encoding="utf-8")
    return out


def _bundle_agent_plugin_files_for_workflow(bundle_root: Path, bundle_slug: str, workflow_slug: str) -> dict[str, str]:
    """Single-workflow view: return the bundle Claude skill file."""

    _ = workflow_slug
    out: dict[str, str] = {}
    for root_name in ("claude",):
        skill_md = bundle_root / root_name / "skills" / _sanitize_segment(bundle_slug) / "SKILL.md"
        if skill_md.is_file():
            out[skill_md.relative_to(bundle_root).as_posix()] = skill_md.read_text(encoding="utf-8")
    return out


_bundle_write_locks: dict[str, threading.Lock] = {}
_bundle_write_lock_registry = threading.Lock()


@contextmanager
def _bundle_write_lock(bundle_slug: str):
    """Serialize filesystem updates that rebuild bundle ``index.json`` for one bundle.

    Parallel ``POST /skill-pack/build`` requests use distinct workflow dirs but share
    index regeneration; a per-bundle lock prevents torn ``index.json`` writes.
    """

    key = _sanitize_segment(bundle_slug)
    with _bundle_write_lock_registry:
        lock = _bundle_write_locks.setdefault(key, threading.Lock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _write_skill_package_files_core(
    bundle_slug: str,
    workflow_slug: str,
    files: dict[str, str],
    *,
    visual_assets: dict[str, bytes] | None = None,
    extra_bundle_files: dict[str, str] | None = None,
    agent_plugin_hyphen: str | None = None,
) -> Path:
    ensure_bundle_scaffold(bundle_slug)
    wf_name = _sanitize_segment(workflow_slug)
    bundle_posix = skill_package_root_posix(bundle_slug)
    path = skill_package_dir(bundle_slug, wf_name)
    path.mkdir(parents=True, exist_ok=True)
    visuals_dir = path / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    bundle_root = bundle_root_dir(bundle_slug)
    if extra_bundle_files and bundle_root is not None and agent_plugin_hyphen:
        _clear_bundle_agent_plugin_skill_folders(bundle_root, agent_plugin_hyphen)
    _clear_legacy_workflow_agent_plugins(path)
    for filename in OBSOLETE_WORKFLOW_FILENAMES:
        stale_file = path / filename
        if stale_file.is_file():
            stale_file.unlink()
    for filename in WORKFLOW_FILENAMES:
        content = files.get(filename)
        if content is None:
            continue
        t0 = time.perf_counter()
        (path / filename).write_text(content, encoding="utf-8")
        rel_path = f"{bundle_posix}/workflows/{wf_name}/{filename}"
        skill_pack_log_append(
            {
                "kind": "file_written",
                "path": rel_path,
                "bytes": len(content.encode("utf-8")),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
            }
        )
    existing_visuals = any(
        child.is_file() and not child.name.startswith(".") and child.suffix.lower() in VISUAL_IMAGE_SUFFIXES
        for child in visuals_dir.iterdir()
    )
    if not existing_visuals:
        for filename, content in sorted((visual_assets or {}).items()):
            safe_name = Path(filename).name
            if not safe_name or safe_name.startswith("."):
                continue
            if Path(safe_name).suffix.lower() not in VISUAL_IMAGE_SUFFIXES:
                continue
            target = visuals_dir / safe_name
            if target.exists():
                continue
            t0 = time.perf_counter()
            target.write_bytes(content)
            rel_path = f"{bundle_posix}/workflows/{wf_name}/visuals/{safe_name}"
            skill_pack_log_append(
                {
                    "kind": "file_written",
                    "path": rel_path,
                    "bytes": len(content),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                }
            )
    if bundle_root is not None:
        for rel, content in sorted((extra_bundle_files or {}).items()):
            safe_rel = _sanitize_bundle_relative_path(rel)
            if safe_rel is None:
                continue
            dest = bundle_root / safe_rel
            try:
                dest.relative_to(bundle_root)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.perf_counter()
            dest.write_text(content, encoding="utf-8")
            skill_pack_log_append(
                {
                    "kind": "file_written",
                    "path": f"{bundle_posix}/{safe_rel}",
                    "bytes": len(content.encode("utf-8")),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                }
            )
    root = bundle_root_dir(bundle_slug)
    assert root is not None
    t0 = time.perf_counter()
    write_skill_package_index(root)
    skill_pack_log_append(
        {
            "kind": "bundle_artifact_updated",
            "path": f"{bundle_posix}/{INDEX_FILENAME}",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    )
    t0 = time.perf_counter()
    write_bundle_skill_manifest(root, bundle_slug)
    skill_pack_log_append(
        {
            "kind": "bundle_artifact_updated",
            "path": f"{bundle_posix}/{BUNDLE_SKILL_MANIFEST_FILENAME.format(bundle_slug=_sanitize_segment(bundle_slug))}",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    )
    return path


def write_skill_package_files(
    bundle_slug: str,
    workflow_slug: str,
    files: dict[str, str],
    *,
    visual_assets: dict[str, bytes] | None = None,
    extra_bundle_files: dict[str, str] | None = None,
    agent_plugin_hyphen: str | None = None,
) -> Path:
    with _bundle_write_lock(bundle_slug):
        return _write_skill_package_files_core(
            bundle_slug,
            workflow_slug,
            files,
            visual_assets=visual_assets,
            extra_bundle_files=extra_bundle_files,
            agent_plugin_hyphen=agent_plugin_hyphen,
        )


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
    skill_path = package_dir / "skill.md"
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
    wf_parent = bundle_root / WORKFLOWS_SUBDIR
    if wf_parent.is_dir():
        return any(p.is_dir() and _workflow_manifest_summary(p) is not None for p in wf_parent.iterdir())
    return any(
        p.is_dir()
        and p.name not in ("engine", WORKFLOWS_SUBDIR)
        and _workflow_manifest_summary(p) is not None
        for p in bundle_root.iterdir()
    )


def list_skill_bundle_summaries() -> list[dict[str, object]]:
    """One entry per bundle directory under the container."""

    container = skill_package_root_dir()
    out: list[dict[str, object]] = []
    for path in sorted(container.iterdir(), key=lambda p: p.name):
        if not path.is_dir():
            continue
        if path.name in RESERVED_BUNDLE_SLUGS:
            continue
        if path.name == "engine":
            continue
        if path.name == WORKFLOWS_SUBDIR:
            continue
        if not _bundle_has_workflows(path):
            continue
        workflow_paths = _workflow_package_dirs(path)
        if not workflow_paths:
            continue
        workflow_paths.sort(key=lambda wp: wp.stat().st_mtime_ns, reverse=True)
        max_mtime = max(wp.stat().st_mtime for wp in workflow_paths)
        workflows_meta: list[dict[str, object]] = []
        for wp in workflow_paths:
            wf_name = wp.name
            label = _workflow_folder_display_label(wp, wf_name)
            present_files = [fn for fn in WORKFLOW_FILENAMES if (wp / fn).is_file()]
            workflows_meta.append(
                {
                    "workflow_slug": wf_name,
                    "display_label": label,
                    "modified_at": wp.stat().st_mtime,
                    "files": present_files,
                }
            )
        file_keys: list[str] = [
            INSTALL_JS_FILENAME,
            INSTALL_BAT_FILENAME,
            *CLI_FILENAMES,
            INDEX_FILENAME,
            *[f"engine/{f}" for f in ENGINE_FILENAMES],
            *[f"bridge/{f}" for f in BRIDGE_FILENAMES],
        ]
        file_keys.extend(sorted(_collect_bundle_agent_plugin_files(path).keys()))
        for wm in workflows_meta:
            wf = str(wm["workflow_slug"])
            for fn in wm["files"]:  # type: ignore[arg-type]
                file_keys.append(f"{WORKFLOWS_SUBDIR}/{wf}/{fn}")
        out.append(
            {
                "package_name": path.name,
                "modified_at": max_mtime,
                "workflows": workflows_meta,
                "files": file_keys,
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
    """Flatten bundle tree: workflows/<wf>/<file>, engine/*, bridge/*, installers, Claude skill, index."""

    root = bundle_root_dir(bundle_slug)
    if root is None or not root.is_dir():
        return None
    out: dict[str, str] = {}
    for filename in (INSTALL_JS_FILENAME, INSTALL_BAT_FILENAME, *CLI_FILENAMES):
        path = root / filename
        if path.is_file():
            out[filename] = path.read_text(encoding="utf-8")
    skill_manifest_path = root / BUNDLE_SKILL_MANIFEST_FILENAME.format(bundle_slug=_sanitize_segment(bundle_slug))
    if skill_manifest_path.is_file():
        out[skill_manifest_path.relative_to(root).as_posix()] = skill_manifest_path.read_text(encoding="utf-8")
    index_path = root / INDEX_FILENAME
    if index_path.is_file():
        out[INDEX_FILENAME] = index_path.read_text(encoding="utf-8")
    engine_root = root / "engine"
    for filename in ENGINE_FILENAMES:
        engine_file = engine_root / filename
        if engine_file.is_file():
            out[f"engine/{filename}"] = engine_file.read_text(encoding="utf-8")
    bridge_root = root / "bridge"
    for filename in BRIDGE_FILENAMES:
        bridge_file = bridge_root / filename
        if bridge_file.is_file():
            out[f"bridge/{filename}"] = bridge_file.read_text(encoding="utf-8")
    for wf_path in _workflow_package_dirs(root):
        wf_name = wf_path.name
        prefix = f"{WORKFLOWS_SUBDIR}/{wf_name}/"
        for filename in WORKFLOW_FILENAMES:
            fp = wf_path / filename
            if fp.is_file():
                out[prefix + filename] = fp.read_text(encoding="utf-8")
        for rel, text in _collect_agent_plugin_files(wf_path).items():
            out[prefix + rel] = text
        for vk, vv in _read_visual_assets(wf_path).items():
            out[prefix + vk] = vv
    out.update(_collect_bundle_agent_plugin_files(root))
    return out or None


def read_skill_package_files(bundle_slug: str, workflow_slug: str) -> dict[str, str] | None:
    """Single-workflow overlay: bundle runtime files plus unprefixed workflow files + visuals/."""

    root = bundle_root_dir(bundle_slug)
    if root is None or not root.is_dir():
        return None
    wf_dir = resolve_workflow_dir(bundle_slug, workflow_slug)
    if wf_dir is None:
        return None
    out: dict[str, str] = {}
    for filename in (INSTALL_JS_FILENAME, INSTALL_BAT_FILENAME, *CLI_FILENAMES):
        path = root / filename
        if path.is_file():
            out[filename] = path.read_text(encoding="utf-8")
    skill_manifest_path = root / BUNDLE_SKILL_MANIFEST_FILENAME.format(bundle_slug=_sanitize_segment(bundle_slug))
    if skill_manifest_path.is_file():
        out[skill_manifest_path.relative_to(root).as_posix()] = skill_manifest_path.read_text(encoding="utf-8")
    index_path = root / INDEX_FILENAME
    if index_path.is_file():
        out[INDEX_FILENAME] = index_path.read_text(encoding="utf-8")
    engine_root = root / "engine"
    for filename in ENGINE_FILENAMES:
        engine_file = engine_root / filename
        if engine_file.is_file():
            out[f"engine/{filename}"] = engine_file.read_text(encoding="utf-8")
    bridge_root = root / "bridge"
    for filename in BRIDGE_FILENAMES:
        bridge_file = bridge_root / filename
        if bridge_file.is_file():
            out[f"bridge/{filename}"] = bridge_file.read_text(encoding="utf-8")
    for filename in WORKFLOW_FILENAMES:
        fp = wf_dir / filename
        if fp.is_file():
            out[filename] = fp.read_text(encoding="utf-8")
    out.update(_bundle_agent_plugin_files_for_workflow(root, bundle_slug, workflow_slug))
    out.update(_collect_agent_plugin_files(wf_dir))
    out.update(_read_visual_assets(wf_dir))
    return out or None


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
    new_root = skill_package_root_dir() / new
    if new_root.exists():
        raise ValueError(f'A skill package named "{new}" already exists.')
    old_root.rename(new_root)


def delete_skill_package_workflow(bundle_slug: str, workflow_slug: str) -> bool:
    path = resolve_workflow_dir(bundle_slug, workflow_slug)
    if path is None or not path.is_dir():
        return False
    hyphen = _bundle_workflow_plugin_hyphen(bundle_slug, workflow_slug)
    root = bundle_root_dir(bundle_slug)
    if root and root.is_dir():
        _clear_bundle_agent_plugin_skill_folders(root, hyphen)
    shutil.rmtree(path)
    if root and root.is_dir():
        with _bundle_write_lock(bundle_slug):
            write_skill_package_index(root)
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
    new_parent = (bundle_root_dir(bundle_slug) or Path()) / WORKFLOWS_SUBDIR
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
            write_skill_package_index(root)
