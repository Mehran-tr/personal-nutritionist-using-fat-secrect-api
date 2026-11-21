"""Composition root: the only place that knows which adapter implements which port."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from nutritionist.core.auth import AccessTokenVerifier
from nutritionist.core.background import BackgroundRunner
from nutritionist.core.cache import Cache, InMemoryCache, RedisCache
from nutritionist.core.clock import Clock, SystemClock
from nutritionist.core.config import Settings
from nutritionist.core.db import create_engine, create_session_factory, ping
from nutritionist.core.rate_limit import RateLimiter
from nutritionist.core.rate_limit_stores import (
    FailOpenRateLimiter,
    InMemoryRateLimiter,
    RedisRateLimiter,
)
from nutritionist.integrations.anthropic.client import AnthropicClient
from nutritionist.integrations.fatsecret.auth import ClientCredentialsTokenProvider
from nutritionist.integrations.fatsecret.client import FatSecretClient
from nutritionist.interop.catalog_to_diary import CatalogFoodLookup
from nutritionist.interop.diary_to_coach import DiaryDaySource
from nutritionist.interop.profile_to_targets import ProfileBodyStatsProvider
from nutritionist.interop.targets_to_diary import TargetsForDiary
from nutritionist.modules.catalog.application.use_cases import GetFood
from nutritionist.modules.catalog.domain.ports import FoodProvider
from nutritionist.modules.catalog.infrastructure.cached_provider import CachedFoodProvider
from nutritionist.modules.catalog.infrastructure.fatsecret_provider import FatSecretFoodProvider
from nutritionist.modules.coach.application.use_cases import GetDayReview, NoPhraser, Phraser
from nutritionist.modules.coach.domain.rules import CoachEngine
from nutritionist.modules.coach.infrastructure.phrasers import CachedPhraser, LlmPhraser
from nutritionist.modules.diary.application.use_cases import (
    DeleteEntry,
    DiaryUseCases,
    GetDailySummary,
    LogFood,
    UpdateEntry,
)
from nutritionist.modules.diary.infrastructure.repository import SqlAlchemyDiaryUnitOfWork
from nutritionist.modules.identity.application.use_cases import (
    AuthenticateUser,
    GetCurrentUser,
    IdentityUseCases,
    LoginGuard,
    LoginPolicy,
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
from nutritionist.modules.targets.application.use_cases import GetTargets
from nutritionist.modules.targets.domain.calculator import TargetCalculator


@dataclass(slots=True)
class Container:
    settings: Settings
    clock: Clock
    http: httpx.AsyncClient
    cache: Cache
    engine: AsyncEngine
    token_verifier: AccessTokenVerifier
    rate_limiter: RateLimiter
    food_provider: FoodProvider
    identity: IdentityUseCases
    profile: ProfileUseCases
    targets: GetTargets
    diary: DiaryUseCases
    coach: GetDayReview
    background: BackgroundRunner = field(default_factory=BackgroundRunner)
    # Best-effort tasks run at startup (open DB pool, fetch upstream tokens...).
    warmups: list[Callable[[], Awaitable[object]]] = field(default_factory=list)
    _limiter_store: object = None

    async def readiness(self) -> dict[str, bool]:
        return {"database": await ping(self.engine), "cache": await self.cache.ping()}

    async def warm_up(self, timeout_seconds: float = 3.0) -> None:
        """Pay first-request costs (TCP/TLS handshakes, DB connection, OAuth token)
        before traffic arrives. Never fails startup: a cold path is still correct."""
        log = structlog.get_logger(__name__)
        for task in self.warmups:
            try:
                await asyncio.wait_for(task(), timeout_seconds)
            except Exception as exc:
                log.warning(
                    "warm_up_skipped", task=getattr(task, "__name__", "?"), error=type(exc).__name__
                )

    async def aclose(self) -> None:
        await self.background.aclose()
        await self.http.aclose()
        await self.cache.aclose()
        close = getattr(self._limiter_store, "aclose", None)
        if close is not None:
            await close()
        await self.engine.dispose()


ContainerFactory = Callable[[Settings], Awaitable[Container]]


def build_cache(settings: Settings) -> Cache:
    if settings.cache.backend == "memory":
        return InMemoryCache()
    return RedisCache.from_url(
        settings.cache.redis_url, settings.cache.redis_socket_timeout_seconds
    )


def build_food_provider(
    settings: Settings,
    http: httpx.AsyncClient,
    cache: Cache,
    warmups: list[Callable[[], Awaitable[object]]] | None = None,
) -> FoodProvider:
    fs = settings.fatsecret
    tokens = ClientCredentialsTokenProvider(
        http,
        token_url=fs.token_url,
        client_id=fs.client_id.get_secret_value(),
        client_secret=fs.client_secret.get_secret_value(),
        scopes=fs.scopes,
        refresh_margin_seconds=fs.token_refresh_margin_seconds,
    )
    if warmups is not None:
        warmups.append(tokens.get_token)
    return CachedFoodProvider(
        FatSecretFoodProvider(FatSecretClient(http, tokens, fs)),
        cache,
        namespace=f"fatsecret:{fs.region or 'default'}",
        food_ttl_seconds=settings.cache.food_ttl_seconds,
        search_ttl_seconds=settings.cache.search_ttl_seconds,
    )


def build_rate_limiter(settings: Settings) -> tuple[RateLimiter, object]:
    """Returns (fail-open limiter for use, underlying store for shutdown)."""
    store: RedisRateLimiter | InMemoryRateLimiter
    if settings.cache.backend == "memory":
        store = InMemoryRateLimiter()
    else:
        store = RedisRateLimiter.from_url(
            settings.cache.redis_url, settings.cache.redis_socket_timeout_seconds
        )
    return FailOpenRateLimiter(store), store


def build_phraser(
    settings: Settings,
    http: httpx.AsyncClient,
    cache: Cache,
    runner: BackgroundRunner | None = None,
) -> Phraser:
    coach = settings.coach
    if not coach.llm_enabled or coach.anthropic_api_key is None:
        return NoPhraser()
    client = AnthropicClient(
        http,
        api_key=coach.anthropic_api_key.get_secret_value(),
        base_url=coach.anthropic_base_url,
        timeout_seconds=coach.timeout_seconds,
    )
    return CachedPhraser(
        LlmPhraser(client, model=coach.model, max_tokens=coach.max_tokens),
        cache,
        ttl_seconds=coach.cache_ttl_seconds,
        model=coach.model,
        runner=runner,
    )


async def build_container(
    settings: Settings,
    clock: Clock | None = None,
    food_provider: FoodProvider | None = None,
) -> Container:
    """Build the object graph. ``clock`` and ``food_provider`` can be overridden
    (tests replace the external food API, nothing else)."""
    clock = clock or SystemClock()
    http = httpx.AsyncClient(
        # One shared client: connection pooling + HTTP keep-alive to upstreams.
        timeout=httpx.Timeout(
            settings.fatsecret.timeout_seconds, connect=settings.fatsecret.connect_timeout_seconds
        ),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        headers={"User-Agent": f"{settings.app_name}/0.1"},
    )
    cache = build_cache(settings)
    engine = create_engine(settings.database)
    sessions = create_session_factory(engine)

    hasher = Argon2PasswordHasher(threads=settings.auth.hashing_threads)
    tokens = JwtTokenService(settings.auth, clock)
    rate_limiter, limiter_store = build_rate_limiter(settings)
    auth = settings.auth
    login_guard = LoginGuard(
        rate_limiter,
        LoginPolicy(
            max_failures_per_account_and_ip=auth.login_max_failures_per_account_and_ip,
            lockout_seconds=auth.login_lockout_seconds,
            max_failures_per_account=auth.login_max_failures_per_account,
            account_window_seconds=auth.login_account_window_seconds,
        ),
    )
    warmups: list[Callable[[], Awaitable[object]]] = [lambda: ping(engine), cache.ping]
    food_provider = food_provider or build_food_provider(settings, http, cache, warmups)
    background = BackgroundRunner(settings.performance.background_concurrency)

    def identity_uow() -> SqlAlchemyIdentityUnitOfWork:
        return SqlAlchemyIdentityUnitOfWork(sessions)

    def profile_uow() -> SqlAlchemyProfileUnitOfWork:
        return SqlAlchemyProfileUnitOfWork(sessions)

    def diary_uow() -> SqlAlchemyDiaryUnitOfWork:
        return SqlAlchemyDiaryUnitOfWork(sessions)

    profile = ProfileUseCases(
        save_profile=SaveProfile(profile_uow, clock),
        get_profile=GetProfile(profile_uow),
    )
    targets = GetTargets(ProfileBodyStatsProvider(profile.get_profile), TargetCalculator(), clock)
    targets_for_diary = TargetsForDiary(targets)
    daily_summary = GetDailySummary(diary_uow, targets_for_diary)

    return Container(
        settings=settings,
        clock=clock,
        http=http,
        cache=cache,
        engine=engine,
        token_verifier=tokens,
        rate_limiter=rate_limiter,
        _limiter_store=limiter_store,
        food_provider=food_provider,
        identity=IdentityUseCases(
            register_user=RegisterUser(identity_uow, hasher, clock),
            authenticate_user=AuthenticateUser(identity_uow, hasher, tokens, login_guard),
            get_current_user=GetCurrentUser(identity_uow),
        ),
        profile=profile,
        targets=targets,
        diary=DiaryUseCases(
            log_food=LogFood(
                diary_uow,
                CatalogFoodLookup(GetFood(food_provider)),
                targets_for_diary,
                clock,
                max_entries_per_day=settings.performance.max_entries_per_day,
            ),
            update_entry=UpdateEntry(diary_uow),
            delete_entry=DeleteEntry(diary_uow),
            get_daily_summary=daily_summary,
        ),
        coach=GetDayReview(
            DiaryDaySource(daily_summary),
            CoachEngine(),
            build_phraser(settings, http, cache, background),
            clock,
        ),
        background=background,
        warmups=warmups,
    )
