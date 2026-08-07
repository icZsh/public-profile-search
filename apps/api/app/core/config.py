import re
from functools import lru_cache
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite+pysqlite:///./prototype.db"
    redis_url: str = "redis://localhost:6379/0"
    prototype_hmac_key: str = "local-prototype-hmac-key-change-me-32"
    prototype_api_token: str = "local-prototype-token"
    prototype_admin_token: str = "local-prototype-admin-token"
    prototype_user_id: UUID = UUID("11111111-1111-4111-8111-111111111111")
    prototype_jobs_enabled: bool = True
    prototype_report_reads_enabled: bool = True
    prototype_allowed_origins: str = "http://localhost:3417"
    profile_url_encryption_key: SecretStr = SecretStr(
        "O_zdxoJwfVA_pJWpHc3vLwKtGqDRjdXyiNQjW4WLJew="
    )

    fixture_url: str = "https://profiles.example.test/alex-chen"
    fixture_linked_url: str = "https://code.example.test/alex-chen"
    fixture_eligibility_reference_id: UUID = UUID("22222222-2222-4222-8222-222222222222")
    github_provider_enabled: bool = True
    github_api_version: str = "2026-03-10"
    github_api_token: SecretStr | None = None
    professional_search_enabled: bool = True
    exa_people_search_enabled: bool = True
    exa_api_key: SecretStr | None = None
    github_people_search_enabled: bool = True
    professional_search_max_results_per_query: int = Field(default=5, ge=1, le=5)
    professional_search_max_github_profiles: int = Field(default=3, ge=1, le=3)
    professional_search_run_lease_seconds: int = Field(default=60, ge=15, le=180)
    adaptive_professional_search_max_names: int = Field(default=4, ge=1, le=6)
    adaptive_professional_search_max_queries: int = Field(default=20, ge=1, le=36)
    adaptive_professional_search_max_requests: int = Field(default=32, ge=1, le=64)
    adaptive_professional_search_max_profiles: int = Field(default=30, ge=1, le=50)
    adaptive_professional_search_budget_seconds: int = Field(default=120, ge=30, le=300)
    adaptive_professional_search_stagnation_queries: int = Field(default=3, ge=1, le=6)
    grounded_synthesis_enabled: bool = True
    grounded_synthesis_provider: str = "openai"
    openai_api_key: SecretStr | None = None
    openai_synthesis_model: str = "gpt-5.6-sol"
    openrouter_api_key: SecretStr | None = None
    openrouter_synthesis_model: str = "~deepseek/deepseek-v4-flash-latest"
    openrouter_http_referer: str = "http://localhost:3417"
    openrouter_app_title: str = "tracebrief local prototype"
    grounded_synthesis_reasoning_effort: str = Field(
        default="medium",
        validation_alias=AliasChoices(
            "GROUNDED_SYNTHESIS_REASONING_EFFORT",
            "OPENAI_SYNTHESIS_REASONING_EFFORT",
        ),
    )
    grounded_synthesis_max_output_tokens: int = Field(
        default=16_000,
        ge=800,
        le=32_000,
        validation_alias=AliasChoices(
            "GROUNDED_SYNTHESIS_MAX_OUTPUT_TOKENS",
            "OPENAI_SYNTHESIS_MAX_OUTPUT_TOKENS",
        ),
    )
    grounded_synthesis_max_attempts: int = Field(default=3, ge=1, le=5)
    grounded_synthesis_retry_backoff_seconds: int = Field(default=2, ge=0, le=30)
    grounded_synthesis_run_lease_seconds: int = Field(default=120, ge=30, le=300)
    grounded_synthesis_max_evidence_items: int = Field(default=40, ge=10, le=40)
    grounded_synthesis_max_evidence_characters: int = Field(
        default=60_000,
        ge=5_000,
        le=100_000,
    )
    maigret_enabled: bool = True
    maigret_catalog_manifest: str = "config/maigret-catalog-v0.6.3.json"
    maigret_run_lease_seconds: int = Field(default=180, ge=30, le=900)
    maigret_max_shards_per_job: int = Field(default=10, ge=1, le=40)
    safe_fetch_max_bytes: int = Field(default=262_144, ge=4_096, le=1_048_576)
    safe_fetch_total_timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)
    safe_fetch_connect_timeout_seconds: float = Field(default=3.0, ge=0.5, le=10.0)
    safe_fetch_read_timeout_seconds: float = Field(default=5.0, ge=0.5, le=15.0)
    eligibility_challenge_ttl_minutes: int = Field(default=30, ge=5, le=60)
    eligibility_review_ttl_hours: int = Field(default=24, ge=1, le=72)
    eligibility_approval_ttl_hours: int = Field(default=24, ge=1, le=168)
    eligibility_max_attempts: int = Field(default=5, ge=1, le=10)
    eligibility_check_cooldown_seconds: int = Field(default=3, ge=0, le=60)
    policy_version: str = "2026-07-23"
    completion_policy_id: str = "fast-brief-prototype-v1"
    retention_days: int = 30

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.prototype_allowed_origins.split(",") if origin]

    @model_validator(mode="after")
    def reject_prototype_auth_in_production(self) -> "Settings":
        if self.app_env.lower() in {"production", "prod"}:
            raise ValueError(
                "Local prototype authentication and evaluation providers cannot run in production"
            )
        if len(self.prototype_hmac_key) < 32:
            raise ValueError("PROTOTYPE_HMAC_KEY must contain at least 32 characters")
        try:
            Fernet(self.profile_url_encryption_key.get_secret_value().encode())
        except (TypeError, ValueError) as exc:
            raise ValueError("PROFILE_URL_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.github_api_version):
            raise ValueError("GITHUB_API_VERSION must be a YYYY-MM-DD value")
        if self.grounded_synthesis_reasoning_effort not in {
            "none",
            "low",
            "medium",
            "high",
        }:
            raise ValueError(
                "GROUNDED_SYNTHESIS_REASONING_EFFORT must be none, low, medium, or high"
            )
        if self.grounded_synthesis_provider not in {"openai", "openrouter"}:
            raise ValueError(
                "GROUNDED_SYNTHESIS_PROVIDER must be openai or openrouter"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
