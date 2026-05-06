"""Dedicated LLM client for Skill Pack Builder."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request
from urllib.parse import urlparse, urlunparse

from app.config import settings
from app.llm.pack_llm_config import resolved_pack_llm_config
from app.llm.pack_llm_keys import next_pack_api_key

_SYSTEM_PROMPT = (
    "You are an expert AI agent designer. "
    "Convert structured UI automation data into a clean, reusable markdown skill file for AI agents. "
    "Write like a human explaining the task clearly to another capable agent. "
    "Return markdown only with no code fences."
)


def _chat_completions_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        return endpoint
    if path.endswith("/v1"):
        path = f"{path}/chat/completions"
    elif not path:
        path = "/v1/chat/completions"
    else:
        path = f"{path}/chat/completions"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return str(first.get("text") or "").strip()
    content = message.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text") or ""))
        return "".join(chunks).strip()
    return str(content or "").strip()


def generate_skill_markdown_with_llm(summary: dict[str, Any]) -> str | None:
    if not settings.pack_llm_enabled:
        return None
    llm_config = resolved_pack_llm_config()
    endpoint = llm_config.endpoint
    model = llm_config.model
    if not endpoint or not model:
        return None

    prompt = (
        "Convert the structured UI workflow into a clean, high-quality `skill.md` file that an AI agent "
        "(such as Claude, Cursor, or similar) can execute reliably.\n\n"
        "OBJECTIVE\n"
        "- Transform machine-level workflow data into human-readable instructions, agent-executable steps, generalized reusable logic, and minimal precise output.\n\n"
        "DO NOT\n"
        "- Do not copy the JSON structure literally.\n"
        "- Do not use the words focus, activate, intent, or selector.\n"
        "- Do not include XPath, CSS selectors, or internal field names.\n"
        "- Do not include scroll steps.\n"
        "- Do not expose internal variable names that are not user-facing.\n\n"
        "CORE RULES\n"
        "1. Think like a human. Rewrite steps the way a human would describe them. Prefer phrases like Enter email or Click Submit.\n"
        "2. Merge redundant steps. Combine low-level actions into one meaningful step, especially focus + type -> Enter value.\n"
        "3. Generalize reusable values. Replace hardcoded values with variables when applicable.\n"
        "4. Use variables correctly. Keep variable names exactly as defined in inputs and use them naturally in sentences.\n"
        "5. Remove noise. Omit scroll steps, duplicate steps, and mechanical actions.\n"
        "6. Add missing context. Include a starting navigation step or section navigation when needed.\n"
        "7. Write strong validation. Prefer observable checks like URL changes, visible UI, confirmation prompts, or loaded pages.\n"
        "8. Handle destructive or sensitive actions carefully. Include confirmation steps and explicit validation when actions are irreversible.\n\n"
        "OUTPUT FORMAT\n"
        "- Title: `# Skill: <name>`\n"
        "- Section: `Inputs` with `* {{variable_name}}: description`\n"
        "- Section: `Steps` with numbered steps\n"
        "- Section: `Validation` with clear observable checks\n"
        "- Section: `Execution Rules`\n"
        "- Section: `Input Handling`\n\n"
        "EXECUTION RULES CONTENT\n"
        "- Execute steps in order.\n"
        "- Do not skip steps.\n"
        "- Use visible text and surrounding context to identify elements.\n"
        "- If a step fails, retry using semantic understanding.\n"
        "- If the step still fails, ask the user.\n\n"
        "INPUT HANDLING CONTENT\n"
        "- If any required {{variable}} is missing, ask the user before proceeding.\n"
        "- Replace all variables before execution.\n\n"
        "TRANSFORMATION STRATEGY\n"
        "1. Understand the workflow intent.\n"
        "2. Remove unnecessary or redundant steps.\n"
        "3. Merge related actions.\n"
        "4. Replace hardcoded values with variables.\n"
        "5. Rewrite everything in natural, human-like instructions.\n\n"
        "FINAL GOAL\n"
        "- The output should feel like a human explaining how to complete the task step by step.\n"
        "- It must not feel like a machine log or a direct translation of JSON.\n"
        "- Use the provided numbered steps and inputs as the source of truth.\n"
        "- Keep every `{{variable}}` exactly as provided in the inputs list.\n\n"
        "Structured workflow JSON:\n"
        f"{json.dumps(summary, ensure_ascii=False, indent=2)}"
    )

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": settings.pack_llm_markdown_temperature,
        "max_tokens": settings.pack_llm_markdown_max_tokens,
    }
    if settings.pack_llm_top_p is not None:
        body["top_p"] = settings.pack_llm_top_p
    headers = {"Content-Type": "application/json"}
    pack_key, _, _ = next_pack_api_key()
    if pack_key:
        headers["Authorization"] = f"Bearer {pack_key}"

    req = request.Request(
        _chat_completions_url(endpoint),
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=max(0.2, settings.pack_llm_timeout_ms / 1000.0)) as res:
            raw = res.read().decode("utf-8")
    except (error.HTTPError, error.URLError, TimeoutError, OSError, ValueError):
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return _extract_message_content(data) or None
