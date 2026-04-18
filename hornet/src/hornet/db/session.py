"""Async SQLAlchemy engine and session factory.

The engine and session factory are created lazily on first access so
importing this module has no side effects (no connection pool, no
environment reads beyond what Settings already did). Call sites get
their session via ``session_scope()`` — an async context manager that
commits on clean exit and rolls back on exception.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hornet.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the shared async engine, constructing it on first call."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.db_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared async session factory, constructing it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session that commits on clean exit and rolls back on failure.

    Usage::

        async with session_scope() as session:
            session.add(thing)
            # commit happens automatically when the block exits cleanly

    If the block raises, the session is rolled back and the exception
    re-raised. Either way the session is always closed.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Close the engine and release its connection pool.

    Call at process shutdown (FastAPI lifespan, CLI teardown) so
    Postgres sees connections being closed cleanly instead of timing out.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
