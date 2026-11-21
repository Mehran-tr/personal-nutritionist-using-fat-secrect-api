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

    # Per attempt. Worst case per call ~ attempts x timeout, so keep both small.
    timeout_seconds: float = Field(default=5.0, gt=0)
    connect_timeout_seconds: float = Field(default=2.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=0.2, ge=0)
    token_refresh_margin_seconds: int = Field(default=60, ge=0)


class CacheSettings(BaseModel):
    backend: Literal["redis", "memory"] = "redis"
    redis_url: str = "redis://localhost:6379/0"
    # Redis is a cache: if it's slow, give up fast and fall back.
    redis_socket_timeout_seconds: float = Field(default=0.5, gt=0)
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
    # Recycle before typical proxy/firewall idle cut-offs (e.g. 30-60 min).
    pool_recycle_seconds: int = Field(default=1800, ge=60)
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    # Server-side guard rails: a runaway query or a forgotten transaction can't
    # hold locks and connections forever.
    statement_timeout_ms: int = Field(default=5000, ge=100)
    idle_in_transaction_timeout_ms: int = Field(default=10_000, ge=1000)
    slow_query_ms: int = Field(default=200, ge=1)


class AuthSettings(BaseModel):
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "nutritionist"
    jwt_audience: str = "nutritionist-api"
    access_token_ttl_minutes: int = Field(default=30, ge=1, le=24 * 60)

    # Threads for password hashing; 0 = auto (CPU count - 1, at least 1). Argon2
    # is deliberately CPU-heavy. Unbounded, a login burst takes every core and
    # starves the event loop, so *all* other requests stall too.
    hashing_threads: int = Field(default=0, ge=0, le=64)

    # Login brute-force protection ("max retry + jail").
    login_max_failures_per_account_and_ip: int = Field(default=5, ge=1)
    login_lockout_seconds: int = Field(default=15 * 60, ge=1)
    login_max_failures_per_account: int = Field(default=20, ge=1)  # across all IPs
    login_account_window_seconds: int = Field(default=60 * 60, ge=1)

    @model_validator(mode="after")
    def _secret_is_not_trivial(self) -> "AuthSettings":
        # Length alone accepts "aaaa…": require some variety as well (generate with
        # `python -c "import secrets; print(secrets.token_urlsafe(48))"`).
        if len(set(self.jwt_secret.get_secret_value())) < 12:
            raise ValueError("AUTH__JWT_SECRET is too weak: use a random secret.")
        return self


PRIVATE_NETWORKS = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128"]


class SecuritySettings(BaseModel):
    # Hosts this API answers for (Host header). "*" only outside production.
    allowed_hosts: list[str] = ["*"]
    # HSTS: only meaningful when served over HTTPS (TLS terminates at the proxy).
    hsts_enabled: bool = False
    hsts_max_age_seconds: int = Field(default=63_072_000, ge=0)  # 2 years
    max_request_body_bytes: int = Field(default=64 * 1024, ge=1024)

    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = Field(default=300, ge=1)  # per client IP, all routes
    auth_rate_limit_per_minute: int = Field(default=10, ge=1)  # per client IP, /auth/*

    # Networks allowed to call internal endpoints (readiness probe).
    internal_networks: list[str] = PRIVATE_NETWORKS


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


class PerformanceSettings(BaseModel):
    gzip_enabled: bool = True
    gzip_min_bytes: int = Field(default=1024, ge=0)  # tiny bodies aren't worth it
    etag_enabled: bool = True
    background_concurrency: int = Field(default=4, ge=1)  # e.g. parallel LLM phrasings
    max_entries_per_day: int = Field(default=200, ge=1)
    max_batch_items: int = Field(default=20, ge=1, le=100)


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
    security: SecuritySettings = SecuritySettings()
    performance: PerformanceSettings = PerformanceSettings()

    @model_validator(mode="after")
    def _production_is_hardened(self) -> "Settings":
        if self.environment is not Environment.PRODUCTION:
            return self
        problems = []
        if "*" in self.security.allowed_hosts:
            problems.append("SECURITY__ALLOWED_HOSTS must list real hostnames")
        if not self.security.hsts_enabled:
            problems.append("SECURITY__HSTS_ENABLED must be true")
        if not self.security.rate_limit_enabled:
            problems.append("SECURITY__RATE_LIMIT_ENABLED must be true")
        if self.cache.backend != "redis":
            problems.append("CACHE__BACKEND must be redis (shared limits across replicas)")
        if not self.log_json:
            problems.append("LOG_JSON must be true (centralized logging)")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.environment is not Environment.PRODUCTION
