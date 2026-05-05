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
                        "manifest": f"skills/{skill['name']}/manifest.json",
                        "execution": f"skills/{skill['name']}/execution.json",
                        "input": f"skills/{skill['name']}/input.json",
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
        "## Skills",
        "",
    ]
    for skill in skills:
        name = skill["name"]
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(skill["description"])
        lines.append("")
        lines.append(f"- Execution: `skills/{name}/execution.json`")
        lines.append(f"- Inputs: `skills/{name}/input.json`")
        lines.append(f"- Recovery: `skills/{name}/recovery.json`")
        lines.append("")
    lines += [
        "## Usage",
        "",
        "1. Read this README or `orchestration/index.md` to understand available skills",
        "2. Use `orchestration/planner.md` to plan skill sequences",
        "3. Execute using `execution/executor.js`",
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
