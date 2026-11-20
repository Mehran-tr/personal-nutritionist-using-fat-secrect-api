import pytest
import structlog
from pydantic import SecretStr
from pydantic import ValidationError as PydanticValidationError

from nutritionist.core.config import (
    AuthSettings,
    CacheSettings,
    Environment,
    SecuritySettings,
    Settings,
)
from nutritionist.core.logging import REDACTED, redact_sensitive


def test_weak_jwt_secret_is_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="too weak"):
        AuthSettings(jwt_secret=SecretStr("a" * 64))
    with pytest.raises(PydanticValidationError):
        AuthSettings(jwt_secret=SecretStr("short"))


def test_production_refuses_unsafe_defaults(settings: Settings) -> None:
    data = settings.model_dump() | {"environment": Environment.PRODUCTION}
    with pytest.raises(PydanticValidationError) as exc_info:
        Settings.model_validate(_with_secrets(data, settings))
    message = str(exc_info.value)
    for setting in ("ALLOWED_HOSTS", "HSTS_ENABLED", "CACHE__BACKEND", "LOG_JSON"):
        assert setting in message


def test_hardened_production_config_is_accepted(settings: Settings) -> None:
    data = settings.model_dump() | {
        "environment": Environment.PRODUCTION,
        "log_json": True,
        "cache": CacheSettings(backend="redis").model_dump(),
        "security": SecuritySettings(
            allowed_hosts=["api.example.com"], hsts_enabled=True
        ).model_dump(),
    }
    hardened = Settings.model_validate(_with_secrets(data, settings))
    assert not hardened.docs_enabled


def _with_secrets(data: dict, settings: Settings) -> dict:  # type: ignore[type-arg]
    # model_dump() masks SecretStr; put the real values back.
    data["auth"]["jwt_secret"] = settings.auth.jwt_secret.get_secret_value()
    data["fatsecret"]["client_id"] = "id"
    data["fatsecret"]["client_secret"] = "secret"
    return data


def test_log_redaction() -> None:
    event = {
        "event": "x",
        "password": "hunter2",
        "Authorization": "Bearer abc",
        "nested": {"api_key": "sk", "safe": 1, "list": [{"token": "t"}]},
        "user_id": "u1",
    }
    out = redact_sensitive(structlog.get_logger(), "info", event)
    assert out["password"] == out["Authorization"] == REDACTED
    assert out["nested"] == {"api_key": REDACTED, "safe": 1, "list": [{"token": REDACTED}]}
    assert out["user_id"] == "u1"
