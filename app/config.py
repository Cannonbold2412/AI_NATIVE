"""Central configuration for the skill platform service."""

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ProviderConfig:
    """Single LLM provider configuration (one key per instance)."""
    provider: str
    endpoint: str
    api_key: str
    text_model: str
    vision_model: str


class Settings(BaseSettings):
    """Environment-driven settings; safe defaults for local MVP."""

    model_config = SettingsConfigDict(env_prefix="SKILL_", env_file=".env", extra="ignore")

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    host: str = "127.0.0.1"
    port: int = 8000
    default_action_timeout_ms: int = 5000
    screenshot_jpeg_quality: int = 78
    # LLM shared settings (no per-feature toggles; LLM is mandatory and routed via the multi-provider pool)
    llm_max_calls_per_step: int = 1
    llm_parallel_fanout_anchor_vision: bool = True
    llm_debug: bool = False

    # Timeouts (no legacy single-endpoint config — endpoints come from per-provider settings below)
    llm_vision_timeout_ms: int = 120000
    llm_text_timeout_ms: int = 2000

    # Pack structuring + skill.md tuning (calls Text endpoint above)
    llm_pack_enabled: bool = True
    llm_pack_timeout_ms: int = 600000
    llm_pack_max_attempts: int = 1
    llm_pack_structure_temperature: float = 0.0
    llm_pack_structure_max_tokens: int | None = None
    llm_pack_markdown_temperature: float = 0.15
    llm_pack_markdown_max_tokens: int = 8000
    llm_pack_top_p: float | None = None
    pack_recovery_vision_enabled: bool = True

    # Selector compilation tuning (calls Text endpoint above)
    llm_selector_timeout_ms: int = 60000
    llm_selector_candidates: int = 8          # candidates to request per element

    # Selector cache (Phase 1)
    selector_cache_ttl_days: int = 30
    selector_cache_enabled: bool = True

    # DOM snapshot (Phase 2)
    snapshot_dedup_enabled: bool = True
    snapshot_surrounding_text_radius_px: int = 200
    snapshot_capture_a11y: bool = True
    snapshot_retention_days: int = 30
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

    # Tracking HMAC secret for signing runtime telemetry tokens.
    # Set SKILL_TRACKING_HMAC_SECRET in production to enable company-scoped tracking.
    tracking_hmac_secret: str = ""

    # Multi-provider LLM key pool (free-tier rotation)
    groq_enabled: bool = True
    groq_endpoint: str = "https://api.groq.com/openai/v1"
    groq_api_keys: str = ""
    groq_text_model: str = "llama-3.3-70b-versatile"
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    google_ai_studio_enabled: bool = True
    google_ai_studio_endpoint: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    google_ai_studio_api_keys: str = ""
    google_ai_studio_text_model: str = "gemini-2.5-flash"
    google_ai_studio_vision_model: str = "gemini-2.5-flash"

    nvidia_nim_enabled: bool = True
    nvidia_nim_endpoint: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_api_keys: str = ""
    nvidia_nim_text_model: str = "meta/llama-4-maverick-17b-128e-instruct"
    nvidia_nim_vision_model: str = "meta/llama-3.2-90b-vision-instruct"

    cerebras_enabled: bool = False
    cerebras_endpoint: str = "https://api.cerebras.ai/v1"
    cerebras_api_keys: str = ""
    cerebras_text_model: str = "llama-4-scout-17b-16e-instruct"
    cerebras_vision_model: str = ""

    together_enabled: bool = False
    together_endpoint: str = "https://api.together.xyz/v1"
    together_api_keys: str = ""
    together_text_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"
    together_vision_model: str = "meta-llama/Llama-4-Scout-17B-16E-Instruct"

    openrouter_enabled: bool = False
    openrouter_endpoint: str = "https://openrouter.ai/api/v1"
    openrouter_api_keys: str = ""
    openrouter_text_model: str = "deepseek/deepseek-v3:free"
    openrouter_vision_model: str = "meta-llama/llama-4-scout:free"

    mistral_enabled: bool = False
    mistral_endpoint: str = "https://api.mistral.ai/v1"
    mistral_api_keys: str = ""
    mistral_text_model: str = "mistral-large-latest"
    mistral_vision_model: str = "pixtral-large-latest"

    # Router behavior
    llm_router_cooldown_secs: int = 60
    llm_router_max_retries: int = 3
    llm_router_request_timeout_ms: int = 30000
    llm_router_prefer_fast_for_text: bool = True

    # Razorpay payment gateway. These intentionally do not use the SKILL_ prefix.
    razorpay_key_id: str = Field(default="", validation_alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field(default="", validation_alias="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str = Field(default="", validation_alias="RAZORPAY_WEBHOOK_SECRET")

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

    # Legacy single-endpoint accessors — derived from the multi-provider pool so out-of-scope
    # callers (e.g. services/skill_pack/llm.py which does its own HTTP) keep working without
    # additional env vars. NOT user-facing BC; just a runtime adapter pointing at the first
    # enabled provider. Recorder+compile paths use the router directly and never read these.
    @property
    def llm_text_endpoint(self) -> str:
        providers = self.enabled_llm_providers()
        return providers[0].endpoint if providers else ""

    @property
    def llm_text_model(self) -> str:
        providers = self.enabled_llm_providers()
        return providers[0].text_model if providers else ""

    @property
    def llm_text_api_key(self) -> str:
        providers = self.enabled_llm_providers()
        return providers[0].api_key if providers else ""

    @property
    def llm_vision_endpoint(self) -> str:
        providers = [p for p in self.enabled_llm_providers() if p.vision_model]
        return providers[0].endpoint if providers else ""

    @property
    def llm_vision_model(self) -> str:
        providers = [p for p in self.enabled_llm_providers() if p.vision_model]
        return providers[0].vision_model if providers else ""

    @property
    def llm_vision_api_key(self) -> str:
        providers = [p for p in self.enabled_llm_providers() if p.vision_model]
        return providers[0].api_key if providers else ""

    @property
    def clerk_authorized_party_values(self) -> list[str]:
        return [item.strip() for item in self.clerk_authorized_parties.split(",") if item.strip()]

    def _split_api_keys(self, value: str) -> list[str]:
        """Parse comma-separated API keys, handling quotes and bearer prefixes."""
        keys: list[str] = []
        for item in str(value or "").split(","):
            key = item.strip().strip('"').strip("'").strip()
            if key.lower().startswith("bearer "):
                key = key[7:].strip()
            if key:
                keys.append(key)
        return keys

    def enabled_llm_providers(self) -> list[ProviderConfig]:
        """Load all enabled LLM providers with their API keys, returning a flat pool."""
        providers_config = [
            ("groq", self.groq_enabled, self.groq_endpoint, self.groq_api_keys,
             self.groq_text_model, self.groq_vision_model),
            ("google_ai_studio", self.google_ai_studio_enabled, self.google_ai_studio_endpoint,
             self.google_ai_studio_api_keys, self.google_ai_studio_text_model,
             self.google_ai_studio_vision_model),
            ("nvidia_nim", self.nvidia_nim_enabled, self.nvidia_nim_endpoint,
             self.nvidia_nim_api_keys, self.nvidia_nim_text_model, self.nvidia_nim_vision_model),
            ("cerebras", self.cerebras_enabled, self.cerebras_endpoint,
             self.cerebras_api_keys, self.cerebras_text_model, self.cerebras_vision_model),
            ("together", self.together_enabled, self.together_endpoint,
             self.together_api_keys, self.together_text_model, self.together_vision_model),
            ("openrouter", self.openrouter_enabled, self.openrouter_endpoint,
             self.openrouter_api_keys, self.openrouter_text_model, self.openrouter_vision_model),
            ("mistral", self.mistral_enabled, self.mistral_endpoint,
             self.mistral_api_keys, self.mistral_text_model, self.mistral_vision_model),
        ]

        result: list[ProviderConfig] = []
        for provider_name, enabled, endpoint, api_keys_str, text_model, vision_model in providers_config:
            if not enabled or not endpoint:
                continue
            keys = self._split_api_keys(api_keys_str)
            for key in keys:
                result.append(ProviderConfig(
                    provider=provider_name,
                    endpoint=endpoint,
                    api_key=key,
                    text_model=text_model,
                    vision_model=vision_model,
                ))

        return result

    @model_validator(mode="after")
    def _require_at_least_one_provider(self) -> "Settings":
        """Fail fast if no LLM providers are enabled with API keys.

        Tests and bootstrap scripts can bypass with SKILL_ALLOW_NO_PROVIDERS=1.
        """
        if os.environ.get("SKILL_ALLOW_NO_PROVIDERS") == "1":
            return self
        if not self.enabled_llm_providers():
            raise ValueError(
                "No LLM providers enabled. Set at least one *_API_KEYS and "
                "*_ENABLED=true in .env (e.g. GROQ_API_KEYS=gsk_... + GROQ_ENABLED=true). "
                "See ROUTER_SETUP.md or .env.example for the full provider list."
            )
        return self

    @field_validator("llm_text_timeout_ms", mode="before")
    @classmethod
    def _enforce_min_text_timeout(cls, value: object) -> int:
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

    @field_validator("llm_pack_timeout_ms", mode="before")
    @classmethod
    def _enforce_min_pack_timeout(cls, value: object) -> int:
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            timeout = 600000
        return max(600000, timeout)

    @field_validator("llm_pack_max_attempts", mode="before")
    @classmethod
    def _normalize_llm_pack_max_attempts(cls, value: object) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return 1
        return max(1, min(n, 10))

    @field_validator("llm_pack_structure_temperature", mode="before")
    @classmethod
    def _clamp_llm_pack_structure_temperature(cls, value: object) -> float:
        try:
            t = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(2.0, t))

    @field_validator("llm_pack_markdown_temperature", mode="before")
    @classmethod
    def _clamp_llm_pack_markdown_temperature(cls, value: object) -> float:
        try:
            t = float(value)
        except (TypeError, ValueError):
            return 0.15
        return max(0.0, min(2.0, t))

    @field_validator("llm_pack_top_p", mode="before")
    @classmethod
    def _normalize_llm_pack_top_p(cls, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            t = float(value)
        except (TypeError, ValueError):
            return None
        if t <= 0.0 or t > 1.0:
            return None
        return t

    @field_validator("llm_pack_structure_max_tokens", mode="before")
    @classmethod
    def _normalize_llm_pack_structure_max_tokens(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        if n < 1:
            return None
        return min(n, 200_000)

    @field_validator("llm_pack_markdown_max_tokens", mode="before")
    @classmethod
    def _normalize_llm_pack_markdown_max_tokens(cls, value: object) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return 4000
        return max(1, min(n, 200_000))


settings = Settings()
