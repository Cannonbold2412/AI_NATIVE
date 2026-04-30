"""Shared LLM HTTP client with round-robin API key rotation."""

from __future__ import annotations

import itertools
import json
import re
import threading
from datetime import datetime, timezone
from typing import Any
from urllib import error, request
from urllib.parse import urlparse, urlunparse

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


def _safe_error_snippet(text: str, limit: int = 280) -> str:
    t = " ".join(str(text).split())
    if len(t) > limit:
        return t[: limit - 3] + "..."
    return t


def _append_llm_detail(sink: list[str] | None, msg: str) -> None:
    _debug_log(msg)
    if sink is not None:
        sink.append(msg)


def _is_openai_compatible_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    # Local/custom adapters may still accept the legacy payload shape.
    if "integrate.api.nvidia.com" in (parsed.netloc or ""):
        return True
    return (parsed.path or "").rstrip("/") == "/v1"


def supports_multimodal_chat(endpoint: str | None = None) -> bool:
    """True when the configured endpoint uses OpenAI-style chat (vision images supported)."""
    ep = str(endpoint or settings.llm_endpoint or "").strip()
    return bool(ep) and _is_openai_compatible_endpoint(ep)


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


def _resolved_model(task: str, payload: dict[str, Any]) -> Any:
    if task == "anchor_vision":
        return payload.get("model") or settings.llm_vision_model or settings.llm_text_model
    return payload.get("model") or settings.llm_text_model or settings.llm_vision_model


def _openai_messages_for_task(task: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("input")
    prompt = payload.get("prompt")

    if task == "semantic_enrichment":
        return [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys: intent (snake_case string), normalized_text (string), "
                    "confidence (0 to 1 number)."
                ),
            },
            {"role": "user", "content": json.dumps(data or {}, ensure_ascii=False)},
        ]
    if task == "recovery_assist":
        return [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys: selected (candidate id string), confidence (0 to 1 number), "
                    "reason (short string)."
                ),
            },
            {"role": "user", "content": json.dumps(data or {}, ensure_ascii=False)},
        ]
    if task == "vision_reasoning":
        return [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys: best_candidate (candidate id string), confidence (0 to 1 number), "
                    "reason (short string)."
                ),
            },
            {"role": "user", "content": json.dumps({"prompt": prompt, "input": data}, ensure_ascii=False)},
        ]
    if task == "intent_generation":
        intent_prompt = ""
        if isinstance(data, dict):
            intent_prompt = str(data.get("prompt") or "")
        return [
            {
                "role": "system",
                "content": "Return strict JSON with key: intent (single snake_case string).",
            },
            {"role": "user", "content": intent_prompt or json.dumps(data or {}, ensure_ascii=False)},
        ]
    if task == "anchor_vision":
        image_b64 = str(payload.get("image_base64") or "")
        mime = str(payload.get("image_mime") or "image/jpeg")
        user_text = str(payload.get("user_text") or "")
        # NVIDIA Gemma 4 VLMs: put image before text for best multimodal behavior (NIM docs).
        return [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys: "
                    "primary_phrase (short string describing the highlighted control), "
                    "secondary (array of objects with keys element and relation only). "
                    "relation must be one of: inside, above, below, near. "
                    "No markdown, no extra keys."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                    },
                    {"type": "text", "text": user_text},
                ],
            },
        ]
    return [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _openai_body_dict(task: str, payload: dict[str, Any], *, json_mode: bool) -> dict[str, Any]:
    resolved_model = _resolved_model(task, payload)
    messages = _openai_messages_for_task(task, payload)
    body: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": 0.0,
    }
    if task == "anchor_vision":
        # Short JSON anchors; VLMs often expect an explicit ceiling (see NVIDIA Gemma chat examples).
        body["max_tokens"] = 1024
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def _extract_json_object_substring(raw: str) -> str | None:
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


def _parse_json_object_content(content: str) -> dict[str, Any] | None:
    s = content.strip()
    try:
        p = json.loads(s)
        if isinstance(p, dict):
            return p
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", s, re.I)
    if fence:
        try:
            p = json.loads(fence.group(1))
            if isinstance(p, dict):
                return p
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    sub = _extract_json_object_substring(s)
    if sub:
        try:
            p = json.loads(sub)
            if isinstance(p, dict):
                return p
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return None


def _provider_top_level_error(data: dict[str, Any]) -> str | None:
    err = data.get("error")
    if err is None:
        return None
    if isinstance(err, dict):
        msg = err.get("message")
        typ = err.get("type") or err.get("code")
        parts = [str(p) for p in (msg, typ) if p]
        return ": ".join(parts) if parts else json.dumps(err, ensure_ascii=False)[:280]
    if isinstance(err, str):
        return err
    return json.dumps(err, ensure_ascii=False)[:280]


