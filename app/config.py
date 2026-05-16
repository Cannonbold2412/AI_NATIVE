"""Central configuration for the skill platform service."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings; safe defaults for local MVP."""

    model_config = SettingsConfigDict(env_prefix="SKILL_", env_file=".env", extra="ignore")

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    host: str = "127.0.0.1"
    port: int = 8000
    default_action_timeout_ms: int = 5000
    screenshot_jpeg_quality: int = 78
    # LLM toggles and shared settings
    llm_enabled: bool = True
    llm_semantic_enrichment: bool = True
    llm_vision_reasoning: bool = True
    llm_recovery_assist: bool = True
    llm_max_calls_per_step: int = 1
    llm_anchor_vision: bool = True
    llm_parallel_fanout_anchor_vision: bool = True
    llm_debug: bool = False

    # LLM 1: Skill Pack Structuring (compile time)
    llm_pack_enabled: bool = True
    llm_pack_endpoint: str = ""
    llm_pack_api_key: str = ""
    llm_pack_model: str = ""
    llm_pack_timeout_ms: int = 600000
    llm_pack_max_attempts: int = 1
    llm_pack_structure_temperature: float = 0.0
    llm_pack_structure_max_tokens: int | None = None
    llm_pack_markdown_temperature: float = 0.15
    llm_pack_markdown_max_tokens: int = 8000
    llm_pack_top_p: float | None = None

    # LLM 2: Vision (anchor generation + visual recovery, multimodal)
    llm_vision_endpoint: str = ""
    llm_vision_api_key: str = ""
    llm_vision_model: str = ""
    llm_vision_timeout_ms: int = 120000

    # LLM 3: Runtime Text (semantic enrichment, intent generation, recovery assist)
    llm_text_endpoint: str = ""
    llm_text_api_key: str = ""
    llm_text_model: str = ""
    llm_text_timeout_ms: int = 2000
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

    # GitHub OAuth integration. These intentionally do not use the SKILL_ prefix.
    github_oauth_client_id: str = Field(default="", validation_alias="GITHUB_OAUTH_CLIENT_ID")
    github_oauth_client_secret: str = Field(default="", validation_alias="GITHUB_OAUTH_CLIENT_SECRET")
    github_oauth_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/integrations/github/callback",
        validation_alias="GITHUB_OAUTH_REDIRECT_URI",
    )
    github_oauth_frontend_origin: str = Field(
        default="http://localhost:3000",
        validation_alias="GITHUB_OAUTH_FRONTEND_ORIGIN",
    )

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
