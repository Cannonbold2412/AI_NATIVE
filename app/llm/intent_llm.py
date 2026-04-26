"""Intent generation for compiler V2 with cache-backed real LLM calls."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.config import settings
from app.llm.client import call_llm
from app.policy.bundle import get_policy_bundle
from app.policy.intent_ontology import generic_intents

INTENT_RE = re.compile(r"^[a-z][a-z0-9_]{2,80}$")


def _cache_path() -> Path:
    p = settings.data_dir / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / "intent_llm_cache.json"


def _read_cache() -> dict[str, str]:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


def _write_cache(cache: dict[str, str]) -> None:
    _cache_path().write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _intent_key(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sanitize_intent(value: str, fallback: str) -> str:
    intent = "_".join(value.strip().lower().split())
    if intent == "perform_action":
        return fallback
    if not INTENT_RE.match(intent):
        return fallback
    return intent


def _fallback(payload: dict[str, str], action: str) -> str:
    name = payload.get("name", "").strip().lower().replace(" ", "_")
    role = payload.get("role", "").strip().lower().replace(" ", "_")
    tag = payload.get("tag", "").strip().lower().replace(" ", "_")
    target_hint = name or role or tag or "target"
    if action == "focus":
        return f"focus_{target_hint}"
    if action in {"type", "fill", "input"}:
        return f"enter_{target_hint}_value"
    if action == "click":
        return f"click_{target_hint}"
    if action == "scroll":
        return "scroll_viewport"
    if action in {"navigate", "open", "go_to"}:
        return "navigate_to_page"
    return f"{action or 'advance'}_ui_flow"


def generate_intent_with_llm(step: dict[str, object]) -> str:
    policy = get_policy_bundle().data
    generics = generic_intents(policy)
    action = str((step.get("action") or {}).get("action") or "interact")
    target = step.get("target") or {}
    context = step.get("context") or {}
    semantic = step.get("semantic") or {}
    payload = {
        "tag": str(target.get("tag") or ""),
        "inner_text": str(target.get("inner_text") or semantic.get("normalized_text") or ""),
        "name": str(target.get("name") or ""),
        "role": str(target.get("role") or semantic.get("role") or ""),
        "placeholder": str(target.get("placeholder") or ""),
        "context": str(context.get("form_context") or ""),
    }
    fallback = _fallback(payload, action)
    cache = _read_cache()
    key = _intent_key({"action": action, **payload})
    if key in cache:
        return _sanitize_intent(cache[key], fallback)

    prompt = (
        "Given:\n"
        f"- element tag: {payload['tag']}\n"
        f"- attributes: name={payload['name']}, role={payload['role']}, placeholder={payload['placeholder']}\n"
        f"- visible text: {payload['inner_text']}\n"
        f"- page context: {payload['context']}\n\n"
        "Return one snake_case intent string that describes the user goal for this control "
        "(verb + object, no spaces). Examples of shape: focus_<name>, enter_<name>_value, click_<name>, "
        "navigate_to_<place>, scroll_viewport. Return ONLY the intent."
    )
    if settings.llm_enabled and settings.llm_endpoint:
        req_body = {
            "task": "intent_generation",
            "model": settings.llm_text_model or None,
            "input": {"prompt": prompt},
        }
        data = call_llm("intent_generation", req_body, max(500, settings.llm_timeout_ms))
        if data is not None:
            raw_intent = str(data.get("intent") or data.get("output") or data.get("text") or "").strip()
            intent = _sanitize_intent(raw_intent, fallback)
            if intent in generics:
                intent = fallback
            cache[key] = intent
            _write_cache(cache)
            return intent
    cache[key] = fallback
    _write_cache(cache)
    return fallback


def generate_intent(step: dict[str, object]) -> str:
    """Backwards-compatible alias for compiler callers."""
    return generate_intent_with_llm(step)

