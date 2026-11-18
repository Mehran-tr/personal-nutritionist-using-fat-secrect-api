"""Framework-agnostic error hierarchy.

Feature modules subclass these. Only the web layer (``nutritionist.api.errors``)
knows how each category maps to an HTTP status.
"""


class AppError(Exception):
    """Base class for every error we raise on purpose."""

    code: str = "app_error"
    title: str = "Application error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.title
        super().__init__(self.detail)


class NotFoundError(AppError):
    code = "not_found"
    title = "Resource not found"


class ValidationError(AppError):
    code = "validation_error"
    title = "Invalid input"


class ExternalServiceError(AppError):
    """An upstream dependency answered, but with an error we cannot recover from."""

    code = "upstream_error"
    title = "Upstream service error"


class ExternalServiceUnavailableError(ExternalServiceError):
    """An upstream dependency is down, timing out or rate-limiting us."""

    code = "upstream_unavailable"
    title = "Upstream service unavailable"