def _normalize_openai_response(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return data
    first = choices[0]
    if not isinstance(first, dict):
        return data
    message = first.get("message")
    content = ""
    if isinstance(message, dict):
        raw_content = message.get("content")
        if isinstance(raw_content, list):
            # Some providers emit content as multimodal fragments.
            chunks: list[str] = []
            for part in raw_content:
                if isinstance(part, dict) and part.get("type") == "text":
                    chunks.append(str(part.get("text") or ""))
            content = "".join(chunks).strip()
        else:
            content = str(raw_content or "").strip()
    if not content:
        content = str(first.get("text") or "").strip()
    if not content:
        return data
    parsed = _parse_json_object_content(content)
    if parsed is not None:
        return parsed
    try:
        p = json.loads(content)
        if isinstance(p, dict):
            return p
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


def _decode_http_error_body(exc: error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def call_llm(
    task: str,
    payload: dict[str, Any],
    timeout_ms: int,
    *,
    error_detail: list[str] | None = None,
) -> dict[str, Any] | None:
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
        f"key_slot={key_slot}/{key_count} timeout_ms={timeout_ms}"
    )
    endpoint_raw = settings.llm_endpoint
    use_openai_shape = _is_openai_compatible_endpoint(endpoint_raw)

    timeout_s = max(0.2, timeout_ms / 1000.0)

    def _single_openai_post(*, json_mode: bool, attempt_tag: str) -> dict[str, Any] | None:
        ep = _chat_completions_url(endpoint_raw) if use_openai_shape else endpoint_raw
        body_dict = _openai_body_dict(task, payload, json_mode=json_mode)
        raw_body = json.dumps(body_dict).encode("utf-8")
        req = request.Request(ep, data=raw_body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout_s) as res:
                raw = res.read().decode("utf-8")
        except error.HTTPError as exc:
            bod = _decode_http_error_body(exc)
            snippet = _safe_error_snippet(bod or str(exc.reason or exc))
            _append_llm_detail(
                error_detail,
                f"HTTPError {exc.code} ({attempt_tag}): {snippet}",
            )
            return None
        except (error.URLError, TimeoutError, OSError) as exc:
            _append_llm_detail(error_detail, f"{type(exc).__name__} ({attempt_tag}): {exc}")
            return None

        try:
            data_raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            snippet = _safe_error_snippet(raw)
            pos = getattr(exc, "pos", None)
            loc = f"@{pos}" if pos is not None else ""
            _append_llm_detail(
                error_detail,
                f"JSONDecodeError ({attempt_tag}) body{loc}: {snippet}",
            )
            return None

        if not isinstance(data_raw, dict):
            _append_llm_detail(
                error_detail,
                f"unexpected_json_root ({attempt_tag}): {type(data_raw).__name__}",
            )
            return None

        prov_msg = _provider_top_level_error(data_raw)
        if prov_msg:
            _append_llm_detail(error_detail, f"provider_error ({attempt_tag}): {prov_msg}")
            return None

        data = _normalize_openai_response(data_raw)

        _debug_log(
            "response_received "
            f"req_id={req_id} task={task} json_mode={json_mode} "
            f"attempt={attempt_tag} status_ok"
        )
        return data if isinstance(data, dict) else None

    try:
        if use_openai_shape:
            modes = [(True, "json_mode")]
            if task == "anchor_vision":
                modes.append((False, "compat_no_json_format"))
            for json_mode, tag in modes:
                out = _single_openai_post(json_mode=json_mode, attempt_tag=tag)
                if out is not None:
                    return out
                if task != "anchor_vision":
                    break
            return None

        body_legacy = _legacy_payload(task, payload)
        req = request.Request(endpoint_raw, data=body_legacy, headers=headers, method="POST")
        with request.urlopen(req, timeout=timeout_s) as res:
            raw = res.read().decode("utf-8")
        data_legacy = json.loads(raw)
        if not isinstance(data_legacy, dict):
            _append_llm_detail(
                error_detail,
                f"unexpected_json_root legacy: {type(data_legacy).__name__}",
            )
            return None
        _debug_log(f"response_received req_id={req_id} task={task} status=legacy_ok")
        return data_legacy

    except error.HTTPError as exc:
        bod = _decode_http_error_body(exc)
        snippet = _safe_error_snippet(bod or str(exc.reason or exc))
        _append_llm_detail(error_detail, f"HTTPError {exc.code}: {snippet}")
        return None
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        _append_llm_detail(error_detail, f"request_failed legacy {type(exc).__name__}: {exc}")
        return None
