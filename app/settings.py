from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ReliefOS Disaster Response"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    auth_mode: Literal["local", "cognito"] = "local"
    storage_backend: Literal["memory", "dynamodb"] = "memory"
    case_access_secret: str = "development-only-change-me"  # noqa: S105

    aws_region: str = "us-east-1"
    dynamodb_endpoint_url: str | None = None
    cases_table: str = "reliefos-cases"
    people_table: str = "reliefos-people"
    responders_table: str = "reliefos-responders"
    shelters_table: str = "reliefos-shelters"
    missions_table: str = "reliefos-missions"
    audit_table: str = "reliefos-audit"

    media_bucket: str | None = None
    case_queue_url: str | None = None
    max_media_bytes: int = Field(default=25_000_000, ge=1_000_000, le=250_000_000)
    local_media_path: Path = Path("runtime/media")

    ai_triage_enabled: bool = False
    bedrock_model_id: str | None = None
    bedrock_guardrail_id: str | None = None
    bedrock_guardrail_version: str | None = None

    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.app_env == "production" and self.auth_mode == "local":
            raise ValueError("AUTH_MODE=local is forbidden when APP_ENV=production")
        if self.app_env == "production" and (
            self.case_access_secret == "development-only-change-me"
            or len(self.case_access_secret) < 32
        ):
            raise ValueError("CASE_ACCESS_SECRET must be a unique value of at least 32 characters")
        if self.auth_mode == "cognito":
            if not self.cognito_user_pool_id or not self.cognito_app_client_id:
                raise ValueError("Cognito mode requires user pool and app client IDs")
        if self.ai_triage_enabled and not self.bedrock_model_id:
            raise ValueError("AI triage requires BEDROCK_MODEL_ID")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
