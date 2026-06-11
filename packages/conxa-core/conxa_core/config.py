"""Central configuration for the skill platform service."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def state_base_dir() -> Path:
    """Writable base directory for generated runtime state (``data/``, ``output/``).

    Frozen builds are installed under a read-only location (e.g. ``Program Files``
    on Windows), so state cannot live next to the bundled package. Redirect it to
    the user profile (``~/.conxa``), consistent with the deps/runtime convention.
    Development keeps the in-repo source default so ``pip install -e`` and
    ``python backend.py`` workflows are unchanged.
    """
    if getattr(sys, "frozen", False):
        return Path(os.path.expanduser("~/.conxa"))
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ProviderConfig:
    """Single LLM provider configuration (one key per instance)."""
    provider: str
    endpoint: str
    api_key: str
    text_model: str
    vision_model: str


def _provider_env(name: str) -> AliasChoices:
    return AliasChoices(f"SKILL_{name}", name)


class Settings(BaseSettings):
    """Environment-driven settings; safe defaults for local MVP."""

    model_config = SettingsConfigDict(
        env_prefix="SKILL_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = state_base_dir() / "data"
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
    build_artifact_upload_max_bytes: int = 250 * 1024 * 1024

    # Clerk authentication. Local development leaves this disabled; production
    # deployments should set SKILL_AUTH_REQUIRED=true and the Clerk values below.
    auth_required: bool = False
    clerk_issuer: str = ""
    clerk_jwks_url: str = ""
    clerk_authorized_parties: str = ""
    clerk_audience: str = ""
    clerk_secret_key: str = Field(default="", validation_alias="CLERK_SECRET_KEY")
    api_proxy_shared_secret: str = ""

    # Metered LLM proxy used by Build Studio. Quota is per org per calendar month
    # (input + output tokens). 0 disables enforcement. The proxy only accepts
    # requests carrying the X-Conxa-Client header below.
    llm_proxy_monthly_token_quota: int = 5_000_000
    llm_proxy_client_header: str = "build-studio"
    entitlements_enforce_compile: bool = False
    entitlements_enforce_human_edit: bool = False
    entitlements_enforce_installers: bool = False
    entitlements_reservation_ttl_secs: int = 30 * 60

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
    groq_enabled: bool = Field(default=True, validation_alias=_provider_env("GROQ_ENABLED"))
    groq_endpoint: str = Field(
        default="https://api.groq.com/openai/v1",
        validation_alias=_provider_env("GROQ_ENDPOINT"),
    )
    groq_api_keys: str = Field(default="", validation_alias=_provider_env("GROQ_API_KEYS"))
    groq_text_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=_provider_env("GROQ_TEXT_MODEL"),
    )
    groq_vision_model: str = Field(
        default="meta-llama/llama-4-scout-17b-16e-instruct",
        validation_alias=_provider_env("GROQ_VISION_MODEL"),
    )

    google_ai_studio_enabled: bool = Field(
        default=True,
        validation_alias=_provider_env("GOOGLE_AI_STUDIO_ENABLED"),
    )
    google_ai_studio_endpoint: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai",
        validation_alias=_provider_env("GOOGLE_AI_STUDIO_ENDPOINT"),
    )
    google_ai_studio_api_keys: str = Field(
        default="",
        validation_alias=_provider_env("GOOGLE_AI_STUDIO_API_KEYS"),
    )
    google_ai_studio_text_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=_provider_env("GOOGLE_AI_STUDIO_TEXT_MODEL"),
    )
    google_ai_studio_vision_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=_provider_env("GOOGLE_AI_STUDIO_VISION_MODEL"),
    )

    nvidia_nim_enabled: bool = Field(
        default=True,
        validation_alias=_provider_env("NVIDIA_NIM_ENABLED"),
    )
    nvidia_nim_endpoint: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        validation_alias=_provider_env("NVIDIA_NIM_ENDPOINT"),
    )
    nvidia_nim_api_keys: str = Field(
        default="",
        validation_alias=_provider_env("NVIDIA_NIM_API_KEYS"),
    )
    nvidia_nim_text_model: str = Field(
        default="meta/llama-4-maverick-17b-128e-instruct",
        validation_alias=_provider_env("NVIDIA_NIM_TEXT_MODEL"),
    )
    nvidia_nim_vision_model: str = Field(
        default="meta/llama-3.2-90b-vision-instruct",
        validation_alias=_provider_env("NVIDIA_NIM_VISION_MODEL"),
    )

    cerebras_enabled: bool = Field(
        default=False,
        validation_alias=_provider_env("CEREBRAS_ENABLED"),
    )
    cerebras_endpoint: str = Field(
        default="https://api.cerebras.ai/v1",
        validation_alias=_provider_env("CEREBRAS_ENDPOINT"),
    )
    cerebras_api_keys: str = Field(
        default="",
        validation_alias=_provider_env("CEREBRAS_API_KEYS"),
    )
    cerebras_text_model: str = Field(
        default="llama-4-scout-17b-16e-instruct",
        validation_alias=_provider_env("CEREBRAS_TEXT_MODEL"),
    )
    cerebras_vision_model: str = Field(
        default="",
        validation_alias=_provider_env("CEREBRAS_VISION_MODEL"),
    )

    together_enabled: bool = Field(
        default=False,
        validation_alias=_provider_env("TOGETHER_ENABLED"),
    )
    together_endpoint: str = Field(
        default="https://api.together.xyz/v1",
        validation_alias=_provider_env("TOGETHER_ENDPOINT"),
    )
    together_api_keys: str = Field(default="", validation_alias=_provider_env("TOGETHER_API_KEYS"))
    together_text_model: str = Field(
        default="meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        validation_alias=_provider_env("TOGETHER_TEXT_MODEL"),
    )
    together_vision_model: str = Field(
        default="meta-llama/Llama-4-Scout-17B-16E-Instruct",
        validation_alias=_provider_env("TOGETHER_VISION_MODEL"),
    )

    openrouter_enabled: bool = Field(
        default=False,
        validation_alias=_provider_env("OPENROUTER_ENABLED"),
    )
    openrouter_endpoint: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=_provider_env("OPENROUTER_ENDPOINT"),
    )
    openrouter_api_keys: str = Field(
        default="",
        validation_alias=_provider_env("OPENROUTER_API_KEYS"),
    )
    openrouter_text_model: str = Field(
        default="deepseek/deepseek-v3:free",
        validation_alias=_provider_env("OPENROUTER_TEXT_MODEL"),
    )
    openrouter_vision_model: str = Field(
        default="meta-llama/llama-4-scout:free",
        validation_alias=_provider_env("OPENROUTER_VISION_MODEL"),
    )

    mistral_enabled: bool = Field(
        default=False,
        validation_alias=_provider_env("MISTRAL_ENABLED"),
    )
    mistral_endpoint: str = Field(
        default="https://api.mistral.ai/v1",
        validation_alias=_provider_env("MISTRAL_ENDPOINT"),
    )
    mistral_api_keys: str = Field(default="", validation_alias=_provider_env("MISTRAL_API_KEYS"))
    mistral_text_model: str = Field(
        default="mistral-large-latest",
        validation_alias=_provider_env("MISTRAL_TEXT_MODEL"),
    )
    mistral_vision_model: str = Field(
        default="pixtral-large-latest",
        validation_alias=_provider_env("MISTRAL_VISION_MODEL"),
    )

    # Router behavior
    llm_router_cooldown_secs: int = 60
    llm_router_max_retries: int = 3
    llm_router_request_timeout_ms: int = 30000
    llm_router_prefer_fast_for_text: bool = True

    # Razorpay payment gateway. These intentionally do not use the SKILL_ prefix.
    razorpay_key_id: str = Field(default="", validation_alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field(default="", validation_alias="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str = Field(default="", validation_alias="RAZORPAY_WEBHOOK_SECRET")
    razorpay_starter_plan_id: str = Field(default="", validation_alias="RAZORPAY_STARTER_PLAN_ID")
    razorpay_pro_plan_id: str = Field(default="", validation_alias="RAZORPAY_PRO_PLAN_ID")

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
