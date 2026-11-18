"""Composition root: the only place that knows which adapter implements which port."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from nutritionist.core.auth import AccessTokenVerifier
from nutritionist.core.cache import Cache, InMemoryCache, RedisCache
from nutritionist.core.clock import Clock, SystemClock
from nutritionist.core.config import Settings
from nutritionist.core.db import create_engine, create_session_factory, ping
from nutritionist.integrations.fatsecret.auth import ClientCredentialsTokenProvider
from nutritionist.integrations.fatsecret.client import FatSecretClient
from nutritionist.modules.catalog.domain.ports import FoodProvider
from nutritionist.modules.catalog.infrastructure.cached_provider import CachedFoodProvider
from nutritionist.modules.catalog.infrastructure.fatsecret_provider import FatSecretFoodProvider
from nutritionist.modules.identity.application.use_cases import (
    AuthenticateUser,
    GetCurrentUser,
    IdentityUseCases,
    RegisterUser,
)
from nutritionist.modules.identity.infrastructure.repository import SqlAlchemyIdentityUnitOfWork
from nutritionist.modules.identity.infrastructure.security import (
    Argon2PasswordHasher,
    JwtTokenService,
)
from nutritionist.modules.profile.application.use_cases import (
    GetProfile,
    ProfileUseCases,
    SaveProfile,
)
from nutritionist.modules.profile.infrastructure.repository import SqlAlchemyProfileUnitOfWork


@dataclass(slots=True)
class Container:
    settings: Settings
    clock: Clock
    http: httpx.AsyncClient
    cache: Cache
    engine: AsyncEngine
    token_verifier: AccessTokenVerifier
    food_provider: FoodProvider
    identity: IdentityUseCases
    profile: ProfileUseCases

    async def readiness(self) -> dict[str, bool]:
        return {"database": await ping(self.engine), "cache": await self.cache.ping()}

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.cache.aclose()
        await self.engine.dispose()


ContainerFactory = Callable[[Settings], Awaitable[Container]]


def build_cache(settings: Settings) -> Cache:
    if settings.cache.backend == "memory":
        return InMemoryCache()
    return RedisCache.from_url(settings.cache.redis_url)


def build_food_provider(settings: Settings, http: httpx.AsyncClient, cache: Cache) -> FoodProvider:
    fs = settings.fatsecret
    tokens = ClientCredentialsTokenProvider(
        http,
        token_url=fs.token_url,
        client_id=fs.client_id.get_secret_value(),
        client_secret=fs.client_secret.get_secret_value(),
        scopes=fs.scopes,
        refresh_margin_seconds=fs.token_refresh_margin_seconds,
    )
    return CachedFoodProvider(
        FatSecretFoodProvider(FatSecretClient(http, tokens, fs)),
        cache,
        namespace=f"fatsecret:{fs.region or 'default'}",
        food_ttl_seconds=settings.cache.food_ttl_seconds,
        search_ttl_seconds=settings.cache.search_ttl_seconds,
    )


async def build_container(settings: Settings, clock: Clock | None = None) -> Container:
    clock = clock or SystemClock()
    http = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.fatsecret.timeout_seconds),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        headers={"User-Agent": f"{settings.app_name}/0.1"},
    )
    cache = build_cache(settings)
    engine = create_engine(settings.database)
    sessions = create_session_factory(engine)

    hasher = Argon2PasswordHasher()
    tokens = JwtTokenService(settings.auth, clock)

    def identity_uow() -> SqlAlchemyIdentityUnitOfWork:
        return SqlAlchemyIdentityUnitOfWork(sessions)

    def profile_uow() -> SqlAlchemyProfileUnitOfWork:
        return SqlAlchemyProfileUnitOfWork(sessions)

    return Container(
        settings=settings,
        clock=clock,
        http=http,
        cache=cache,
        engine=engine,
        token_verifier=tokens,
        food_provider=build_food_provider(settings, http, cache),
        identity=IdentityUseCases(
            register_user=RegisterUser(identity_uow, hasher, clock),
            authenticate_user=AuthenticateUser(identity_uow, hasher, tokens),
            get_current_user=GetCurrentUser(identity_uow),
        ),
        profile=ProfileUseCases(
            save_profile=SaveProfile(profile_uow, clock),
            get_profile=GetProfile(profile_uow),
        ),
    )
