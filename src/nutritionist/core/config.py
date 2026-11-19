"""Typed application settings.

All configuration comes from environment variables (or a local `.env`).
Nested groups use a double underscore, e.g. ``FATSECRET__CLIENT_ID``.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class FatSecretSettings(BaseModel):
    client_id: SecretStr
    client_secret: SecretStr
    scopes: str = "premier"

    token_url: str = "https://oauth.fatsecret.com/connect/token"
    base_url: str = "https://platform.fatsecret.com/rest"

    # Endpoint versions are pinned explicitly. Upgrading one is a deliberate change,
    # backed by refreshed contract fixtures in tests/contract/fatsecret/fixtures.
    search_path: str = "foods/search/v6"
    food_get_path: str = "food/v6"
    barcode_path: str = "food/barcode/find-by-id/v1"

    region: str | None = None
    language: str | None = None

    timeout_seconds: float = Field(default=10.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=0.2, ge=0)
    token_refresh_margin_seconds: int = Field(default=60, ge=0)


class CacheSettings(BaseModel):
    backend: Literal["redis", "memory"] = "redis"
    redis_url: str = "redis://localhost:6379/0"
    food_ttl_seconds: int = Field(default=60 * 60 * 24, ge=0)
    search_ttl_seconds: int = Field(default=60 * 60, ge=0)


class DatabaseSettings(BaseSettings):
    """Also loadable on its own (Alembic needs the DB URL, not fatsecret keys)."""

    model_config = SettingsConfigDict(env_prefix="DATABASE__", env_file=".env", extra="ignore")

    url: str = "postgresql+asyncpg://nutritionist:nutritionist@localhost:5432/nutritionist"
    echo: bool = False
    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout_seconds: float = Field(default=10.0, gt=0)


class AuthSettings(BaseModel):
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "nutritionist"
    jwt_audience: str = "nutritionist-api"
    access_token_ttl_minutes: int = Field(default=30, ge=1, le=24 * 60)


class CoachSettings(BaseModel):
    """LLM phrasing of coach insights. Off by default: the coach works without it."""

    llm_enabled: bool = False
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    model: str = "claude-haiku-5-5"
    max_tokens: int = Field(default=300, ge=50, le=1000)
    timeout_seconds: float = Field(default=8.0, gt=0)
    cache_ttl_seconds: int = Field(default=60 * 60 * 24 * 7, ge=0)

    @model_validator(mode="after")
    def _key_required_when_enabled(self) -> "CoachSettings":
        if self.llm_enabled and not self.anthropic_api_key:
            raise ValueError("COACH__ANTHROPIC_API_KEY is required when COACH__LLM_ENABLED=true")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "nutritionist"
    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"
    log_json: bool = True
    api_prefix: str = "/api/v1"

    fatsecret: FatSecretSettings
    auth: AuthSettings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    cache: CacheSettings = CacheSettings()
    coach: CoachSettings = CoachSettings()

    @property
    def docs_enabled(self) -> bool:
        return self.environment is not Environment.PRODUCTION
