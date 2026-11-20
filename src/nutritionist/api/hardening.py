"""HTTP hardening: security headers, request size limit, per-IP throttling and
an internal-network guard. Pure ASGI middleware (no BaseHTTPMiddleware)."""

import ipaddress

import structlog
from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nutritionist.api.errors import problem
from nutritionist.core.config import SecuritySettings
from nutritionist.core.rate_limit import RateLimiter

logger = structlog.get_logger("security")

# Strictest policy for a JSON API: the browser should never render or run anything.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI (non-production only) needs its CDN scripts and styles.
DOCS_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; "
    "frame-ancestors 'none'"
)
DOCS_PATHS = ("/docs", "/openapi.json")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, settings: SecuritySettings) -> None:
        self.app = app
        self._hsts = (
            f"max-age={settings.hsts_max_age_seconds}; includeSubDomains"
            if settings.hsts_enabled
            else None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope["path"].startswith(DOCS_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Content-Security-Policy"] = DOCS_CSP if is_docs else API_CSP
                headers["Referrer-Policy"] = "no-referrer"
                headers["Cross-Origin-Resource-Policy"] = "same-origin"
                # Every API response is per-user or volatile: never cache it anywhere.
                headers.setdefault("Cache-Control", "no-store")
                if self._hsts:
                    headers["Strict-Transport-Security"] = self._hsts
                for fingerprint in ("server", "x-powered-by"):
                    if fingerprint in headers:
                        del headers[fingerprint]
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """413 for bodies over the limit, whether declared (Content-Length) or streamed.

    Streamed bodies (no Content-Length) are buffered up to the limit *before* the
    app runs. Raising mid-stream wouldn't work: FastAPI turns body-reading errors
    into a 400. Buffering is cheap because the limit is small.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None:
            if not declared.isdigit() or int(declared) > self._max:
                await self._reject(scope, receive, send)
                return
            await self.app(scope, receive, send)  # the server enforces the declared length
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            if len(body) > self._max:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = problem(
            Request(scope),
            status=413,
            code="payload_too_large",
            title="Payload too large",
            detail=f"Request bodies are limited to {self._max} bytes.",
        )
        await response(scope, receive, send)


class RateLimitMiddleware:
    """Per-client-IP fixed-window throttling; stricter on authentication routes."""

    def __init__(self, app: ASGIApp, settings: SecuritySettings, api_prefix: str) -> None:
        self.app = app
        self._enabled = settings.rate_limit_enabled
        self._default = settings.rate_limit_per_minute
        self._auth = settings.auth_rate_limit_per_minute
        self._auth_prefix = f"{api_prefix}/auth/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "http" or not self._enabled or path.startswith("/health"):
            await self.app(scope, receive, send)
            return

        limiter: RateLimiter = scope["app"].state.container.rate_limiter
        client_ip = scope["client"][0] if scope.get("client") else "unknown"
        bucket, limit = (
            ("auth", self._auth) if path.startswith(self._auth_prefix) else ("api", self._default)
        )
        state = await limiter.hit(f"ip:{bucket}:{client_ip}", window_seconds=60)

        if state.count > limit:
            logger.warning("rate_limited", client_ip=client_ip, bucket=bucket, path=path)
            response = problem(
                Request(scope),
                status=429,
                code="too_many_requests",
                title="Too many requests",
                detail="Request limit reached. Retry after the time in Retry-After.",
                headers={"Retry-After": str(state.retry_after_seconds)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def internal_network_only(request: Request) -> None:
    """Dependency: only callers from ``SECURITY__INTERNAL_NETWORKS`` may reach the
    endpoint. Everyone else gets a 404, so the endpoint's existence isn't revealed."""
    networks = request.app.state.container.settings.security.internal_networks
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not Found") from None
    if not any(address in ipaddress.ip_network(n, strict=False) for n in networks):
        raise HTTPException(status_code=404, detail="Not Found")
