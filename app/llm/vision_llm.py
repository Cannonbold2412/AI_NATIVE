"""Vision LLM helper for late recovery fallback (never normal execution)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.llm.client import call_llm


class VisionCandidate(BaseModel):
    element_id: str
    crop_path: str
    text: str = ""


class VisionLLMInput(BaseModel):
    full_screenshot: str
    candidates: list[VisionCandidate]
    intent: str


class VisionLLMOutput(BaseModel):
    best_candidate: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    source: str = "rule_fallback"


def _cache_path() -> Path:
    p = settings.data_dir / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / "vision_llm_cache.json"


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


def _key(inp: VisionLLMInput) -> str:
    payload = json.dumps(inp.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fallback(inp: VisionLLMInput) -> VisionLLMOutput:
    if not inp.candidates:
        return VisionLLMOutput(best_candidate="", confidence=0.0, reason="no candidates")
    intent_tokens = set(inp.intent.lower().split("_"))
    best = inp.candidates[0]
    best_score = -1.0
    for c in inp.candidates:
        overlap = len(intent_tokens & set(c.text.lower().split()))
        score = float(overlap)
        if score > best_score:
            best_score = score
            best = c
    return VisionLLMOutput(
        best_candidate=best.element_id,
        confidence=0.65 if best_score <= 0 else 0.8,
        reason=f"matched candidate text under intent: {best.text}",
    )


def _call_provider(inp: VisionLLMInput) -> VisionLLMOutput | None:
    if not settings.llm_endpoint:
        return None
    payload = {
        "task": "vision_reasoning",
        "model": settings.llm_vision_model or None,
        "prompt": f"Given this UI screenshot and candidate elements, which element best matches the intent: {inp.intent}?",
        "input": inp.model_dump(mode="json"),
    }
    data = call_llm("vision_reasoning", payload, settings.llm_timeout_ms)
    if data is None:
        return None
    try:
        out = VisionLLMOutput.model_validate(data)
        out.source = "llm"
        return out
    except Exception:
        return None


def assist_vision(inp: VisionLLMInput, *, call_count: int = 0, recovery_phase: bool = False) -> VisionLLMOutput | None:
    """Run vision assist only in recovery and only once per step."""
    if (
        not recovery_phase
        or not settings.llm_enabled
        or not settings.llm_vision_reasoning
        or call_count >= settings.llm_max_calls_per_step
    ):
        return None
    cache = _read_cache()
    k = _key(inp)
    if k in cache:
        try:
            return VisionLLMOutput.model_validate(cache[k])
        except Exception:
            pass
    out = _call_provider(inp) or _fallback(inp)
    cache[k] = out.model_dump(mode="json")
    _write_cache(cache)
    return out
