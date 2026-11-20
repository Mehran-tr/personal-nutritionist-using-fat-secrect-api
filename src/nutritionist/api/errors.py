"""Map application errors to RFC 9457 (problem+json) responses."""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from nutritionist.core.exceptions import (
    AppError,
    AuthenticationError,
    ConflictError,
    ExternalServiceError,
    ExternalServiceUnavailableError,
    NotFoundError,
    TooManyRequestsError,
    ValidationError,
)

PROBLEM_JSON = "application/problem+json"

# Most specific class first.
_STATUS_BY_ERROR: tuple[tuple[type[AppError], int], ...] = (
    (AuthenticationError, 401),
    (NotFoundError, 404),
    (ConflictError, 409),
    (TooManyRequestsError, 429),
    (ValidationError, 422),
    (ExternalServiceUnavailableError, 503),
    (ExternalServiceError, 502),
)

logger = structlog.get_logger(__name__)


def _status_for(exc: AppError) -> int:
    for error_type, status in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return status
    return 500


def problem(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    status = _status_for(exc)
    log = logger.warning if status < 500 else logger.error
    log("app_error", code=exc.code, status=status, detail=exc.detail)
    headers: dict[str, str] | None = None
    if status == 401:
        headers = {"WWW-Authenticate": "Bearer"}
    elif isinstance(exc, TooManyRequestsError):
        headers = {"Retry-After": str(exc.retry_after_seconds)}
    return problem(
        request, status=status, code=exc.code, title=exc.title, detail=exc.detail, headers=headers
    )


async def _handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return problem(
        request,
        status=422,
        code="request_validation_error",
        title="Invalid request",
        detail="One or more request parameters are invalid.",
        extra={"errors": _safe_errors(exc.errors())},
    )


def _safe_errors(errors: Any) -> list[dict[str, Any]]:
    """Location, message and type only. Pydantic's default output echoes the
    submitted ``input`` (e.g. a password that was too short) and ``ctx``/``url``
    internals. Never send user input back or into logs."""
    return [
        jsonable_encoder({"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")})
        for e in errors
    ]


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return problem(
        request,
        status=exc.status_code,
        code="http_error",
        title=str(exc.detail),
        detail=str(exc.detail),
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error")
    return problem(
        request,
        status=500,
        code="internal_error",
        title="Internal server error",
        detail="An unexpected error occurred.",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)
