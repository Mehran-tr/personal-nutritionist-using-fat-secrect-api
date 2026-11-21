"""Database guard rails and index usage, on real PostgreSQL."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from nutritionist.core.config import DatabaseSettings
from nutritionist.core.db import create_engine
from nutritionist.core.metrics import DB_SLOW_QUERIES
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.usefixtures("database")


async def test_statement_timeout_stops_runaway_queries() -> None:
    engine = create_engine(DatabaseSettings(url=TEST_DATABASE_URL, statement_timeout_ms=200))
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError, match="statement timeout"):
                await conn.execute(text("SELECT pg_sleep(2)"))
    finally:
        await engine.dispose()


async def test_slow_queries_are_counted() -> None:
    engine = create_engine(DatabaseSettings(url=TEST_DATABASE_URL, slow_query_ms=50))
    before = DB_SLOW_QUERIES._value.get()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_sleep(0.1)"))
    finally:
        await engine.dispose()
    assert DB_SLOW_QUERIES._value.get() == before + 1


async def test_diary_day_query_uses_the_composite_index() -> None:
    engine = create_engine(DatabaseSettings(url=TEST_DATABASE_URL))
    try:
        async with engine.connect() as conn:
            # Tiny test tables make a seq scan cheapest. Forbid it to prove the
            # index *can* serve the query (it will be chosen on real volumes).
            await conn.execute(text("SET enable_seqscan = off"))
            plan = (
                (
                    await conn.execute(
                        text(
                            "EXPLAIN SELECT * FROM diary_entries "
                            "WHERE user_id = :u AND day = :d ORDER BY logged_at"
                        ),
                        {"u": uuid.uuid4(), "d": date(2026, 11, 18)},
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()
    assert any("ix_diary_entries_user_id_day" in line for line in plan), plan
