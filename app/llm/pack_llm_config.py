"""Provider selection helpers for Skill Pack Builder LLM calls."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class PackLLMConfig:
    provider: str
    endpoint: str
    model: str


_GEMINI_DEPRECATED_MODEL_REPLACEMENTS = {
    "gemini-1.5-flash": "gemini-2.5-flash",
    "gemini-1.5-flash-latest": "gemini-2.5-flash",
    "models/gemini-1.5-flash": "gemini-2.5-flash",
}


def _resolved_gemini_model(model: str) -> str:
    normalized = str(model or "").strip()
    return _GEMINI_DEPRECATED_MODEL_REPLACEMENTS.get(normalized, normalized)


def selected_pack_provider() -> str:
    provider = str(settings.pack_llm_provider or "").strip().lower()
    if provider in {"nvidia", "gemini"}:
        return provider

    endpoint = str(settings.pack_llm_endpoint or "").strip().lower()
    if "generativelanguage.googleapis.com" in endpoint:
        return "gemini"
    if "integrate.api.nvidia.com" in endpoint:
        return "nvidia"
    return "custom"


def resolved_pack_llm_config() -> PackLLMConfig:
    provider = selected_pack_provider()
    if provider == "gemini":
        endpoint = str(settings.pack_llm_gemini_endpoint or "").strip()
        model = _resolved_gemini_model(settings.pack_llm_gemini_model)
    elif provider == "nvidia":
        endpoint = str(settings.pack_llm_nvidia_endpoint or "").strip()
        model = str(settings.pack_llm_nvidia_model or "").strip()
    else:
        endpoint = str(settings.pack_llm_endpoint or "").strip()
        model = str(settings.pack_llm_model or "").strip()

    return PackLLMConfig(provider=provider, endpoint=endpoint, model=model)
