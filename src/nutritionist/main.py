"""Application factory.

Run locally:  uv run uvicorn nutritionist.main:create_app --factory --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nutritionist import __version__
from nutritionist.api import health
from nutritionist.api.errors import register_error_handlers
from nutritionist.api.middleware import RequestContextMiddleware
from nutritionist.bootstrap import ContainerFactory, build_container
from nutritionist.core.config import Settings
from nutritionist.core.logging import configure_logging
from nutritionist.modules.catalog.api.router import router as catalog_router
from nutritionist.modules.identity.api.router import router as identity_router
from nutritionist.modules.profile.api.router import router as profile_router


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
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title="Personal Nutritionist API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health.router)
    for router in (identity_router, profile_router, catalog_router):
        app.include_router(router, prefix=settings.api_prefix)
    return app
