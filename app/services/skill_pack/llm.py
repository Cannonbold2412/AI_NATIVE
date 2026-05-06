"""Pack-specific LLM structuring client."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib import error, request
from urllib.parse import urlparse, urlunparse

from app.config import settings
from app.llm.pack_llm_keys import next_pack_api_key
from app.services.skill_pack_build_log import (
    skill_pack_json_metrics,
    skill_pack_log_append,
    skill_pack_text_metrics,
)

_logger = logging.getLogger(__name__)

_PACK_LLM_TRANSIENT_HTTP = frozenset({502, 503, 504})

_STRUCTURING_SYSTEM_PROMPT = """You are an expert automation compiler.

Convert messy browser interaction logs into structured steps.

Rules:

* Remove focus and wait actions (never output `wait`).
* Fold redundant scroll jitter into purposeful `scroll` steps when scrolling clearly reveals UI.
* Merge redundant steps
* Infer user intent
* Replace hardcoded values with variables like {{user_email}}
* Use ONLY these types:

  * navigate
  * fill
  * click
  * scroll — when content only appears after scrolling:
    optional `selector` (scroll that element into view, same selector rules as `click`),
    optional `delta_y` (positive = down, negative = up, wheel pixels with `delta_x` defaulting to 0);
    supply at least one of `selector` or `delta_y` (non-zero).
  * check — insert after important actions to verify the outcome. Use one of these kinds:
    - `{ "type": "check", "kind": "url", "pattern": "..." }` — verify the current URL contains a substring pattern
    - `{ "type": "check", "kind": "url_exact", "url": "..." }` — verify the current URL is exactly this URL
    - `{ "type": "check", "kind": "snapshot", "threshold": 0.9 }` — verify the page looks similar to the saved snapshot (>=90% similarity)
    - `{ "type": "check", "kind": "selector", "selector": "..." }` — verify an element is present on the page
    - `{ "type": "check", "kind": "text", "text": "..." }` — verify specific text appears on the page

When to insert `check` steps:
* After a login / sign-in action — use `check url` or `check text` to confirm successful authentication
* After a form submission — use `check text` or `check url` to confirm the action succeeded
* After navigating to a critical page — use `check url` to confirm the correct page loaded
* After a destructive action (delete, remove, reset) — use `check text` to confirm the outcome
* After key state transitions that the rest of the workflow depends on

Rules for selectors:

* Prefer text="..." for buttons
* Use input[name="..."] for fields
* NEVER output:

  * "input"
  * "button"
  * XPath

Output JSON ONLY:

