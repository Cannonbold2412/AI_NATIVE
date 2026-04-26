"""Text LLM helper for ambiguity resolution in recovery layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.llm.client import call_llm


class RecoveryCandidate(BaseModel):
    id: str
    text: str = ""
    role: str = ""
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class RecoveryLLMInput(BaseModel):
    intent: str
    candidates: list[RecoveryCandidate]
    context: str = ""


class RecoveryLLMOutput(BaseModel):
    selected: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    source: str = "rule_fallback"


def _cache_path() -> Path:
    p = settings.data_dir / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / "recovery_llm_cache.json"


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


def _key(inp: RecoveryLLMInput) -> str:
    payload = json.dumps(inp.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _char_ngrams(s: str, n: int = 2) -> set[str]:
    t = s.lower()
    if len(t) < n:
        return {t} if t else set()
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def _fallback(inp: RecoveryLLMInput) -> RecoveryLLMOutput:
    if not inp.candidates:
        return RecoveryLLMOutput(selected="", confidence=0.0, reason="no candidates")
    intent_l = inp.intent.lower()
    intent_underscore = set(intent_l.split("_")) - {""}
    intent_letters = set(intent_l.replace("_", ""))
    best_row: tuple[float, RecoveryCandidate] | None = None
    for c in inp.candidates:
        t = c.text.lower()
        role_l = c.role.lower()
        toks = intent_underscore & set(t.split())
        overlap = len(toks) + 0.25 * _jaccard(intent_letters, set(t.replace(" ", "")))
        gram = _jaccard(_char_ngrams(intent_l, 2), _char_ngrams(t, 2)) + 0.5 * _jaccard(
            _char_ngrams(intent_l, 3), _char_ngrams(t, 3)
        )
        role_hits = 0.0
        if role_l and role_l in intent_l:
            role_hits = 0.15
        score = c.score + 0.1 * float(overlap) + 0.2 * float(gram) + role_hits
        if best_row is None or score > best_row[0]:
            best_row = (score, c)
    assert best_row is not None
    best = best_row[1]
    return RecoveryLLMOutput(
        selected=best.id,
        confidence=min(0.95, max(0.5, best_row[0])),
        reason=f"scored match (ngram+token+base): {best.text or best.id}",
    )


def _call_provider(inp: RecoveryLLMInput) -> RecoveryLLMOutput | None:
    if not settings.llm_endpoint:
        return None
    payload = {
        "task": "recovery_assist",
        "model": settings.llm_text_model or None,
        "input": inp.model_dump(mode="json"),
    }
    data = call_llm("recovery_assist", payload, settings.llm_timeout_ms)
    if data is None:
        return None
    try:
        out = RecoveryLLMOutput.model_validate(data)
        out.source = "llm"
        return out
    except Exception:
        return None


def assist_recovery(inp: RecoveryLLMInput, *, call_count: int = 0) -> RecoveryLLMOutput | None:
    """Resolve ambiguity only; returns None when feature is disabled or budget exhausted."""
    if (
        not settings.llm_enabled
        or not settings.llm_recovery_assist
        or call_count >= settings.llm_max_calls_per_step
    ):
        return None
    cache = _read_cache()
    k = _key(inp)
    if k in cache:
        try:
            return RecoveryLLMOutput.model_validate(cache[k])
        except Exception:
            pass
    out = _call_provider(inp) or _fallback(inp)
    cache[k] = out.model_dump(mode="json")
    _write_cache(cache)
    return out
