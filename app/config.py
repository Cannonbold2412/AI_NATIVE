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
    # When multiple SKILL_LLM_API_KEYS are set, anchor_vision fires one request per key in parallel and uses the first success.
    llm_parallel_fanout_anchor_vision: bool = True

    # Optional provider endpoint for helper calls. If unset, deterministic fallback is used.
    llm_endpoint: str = ""
    llm_api_key: str = ""
    llm_api_keys: str = ""
    llm_text_model: str = ""
    # NVIDIA / OpenAI-style VLMs (e.g. google/gemma-4-31b-it) via chat completions + image attachment.
    llm_vision_model: str = "google/gemma-4-31b-it"
    llm_debug: bool = False
    pack_llm_enabled: bool = True
    # Selects named Skill Pack Builder provider settings below. Supported: nvidia, gemini.
    # If empty, the legacy SKILL_PACK_LLM_ENDPOINT / MODEL / API_KEY(S) values are used directly.
    pack_llm_provider: str = ""
    pack_llm_endpoint: str = ""
    pack_llm_api_key: str = ""
    # Comma-separated keys; successive pack LLM calls rotate (thread-safe), same pattern as SKILL_LLM_API_KEYS in app/llm/client.py.
    pack_llm_api_keys: str = ""
    pack_llm_model: str = ""
    pack_llm_nvidia_endpoint: str = "https://integrate.api.nvidia.com/v1"
    pack_llm_nvidia_api_key: str = ""
    pack_llm_nvidia_api_keys: str = ""
    pack_llm_nvidia_model: str = "z-ai/glm-5.1"
    pack_llm_gemini_endpoint: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    pack_llm_gemini_api_key: str = ""
    pack_llm_gemini_api_keys: str = ""
    pack_llm_gemini_model: str = "gemini-2.5-flash"
    pack_llm_max_attempts: int = 1
    # Skill structuring often needs several minutes; low values cause client TimeoutError before the
    # gateway can respond (debug logs: 120s capped runs vs ~300s gateway behavior on integrate.api.nvidia.com).
    pack_llm_timeout_ms: int = 600000
    # Chat-completions sampling for Skill Pack Builder (structuring vs skill.md prose).
    pack_llm_structure_temperature: float = 0.0
    pack_llm_structure_max_tokens: int | None = None
    pack_llm_markdown_temperature: float = 0.15
    pack_llm_markdown_max_tokens: int = 8000
    pack_llm_top_p: float | None = None
    pack_recovery_vision_enabled: bool = False
    # Directory name at project root for generated bundles (default skill_package). Overrides .skill_bundle_root after UI rename.
    package_bundle_root: str = "skill_package"
    environment: str = "local"

    # Public API / browser boundary.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cors_preview_origin_regex: str = r"https://.*\.vercel\.app"
    max_json_body_bytes: int = 1_000_000

    # Clerk authentication. Local development leaves this disabled; production
    # deployments should set SKILL_AUTH_REQUIRED=true and the Clerk values below.
    auth_required: bool = False
    clerk_issuer: str = ""
    clerk_jwks_url: str = ""
    clerk_authorized_parties: str = ""
    clerk_audience: str = ""

    # Production backing services. The local MVP still has file-backed fallbacks.
    database_url: str = ""
    redis_url: str = ""
    blob_read_write_token: str = ""
    worker_queue_name: str = "ai-native-jobs"
    worker_dead_letter_queue_name: str = "ai-native-jobs-dlq"

    # Billing and app redirects.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    app_url: str = "http://localhost:5173"

    @field_validator("package_bundle_root", mode="before")
    @classmethod
    def _strip_package_bundle_root(cls, value: object) -> str:
        return str(value or "").strip() or "skill_package"

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _strip_cors_allowed_origins(cls, value: object) -> str:
        return str(value or "").strip()

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

    @property
    def clerk_authorized_party_values(self) -> list[str]:
        return [item.strip() for item in self.clerk_authorized_parties.split(",") if item.strip()]

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

    @field_validator("pack_llm_timeout_ms", mode="before")
    @classmethod
    def _enforce_min_pack_timeout(cls, value: object) -> int:
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            timeout = 600000
        return max(600000, timeout)

    @field_validator("pack_llm_provider", mode="before")
    @classmethod
    def _normalize_pack_provider(cls, value: object) -> str:
        provider = str(value or "").strip().lower()
        return provider if provider in {"", "nvidia", "gemini"} else ""

    @field_validator("pack_llm_max_attempts", mode="before")
    @classmethod
    def _normalize_pack_max_attempts(cls, value: object) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return 1
        return max(1, min(n, 10))

    @field_validator("pack_llm_structure_temperature", mode="before")
    @classmethod
    def _clamp_pack_structure_temperature(cls, value: object) -> float:
        try:
            t = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(2.0, t))

    @field_validator("pack_llm_markdown_temperature", mode="before")
    @classmethod
    def _clamp_pack_markdown_temperature(cls, value: object) -> float:
        try:
            t = float(value)
        except (TypeError, ValueError):
            return 0.15
        return max(0.0, min(2.0, t))

    @field_validator("pack_llm_top_p", mode="before")
    @classmethod
    def _normalize_pack_llm_top_p(cls, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            t = float(value)
        except (TypeError, ValueError):
            return None
        if t <= 0.0 or t > 1.0:
            return None
        return t

    @field_validator("pack_llm_structure_max_tokens", mode="before")
    @classmethod
    def _normalize_pack_structure_max_tokens(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        if n < 1:
            return None
        return min(n, 200_000)

    @field_validator("pack_llm_markdown_max_tokens", mode="before")
    @classmethod
    def _normalize_pack_markdown_max_tokens(cls, value: object) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return 4000
        return max(1, min(n, 200_000))


settings = Settings()
