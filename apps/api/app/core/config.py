import re
from functools import lru_cache
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
