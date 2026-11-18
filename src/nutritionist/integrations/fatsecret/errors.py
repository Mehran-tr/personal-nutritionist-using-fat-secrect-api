"""Vendor-level errors. Translated into domain errors by the catalog adapter."""

# fatsecret API error codes we react to (see platform.fatsecret.com/docs/guides/error-codes).
INVALID_TOKEN = 13
MISSING_SCOPE = 14
INVALID_ID = 106


class FatSecretError(Exception):
    """Base class for every fatsecret integration failure."""


class FatSecretApiError(FatSecretError):
    """fatsecret returned an error envelope: ``{"error": {"code": .., "message": ..}}``."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"fatsecret error {code}: {message}")

    @property
    def is_invalid_token(self) -> bool:
        return self.code == INVALID_TOKEN

    @property
    def is_invalid_id(self) -> bool:
        return self.code == INVALID_ID


class FatSecretAuthError(FatSecretError):
    """Could not obtain an access token (bad credentials, missing scope, ...)."""


class FatSecretUnavailableError(FatSecretError):
    """Timeouts, connection errors, 5xx or rate limiting, after retries."""


class FatSecretProtocolError(FatSecretError):
    """The response did not match the shape we expect. Usually means a version drift."""
