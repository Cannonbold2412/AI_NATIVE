"""Shared LLM HTTP client with round-robin API key rotation."""

from __future__ import annotations

import itertools
import json
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib import error, request

from app.config import settings

_REQUEST_COUNTER = itertools.count(1)
_KEY_INDEX = 0
_KEY_LOCK = threading.Lock()


def _debug_log(message: str) -> None:
    if not settings.llm_debug:
        return
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[LLM DEBUG] {ts} | {message}")


def _configured_keys() -> list[str]:
    csv_keys = [k.strip() for k in str(settings.llm_api_keys or "").split(",") if k.strip()]
    if csv_keys:
        return csv_keys
    single = str(settings.llm_api_key or "").strip()
    return [single] if single else []


def _is_openai_compatible_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    # Local/custom adapters may still accept the legacy payload shape.
    if "integrate.api.nvidia.com" in (parsed.netloc or ""):
        return True
    return (parsed.path or "").rstrip("/") == "/v1"


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


def _legacy_payload(task: str, payload: dict[str, Any]) -> bytes:
    body = dict(payload)
    body.setdefault("task", task)
    return json.dumps(body).encode("utf-8")


def _openai_payload(task: str, payload: dict[str, Any]) -> bytes:
    model = payload.get("model") or settings.llm_text_model or settings.llm_vision_model
    data = payload.get("input")
    prompt = payload.get("prompt")

    if task == "semantic_enrichment":
        messages = [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys: intent (snake_case string), normalized_text (string), "
                    "confidence (0 to 1 number)."
                ),
            },
            {"role": "user", "content": json.dumps(data or {}, ensure_ascii=False)},
        ]
    elif task == "recovery_assist":
        messages = [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys: selected (candidate id string), confidence (0 to 1 number), "
                    "reason (short string)."
                ),
            },
            {"role": "user", "content": json.dumps(data or {}, ensure_ascii=False)},
        ]
    elif task == "vision_reasoning":
        messages = [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys: best_candidate (candidate id string), confidence (0 to 1 number), "
                    "reason (short string)."
                ),
            },
            {"role": "user", "content": json.dumps({"prompt": prompt, "input": data}, ensure_ascii=False)},
        ]
    elif task == "intent_generation":
        intent_prompt = ""
        if isinstance(data, dict):
            intent_prompt = str(data.get("prompt") or "")
        messages = [
            {
                "role": "system",
                "content": "Return strict JSON with key: intent (single snake_case string).",
            },
            {"role": "user", "content": intent_prompt or json.dumps(data or {}, ensure_ascii=False)},
        ]
    else:
        messages = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]

    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    return json.dumps(body).encode("utf-8")


def _normalize_openai_response(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return data
    first = choices[0]
    if not isinstance(first, dict):
        return data
    message = first.get("message")
    content: str = ""
    if isinstance(message, dict):
        content = str(message.get("content") or "").strip()
    if not content:
        content = str(first.get("text") or "").strip()
    if not content:
        return data
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"text": content, "output": content}


def _next_api_key() -> tuple[str, int, int]:
    keys = _configured_keys()
    if not keys:
        return "", 0, 0
    global _KEY_INDEX
    with _KEY_LOCK:
        idx = _KEY_INDEX % len(keys)
        _KEY_INDEX += 1
    return keys[idx], idx + 1, len(keys)


def call_llm(task: str, payload: dict[str, Any], timeout_ms: int) -> dict[str, Any] | None:
    if not settings.llm_endpoint:
        return None

    req_id = next(_REQUEST_COUNTER)
    api_key, key_slot, key_count = _next_api_key()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    _debug_log(
        "request_sent "
        f"req_id={req_id} task={task} endpoint={settings.llm_endpoint} "
        f"key_slot={key_slot}/{key_count}"
    )
    endpoint = settings.llm_endpoint
    use_openai_shape = _is_openai_compatible_endpoint(endpoint)
    body = _openai_payload(task, payload) if use_openai_shape else _legacy_payload(task, payload)
    if use_openai_shape:
        endpoint = _chat_completions_url(endpoint)

    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=max(0.2, timeout_ms / 1000.0)) as res:
            raw = res.read().decode("utf-8")
            data = json.loads(raw)
            if use_openai_shape:
                data = _normalize_openai_response(data)
            _debug_log(
                "response_received "
                f"req_id={req_id} task={task} status={getattr(res, 'status', 'unknown')}"
            )
            return data
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        _debug_log(f"request_failed req_id={req_id} task={task} error={type(exc).__name__}: {exc}")
        return None
