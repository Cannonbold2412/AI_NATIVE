"""Central configuration for the skill platform service."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings; safe defaults for local MVP."""

    model_config = SettingsConfigDict(env_prefix="SKILL_", env_file=".env", extra="ignore")

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    host: str = "127.0.0.1"
    port: int = 8000
    default_action_timeout_ms: int = 5000
    screenshot_jpeg_quality: int = 78
    llm_enabled: bool = True
    llm_semantic_enrichment: bool = True
    llm_vision_reasoning: bool = True
    llm_recovery_assist: bool = True
    llm_max_calls_per_step: int = 1
    llm_timeout_ms: int = 2000
    # Vision multimodal requests (large payloads) need a separate, usually longer, timeout.
    llm_vision_timeout_ms: int = 120000
    llm_anchor_vision: bool = True

    # Optional provider endpoint for helper calls. If unset, deterministic fallback is used.
    llm_endpoint: str = ""
    llm_api_key: str = ""
    llm_api_keys: str = ""
    llm_text_model: str = ""
    # NVIDIA / OpenAI-style VLMs (e.g. google/gemma-4-31b-it) via chat completions + image attachment.
    llm_vision_model: str = "google/gemma-4-31b-it"
    llm_debug: bool = False

    @field_validator("llm_timeout_ms", mode="before")
    @classmethod
    def _enforce_min_llm_timeout(cls, value: object) -> int:
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            timeout = 2000
        return max(2000, timeout)

    @field_validator("llm_vision_timeout_ms", mode="before")
    @classmethod
    def _enforce_min_vision_timeout(cls, value: object) -> int:
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            timeout = 120000
        return max(10000, timeout)


settings = Settings()
