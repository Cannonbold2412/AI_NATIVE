"""Static runtime and orchestration templates for generated skill packages."""

from __future__ import annotations

import json

ORCHESTRATION_SCHEMA_JSON = json.dumps(
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ExecutionPlan",
        "type": "array",
        "items": {
            "type": "object",
            "required": ["skill"],
            "properties": {
                "skill": {"type": "string", "description": "Skill name from plugin index"},
                "inputs": {
                    "type": "object",
                    "description": "Input values for the skill",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
    },
    ensure_ascii=False,
    indent=2,
)


def orchestration_index_md(plugin_name: str, plugin_slug: str, skill_names: list[str]) -> str:
    skill_list = "\n".join(f"- `{s}`" for s in skill_names) if skill_names else "- (none yet)"
    return (
        f"# {plugin_name} Plugin - Orchestration Guide\n\n"
        "## Entry Point\n\n"
        f"Start from `../{plugin_slug}.json` - the machine-readable index of all available skills.\n\n"
        "## How to Use\n\n"
        f"1. Read `../{plugin_slug}.json` to see all available skills and their inputs\n"
        "2. Pick the skill(s) that match the user's request\n"
        "3. Read `planner.md` for how to sequence skills and gather inputs\n"
        "4. Return a plan matching `schema.json` so the conxa runtime can execute it\n\n"
        "## Available Skills\n\n"
        f"{skill_list}\n"
    )


def orchestration_planner_md(plugin_slug: str) -> str:
    return (
        "# Planner Guide\n\n"
        "## Your Job\n\n"
        "Convert a user request into a JSON plan that the conxa runtime can execute.\n\n"
        "## Steps\n\n"
        f"1. Read `../{plugin_slug}.json` to see available skills\n"
        "2. Identify which skill(s) the user needs (one or more, in order)\n"
        "3. For each chosen skill, read `../skills/<skill-name>/input.json` for required inputs\n"
        "4. Ask the user for any missing inputs - ask once, not repeatedly\n"
        "5. Return ONLY the JSON plan matching `schema.json`, no explanations\n\n"
        "## Rules\n\n"
        f"* ONLY use skills listed in `../{plugin_slug}.json`\n"
        "* DO NOT invent or guess skill names\n"
        "* DO NOT output anything outside the JSON plan\n"
        "* Recovery is automatic - do not plan for failure explicitly\n"
    )