{
"goal": "...",
"steps": [
{
"type": "navigate",
"url": "..."
},
{
"type": "fill",
"selector": "input[name=email]",
"value": "{{user_email}}"
},
{
"type": "click",
"selector": "text=Sign in"
},
{
"type": "check",
"kind": "url",
"pattern": "/dashboard"
},
{
"type": "check",
"kind": "url_exact",
"url": "https://example.test/dashboard"
},
{
"type": "scroll",
"selector": "text=Load more reviews"
},
{
"type": "scroll",
"delta_y": 480
},
{
"type": "check",
"kind": "text",
"text": "Welcome"
}
]
}
"""


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
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _extract_llm_content(payload: dict[str, Any]) -> str:
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


def _extract_json_object_substring(raw: str) -> str | None:
    """First balanced `{...}` slice in raw (same idea as app.llm.client)."""
    lb = raw.find("{")
    if lb < 0:
        return None
    depth = 0
    for i in range(lb, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                return raw[lb : i + 1]
    return None


def _parse_strict_json_object(text: str) -> dict[str, Any]:
    """Parse model text into a dict; allow markdown fences and leading/trailing prose."""
    s = (text or "").strip()
    if not s:
        raise ValueError("LLM structuring must return a JSON object only.")

    last_err: json.JSONDecodeError | None = None

    def try_parse(chunk: str) -> dict[str, Any] | None:
        nonlocal last_err
        chunk = chunk.strip()
        if not chunk:
            return None
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError as exc:
            last_err = exc
            return None
        return parsed if isinstance(parsed, dict) else None

    got = try_parse(s)
    if got is not None:
        return got

    sub = _extract_json_object_substring(s)
    if sub:
        got = try_parse(sub)
        if got is not None:
            return got

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.I)
    if fence:
        inner = fence.group(1).strip()
        got = try_parse(inner)
        if got is not None:
            return got
        sub2 = _extract_json_object_substring(inner)
        if sub2:
            got = try_parse(sub2)
            if got is not None:
                return got

    if last_err is not None:
        raise ValueError(
            f"LLM structuring returned invalid JSON: {last_err.msg}"
        ) from last_err
    raise ValueError("LLM structuring must return a JSON object only.")


def _call_structuring_llm(raw_steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.pack_llm_enabled:
        raise ValueError(
            "Skill package generation requires the LLM structuring layer; SKILL_PACK_LLM_ENABLED is disabled."
        )
    endpoint = str(settings.pack_llm_endpoint or "").strip()
    model = str(settings.pack_llm_model or "").strip()
    if not endpoint or not model:
        raise ValueError(
            "Skill package generation requires SKILL_PACK_LLM_ENDPOINT and SKILL_PACK_LLM_MODEL."
        )

    parsed_ep = urlparse(endpoint)
    ep_host = (parsed_ep.netloc or "").lower()
    user_msg = json.dumps(
        {"raw_steps": raw_steps}, ensure_ascii=False, separators=(",", ":")
    )
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _STRUCTURING_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": settings.pack_llm_structure_temperature,
    }
    if settings.pack_llm_structure_max_tokens is not None:
        body["max_tokens"] = settings.pack_llm_structure_max_tokens
    if settings.pack_llm_top_p is not None:
        body["top_p"] = settings.pack_llm_top_p
    # integrate.api.nvidia.com: runtime logs show repeated HTTP 504 ~300s with response_format=json_object;
    # omit strict JSON mode so the gateway/model can finish within upstream limits; prompt still requires JSON.
    if "integrate.api.nvidia.com" not in ep_host:
        body["response_format"] = {"type": "json_object"}
    raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    url = _chat_completions_url(endpoint)
    parsed_call = urlparse(url)
    api_path = (parsed_call.path or "/").strip() or "/"
    strict_json_response = body.get("response_format") is not None
    _timeout_s = max(0.2, settings.pack_llm_timeout_ms / 1000.0)
    # Transient 5xx retries: up to this many HTTP POSTs total (initial + retries).
    max_tries = settings.pack_llm_max_attempts
    raw_step_count = len(raw_steps)

    raw = ""
    for attempt in range(max_tries):
        headers = {"Content-Type": "application/json"}
        pack_key, _, _ = next_pack_api_key()
        if pack_key:
            headers["Authorization"] = f"Bearer {pack_key}"

        req = request.Request(url, data=raw_body, headers=headers, method="POST")
        system_prompt_metrics = skill_pack_text_metrics(
            _STRUCTURING_SYSTEM_PROMPT, prefix="system_prompt"
        )
        user_message_metrics = skill_pack_text_metrics(user_msg, prefix="user_message")
        skill_pack_log_append(
            {
                "kind": "llm_request_sent",
                "attempt": attempt + 1,
                "model": model,
                "host": (parsed_ep.netloc or "").lower() or None,
                "path": api_path,
                "timeout_ms": int(settings.pack_llm_timeout_ms),
                "payload_bytes": len(raw_body),
                "llm_message_chars": system_prompt_metrics["system_prompt_chars"]
                + user_message_metrics["user_message_chars"],
                "llm_message_words": system_prompt_metrics["system_prompt_words"]
                + user_message_metrics["user_message_words"],
                "llm_message_bytes": system_prompt_metrics["system_prompt_bytes"]
                + user_message_metrics["user_message_bytes"],
                **system_prompt_metrics,
                **user_message_metrics,
                **skill_pack_json_metrics(body, prefix="request_body"),
                "raw_step_count": raw_step_count,
                "max_attempts": max_tries,
                "strict_json_response": strict_json_response,
            }
        )
        t0 = time.perf_counter()
        try:
            with request.urlopen(req, timeout=_timeout_s) as res:
                raw = res.read().decode("utf-8")
                skill_pack_log_append(
                    {
                        "kind": "llm_response_received",
                        "attempt": attempt + 1,
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                        **skill_pack_text_metrics(raw, prefix="response"),
                    }
                )
                break
        except error.HTTPError as exc:
            err_preview = ""
            try:
                err_chunk = exc.read()
                err_preview = (
                    err_chunk.decode("utf-8", errors="replace")
                    .strip()
                    .replace("\n", " ")[:1400]
                )
            except Exception:
                err_preview = ""
            elapsed_http = round((time.perf_counter() - t0) * 1000, 2)
            skill_pack_log_append(
                {
                    "kind": "llm_http_error",
                    "attempt": attempt + 1,
                    "status": exc.code,
                    "reason": str(exc.reason),
                    "elapsed_ms": elapsed_http,
                    "response_body_chars": len(err_preview),
                    "response_body_words": skill_pack_text_metrics(err_preview).get(
                        "words", 0
                    ),
                    "response_body_bytes": len(err_preview.encode("utf-8")),
                    **({"response_body_preview": err_preview} if err_preview else {}),
                }
            )
            if exc.code in _PACK_LLM_TRANSIENT_HTTP and attempt < max_tries - 1:
                skill_pack_log_append(
                    {
                        "kind": "llm_retry",
                        "attempt": attempt + 1,
                        "reason": f"HTTP {exc.code}",
                    }
                )
                continue
            _logger.warning(
                "LLM structuring HTTP failure final host=%s path=%s model=%s steps=%s attempt=%s/%s status=%s elapsed_ms=%s preview=%s",
                (parsed_ep.netloc or "").lower(),
                api_path,
                model,
                raw_step_count,
                attempt + 1,
                max_tries,
                exc.code,
                elapsed_http,
                (err_preview[:240] + "…") if len(err_preview) > 240 else err_preview,
            )
            msg = (
                f"LLM structuring request failed (HTTP {exc.code}: {exc.reason!s}); "
                f"attempt {attempt + 1}/{max_tries}, {raw_step_count} raw steps, POST {api_path}."
            )
            if err_preview:
                frag = err_preview[:420]
                if len(err_preview) > 420:
                    frag += "…"
                msg += f" Response body fragment: {frag}"
            raise ValueError(msg) from exc
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            is_timeout = isinstance(exc, TimeoutError) or (
                isinstance(exc, error.URLError)
                and exc.reason is not None
                and "timed out" in str(exc.reason).lower()
            )
            if is_timeout:
                skill_pack_log_append(
                    {
                        "kind": "llm_timeout",
                        "attempt": attempt + 1,
                        "timeout_ms": int(settings.pack_llm_timeout_ms),
                        "elapsed_ms": elapsed_ms,
                        "path": api_path,
                        "raw_step_count": raw_step_count,
                    }
                )
            else:
                skill_pack_log_append(
                    {
                        "kind": "llm_network_error",
                        "attempt": attempt + 1,
                        "elapsed_ms": elapsed_ms,
                        "detail": str(exc)[:500],
                        "exc_type": type(exc).__name__,
                    }
                )
            detail = (
                f"LLM structuring request failed ({type(exc).__name__}); attempt {attempt + 1}/{max_tries}; "
                f"{raw_step_count} raw steps; POST {api_path}: {exc!s}"
            )
            _logger.warning("LLM structuring transport error %s", detail[:700])
            raise ValueError(detail) from exc

    t_parse0 = time.perf_counter()
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM structuring provider returned invalid JSON.") from exc
    skill_pack_log_append(
        {
            "kind": "llm_response_parsed",
            "elapsed_ms": round((time.perf_counter() - t_parse0) * 1000, 2),
            **skill_pack_text_metrics(raw, prefix="response"),
            **(
                {"top_level_keys": sorted(response.keys())}
                if isinstance(response, dict) and len(response) <= 24
                else {
                    "dict_key_estimate": (
                        len(response) if isinstance(response, dict) else 0
                    )
                }
            ),
        }
    )
    if not isinstance(response, dict):
        raise ValueError("LLM structuring provider returned an invalid response.")
    if "goal" in response and "steps" in response:
        skill_pack_log_append(
            {
                "kind": "llm_structured_output",
                "source": "provider_json",
                "canonical_step_count": len(response.get("steps", []))
                if isinstance(response.get("steps"), list)
                else 0,
                **skill_pack_json_metrics(response, prefix="structured"),
            }
        )
        return response
    content = _extract_llm_content(response)
    skill_pack_log_append(
        {
            "kind": "llm_message_content_extracted",
            **skill_pack_text_metrics(content, prefix="content"),
        }
    )
    structured = _parse_strict_json_object(content)
    skill_pack_log_append(
        {
            "kind": "llm_structured_output",
            "source": "message_content",
            "canonical_step_count": len(structured.get("steps", []))
            if isinstance(structured.get("steps"), list)
            else 0,
            **skill_pack_json_metrics(structured, prefix="structured"),
        }
    )
    return structured
