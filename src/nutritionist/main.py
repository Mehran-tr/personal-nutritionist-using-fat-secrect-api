"""Application factory.

Run locally:  uv run uvicorn nutritionist.main:create_app --factory --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from nutritionist import __version__
from nutritionist.api import health
from nutritionist.api.errors import register_error_handlers
from nutritionist.api.hardening import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from nutritionist.api.middleware import RequestContextMiddleware
from nutritionist.api.performance import ETagMiddleware, MetricsMiddleware, metrics_router
from nutritionist.bootstrap import ContainerFactory, build_container
from nutritionist.core.config import Settings
from nutritionist.core.logging import configure_logging
from nutritionist.modules.catalog.api.router import router as catalog_router
from nutritionist.modules.coach.api.router import router as coach_router
from nutritionist.modules.diary.api.router import router as diary_router
from nutritionist.modules.identity.api.router import router as identity_router
from nutritionist.modules.profile.api.router import router as profile_router
from nutritionist.modules.targets.api.router import router as targets_router


def create_app(
    settings: Settings | None = None,
    container_factory: ContainerFactory = build_container,
) -> FastAPI:
    settings = settings or Settings()  # required fields are read from the environment
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await container_factory(settings)
        app.state.container = container
        await container.warm_up()
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title="Personal Nutritionist API",
        debug=False,  # never render tracebacks to clients, in any environment
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # Starlette runs the LAST added middleware first. Resulting order per request:
    # request-id/access log -> security headers -> gzip -> host check -> body size
    # -> throttling -> metrics -> etag -> app.
    # Security headers wrap everything (so 400/413/429 get them). ETag hashes the
    # *uncompressed* body, and gzip compresses the final one.
    security, perf = settings.security, settings.performance
    if perf.etag_enabled:
        app.add_middleware(ETagMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RateLimitMiddleware, settings=security, api_prefix=settings.api_prefix)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=security.max_request_body_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=security.allowed_hosts)
    if perf.gzip_enabled:
        app.add_middleware(GZipMiddleware, minimum_size=perf.gzip_min_bytes, compresslevel=6)
    app.add_middleware(SecurityHeadersMiddleware, settings=security)
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(metrics_router)
    for router in (
        identity_router,
        profile_router,
        targets_router,
        diary_router,
        coach_router,
        catalog_router,
    ):
        app.include_router(router, prefix=settings.api_prefix)
    return app
