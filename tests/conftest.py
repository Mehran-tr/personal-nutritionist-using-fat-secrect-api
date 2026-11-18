import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from nutritionist.core.config import CacheSettings, Environment, FatSecretSettings, Settings

FIXTURES = Path(__file__).parent / "contract" / "fatsecret" / "fixtures"


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
def settings(fatsecret_settings: FatSecretSettings) -> Settings:
    return Settings(
        environment=Environment.TEST,
        log_json=False,
        log_level="WARNING",
        fatsecret=fatsecret_settings,
        cache=CacheSettings(backend="memory"),
    )
