"""Text LLM helper for semantic enrichment (assist-only, deterministic fallback)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.llm.client import call_llm
from app.policy.bundle import get_policy_bundle
from app.policy.intent_ontology import semantic_slug_from_text


class SemanticLLMInput(BaseModel):
    raw_text: str
    element_type: str
    context: str = ""


class SemanticLLMOutput(BaseModel):
    intent: str
    normalized_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "rule_fallback"


def _cache_path() -> Path:
    p = settings.data_dir / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / "semantic_llm_cache.json"


def _read_cache() -> dict[str, Any]:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(cache: dict[str, Any]) -> None:
    _cache_path().write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(inp: SemanticLLMInput) -> str:
    payload = json.dumps(inp.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fallback(inp: SemanticLLMInput) -> SemanticLLMOutput:
    policy = get_policy_bundle().data
    text = " ".join(inp.raw_text.lower().split())
    intent, conf = semantic_slug_from_text(inp.element_type, inp.raw_text, policy)
    return SemanticLLMOutput(intent=intent, normalized_text=text or intent, confidence=conf, source="rule_fallback")


def _call_provider(inp: SemanticLLMInput) -> SemanticLLMOutput | None:
    if not settings.llm_endpoint:
        return None
    payload = {
        "task": "semantic_enrichment",
        "model": settings.llm_text_model or None,
        "input": inp.model_dump(mode="json"),
    }
    data = call_llm("semantic_enrichment", payload, settings.llm_timeout_ms)
    if data is None:
        return None
    try:
        out = SemanticLLMOutput.model_validate(data)
        out.source = "llm"
        return out
    except Exception:
        return None


def enrich_semantic(inp: SemanticLLMInput) -> SemanticLLMOutput:
    """Best-effort semantic assist with cache + deterministic fallback."""
    if not settings.llm_enabled or not settings.llm_semantic_enrichment:
        return _fallback(inp)
    cache = _read_cache()
    k = _key(inp)
    if k in cache:
        try:
            return SemanticLLMOutput.model_validate(cache[k])
        except Exception:
            pass
    out = _call_provider(inp) or _fallback(inp)
    cache[k] = out.model_dump(mode="json")
    _write_cache(cache)
    return out
