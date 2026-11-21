"""SQLAlchemy plumbing shared by every module's infrastructure layer."""

import time
from abc import ABC, abstractmethod
from datetime import datetime
from types import TracebackType
from typing import Self

import structlog
from sqlalchemy import DateTime, MetaData, event, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nutritionist.core.config import DatabaseSettings
from nutritionist.core.metrics import DB_QUERY_LATENCY, DB_SLOW_QUERIES

logger = structlog.get_logger(__name__)

# Deterministic constraint names: stable Alembic diffs and catchable IntegrityErrors.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Pooled async engine with timeouts at every level.

    Pool sizing: (replicas x workers x (pool_size + max_overflow)) must stay below
    Postgres ``max_connections`` (minus admin headroom), or put PgBouncer in front.
    """
    engine = create_async_engine(
        settings.url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,  # wait for a free connection
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.connect_timeout_seconds,  # TCP/handshake
            "command_timeout": settings.statement_timeout_ms / 1000 + 1,  # client side
            "server_settings": {
                "statement_timeout": str(settings.statement_timeout_ms),
                "idle_in_transaction_session_timeout": str(settings.idle_in_transaction_timeout_ms),
                "application_name": "nutritionist",
            },
        },
    )
    install_query_timing(engine, settings.slow_query_ms)
    return engine


def install_query_timing(engine: AsyncEngine, slow_query_ms: int) -> None:
    """Every statement feeds a latency histogram; slow ones are also logged.
    The SQL text is logged, never the bound parameters (they can be personal data).

    Caveat: with asyncio this measures wall time around an ``await``, so it also
    includes event-loop lag. If PK lookups show up as "slow", the loop was
    starved (CPU-bound work on the loop or too many CPU threads), not the database.
    Postgres' own ``log_min_duration_statement`` shows the server-side truth.
    """
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _stop(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        elapsed = time.perf_counter() - conn.info["query_start"].pop()
        DB_QUERY_LATENCY.observe(elapsed)
        if elapsed * 1000 >= slow_query_ms:
            DB_SLOW_QUERIES.inc()
            logger.warning(
                "slow_query", duration_ms=round(elapsed * 1000, 1), statement=statement[:500]
            )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: domain objects are built from records before commit and
    # must stay readable afterwards without lazy loads.
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def ping(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


class SqlAlchemyUnitOfWork(ABC):
    """Base UoW: one session per ``async with`` block, rolled back unless committed."""

    session: AsyncSession

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self.session = self._session_factory()
        self._bind_repositories(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            await self.session.rollback()  # no-op after a successful commit
        finally:
            await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    @abstractmethod
    def _bind_repositories(self, session: AsyncSession) -> None:
        """Create this module's repositories on ``session``."""
