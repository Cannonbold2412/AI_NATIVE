"""JSON and markdown formatters for skill package bundle artifacts."""

from __future__ import annotations

import json


def format_plugin_index_json(bundle_slug: str, skills: list[dict[str, str]]) -> str:
    """Machine-readable plugin index used to discover available skills."""

    return (
        json.dumps(
            {
                "plugin": bundle_slug,
                "version": "1.0.0",
                "skills": [
                    {
                        "name": skill["name"],
                        "description": skill["description"],
                        "execution": f"skills/{skill['name']}/execution.json",
                        "recovery": f"skills/{skill['name']}/recovery.json",
                    }
                    for skill in skills
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def format_plugin_readme_text(bundle_slug: str, skills: list[dict[str, str]]) -> str:
    """Human-readable README generated from the bundle's skill manifests."""

    title = bundle_slug.replace("_", " ").title()
    lines = [
        f"# {title} Plugin",
        "",
        f"Automation plugin for {title}.",
        "",
        "## Available Skills",
        "",
    ]
    for skill in skills:
        name = skill["name"]
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(skill["description"])
        lines.append("")
    lines += [
        "## Setup",
        "",
        "```bash",
        "npm install",
        "```",
        "",
        "## Usage",
        "",
        "```bash",
        "node execution/executor.js --skill <skill-name> [--input-key value ...]",
        "```",
        "",
    ]
    return "\n".join(lines)


def format_plugin_claude_md_text(bundle_slug: str, skills: list[dict[str, str]]) -> str:
    """Instructions for Claude — describes every skill and how to orchestrate them."""

    title = bundle_slug.replace("_", " ").title()
    lines = [
        f"# {title} Plugin — Claude Instructions",
        "",
        "You are orchestrating an automation plugin. Read this file to understand what skills are available, what each skill does, and how to combine them to fulfil user requests.",
        "",
        "## Plugin Structure",
        "",
        "- `plugin.json` — machine-readable manifest listing all skills and auth config",
        "- `auth/auth.json` — saved browser session (restored before every skill run)",
        "- `auth/login/` — login skill, runs automatically if session expires",
        "- `skills/{name}/SKILL.md` — step-by-step description of each skill",
        "- `skills/{name}/execution.json` — machine-executable actions",
        "- `skills/{name}/recovery.json` — fallback strategies for self-healing",
        "- `execution/executor.js` — universal runner, pass `--skill <name>` to execute",
        "",
        "## Available Skills",
        "",
    ]
    for skill in skills:
        name = skill["name"]
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(skill["description"])
        lines.append("")
        lines.append(f"Read `skills/{name}/SKILL.md` for the full step-by-step breakdown.")
        lines.append("")
    lines += [
        "## Orchestration Rules",
        "",
        "1. Authentication is handled automatically — do not include login steps in your plan.",
        "2. Read each relevant `SKILL.md` before deciding the execution order.",
        "3. Ask the user for any required inputs before starting execution.",
        "4. If a skill fails, the self-healing system will attempt recovery — wait for the outcome before replanning.",
        "5. Skills can be composed sequentially; pass outputs of one skill as inputs to the next where applicable.",
        "",
    ]
    return "\n".join(lines)


def infer_auth_config(all_inputs: list[dict[str, str]]) -> dict[str, object]:
    """Infer a bundle auth hint from sensitive input names."""

    sensitive_names = [str(item.get("name") or "").lower() for item in all_inputs if item.get("sensitive")]
    if any(hint in name for name in sensitive_names for hint in ("api_key", "apikey", "token")):
        auth_type = "api-key"
    elif any("password" in name or "passwd" in name or "passcode" in name for name in sensitive_names):
        auth_type = "password"
    elif sensitive_names:
        auth_type = "password"
    else:
        auth_type = "none"
    return {"type": auth_type, "description": f"Authentication for this plugin ({auth_type})"}


def format_auth_json_text(auth_dict: dict[str, object]) -> str:
    return json.dumps(auth_dict, ensure_ascii=False, indent=2) + "\n"


def format_credentials_example_json_text(sensitive_inputs: list[dict[str, str]]) -> str:
    example = {item["name"]: "" for item in sensitive_inputs if item.get("name")}
    if not example:
        example = {"_example_api_key": "your-key-here"}
    return json.dumps(example, ensure_ascii=False, indent=2) + "\n"


def format_test_cases_stub_json_text(inputs: list[dict[str, str]]) -> str:
    defaults: dict[str, str] = {}
    for item in inputs:
        input_type = str(item.get("type") or "string").lower()
        if input_type == "boolean":
            defaults[item["name"]] = "false"
        elif input_type in ("number", "integer"):
            defaults[item["name"]] = "0"
        else:
            defaults[item["name"]] = f"example_{item['name']}"
    return (
        json.dumps(
            [
                {
                    "id": "case-1",
                    "description": "Basic happy path",
                    "inputs": defaults,
                    "expected": {"success": True},
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
