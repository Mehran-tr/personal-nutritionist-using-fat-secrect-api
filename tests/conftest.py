import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from nutritionist.core.config import (
    AuthSettings,
    CacheSettings,
    DatabaseSettings,
    Environment,
    FatSecretSettings,
    Settings,
)

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "contract" / "fatsecret" / "fixtures"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://nutritionist:nutritionist@localhost:5432/nutritionist_test",
)
# In CI a missing database is a failure; locally, DB tests are skipped with a hint.
REQUIRE_DATABASE = os.environ.get("CI") == "true"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


@pytest.fixture
def fatsecret_settings() -> FatSecretSettings:
    return FatSecretSettings(
        client_id=SecretStr("test-client"),
        client_secret=SecretStr("test-secret"),
        token_url="https://oauth.test/connect/token",
        base_url="https://platform.test/rest",
        max_attempts=3,
        retry_backoff_seconds=0,
    )


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(jwt_secret=SecretStr("test-secret-that-is-at-least-32-bytes!"))


@pytest.fixture
def settings(fatsecret_settings: FatSecretSettings, auth_settings: AuthSettings) -> Settings:
    return Settings(
        environment=Environment.TEST,
        log_json=False,
        log_level="WARNING",
        fatsecret=fatsecret_settings,
        auth=auth_settings,
        database=DatabaseSettings(url=TEST_DATABASE_URL, pool_size=2, max_overflow=0),
        cache=CacheSettings(backend="memory"),
    )


# ------------------------------------------------------------------ database


async def _execute(*statements: str) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Build the schema with the real migrations (so they are tested too)."""
    try:
        asyncio.run(_execute("SELECT 1"))
    except Exception as exc:
        if REQUIRE_DATABASE:
            raise
        pytest.skip(f"PostgreSQL not reachable at {TEST_DATABASE_URL} ({exc.__class__.__name__})")
    asyncio.run(_execute("DROP SCHEMA public CASCADE", "CREATE SCHEMA public"))
    command.upgrade(alembic_config(), "head")


@pytest.fixture
def database(migrated_database: None) -> None:
    """A migrated, empty database for each test."""
    asyncio.run(_execute("TRUNCATE users, profiles CASCADE"))
