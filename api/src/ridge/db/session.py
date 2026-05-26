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

from ridge.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the shared async engine, constructing it on first call.

    Pool sizing leaves comfortable headroom for the FastAPI app, the CLI
    pipeline, and the streamlit admin running side-by-side without
    saturating Postgres (defaults 5+10=15; bumped to 10+20=30).

    ``pool_recycle=1800`` recycles connections after 30 min so we don't
    hand out stale ones that an upstream proxy or NAT has silently
    dropped.

    ``statement_timeout=30s`` is a production guardrail — a runaway
    query (e.g. accidental cross join) won't hold a connection open
    forever. Long analytical work that legitimately exceeds 30s should
    raise the bar explicitly rather than rely on the default infinity.

    ``application_name=ridge`` makes ridge connections identifiable in
    pg_stat_activity (the default "psycopg" is useless for debugging
    which process is holding a long-running transaction).
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.db_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            connect_args={
                "options": "-c statement_timeout=30s -c application_name=ridge",
            },
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
