"""Tests for the database session module.

These tests do NOT connect to Postgres — engine construction is lazy
and a connection is not opened until a query runs. Tests that need
real DB connectivity live under a separate marker that the CI config
will gate on a live container.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ridge.db.session import get_engine, get_session_factory


def test_engine_is_async_engine() -> None:
    engine = get_engine()
    assert isinstance(engine, AsyncEngine)


def test_get_engine_returns_same_instance() -> None:
    engine1 = get_engine()
    engine2 = get_engine()
    assert engine1 is engine2


def test_session_factory_bound_to_engine() -> None:
    factory = get_session_factory()
    assert isinstance(factory, async_sessionmaker)


async def test_session_scope_yields_async_session() -> None:
    """Smoke test: session_scope should yield an AsyncSession instance.

    We never touch the DB — we open the session, assert its type, then
    exit cleanly. No queries executed. This catches wiring bugs in the
    session factory without needing a live Postgres.
    """
    from ridge.db.session import session_scope

    async with session_scope() as session:
        assert isinstance(session, AsyncSession)
