"""Configuration for Skill Pack Builder LLM calls."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class PackLLMConfig:
    endpoint: str
    model: str


def resolved_pack_llm_config() -> PackLLMConfig:
    """Resolve Skill Pack Builder LLM endpoint and model from settings."""
    return PackLLMConfig(endpoint=settings.llm_pack_endpoint, model=settings.llm_pack_model)
