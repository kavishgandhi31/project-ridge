"""FastAPI application factory and route definitions.

The app is built by ``create_app()`` so tests can construct fresh
instances without sharing state. A module-level ``app`` binding is
also exposed for uvicorn's import-string loader::

    uv run uvicorn hornet.api.main:app --reload --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from hornet import __version__
from hornet.api.routes.alerts import router as alerts_router
from hornet.api.routes.ask import router as ask_router
from hornet.api.routes.countries import router as countries_router
from hornet.api.routes.narratives import router as narratives_router
from hornet.api.routes.observations import router as observations_router
from hornet.api.routes.pipeline import router as pipeline_router
from hornet.api.routes.quality import router as quality_router
from hornet.api.routes.scores import router as scores_router
from hornet.db.session import dispose_engine, session_scope


class HealthResponse(BaseModel):
    """Shape of a healthy ``/health`` response body."""

    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unreachable"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run startup and shutdown hooks once per process.

    FastAPI calls this once at application boot (yielding to normal
    request handling) and once when the process is shutting down
    (after ``yield``). Keep this lean — anything slow here blocks
    the worker from serving traffic.
    """
    # Startup: no work needed — the engine is constructed lazily on
    # first use, so cold-start requests pay the pool-creation cost
    # but subsequent requests are fast.
    yield
    # Shutdown: close the connection pool cleanly so Postgres sees
    # connections going away instead of timing them out.
    await dispose_engine()


def create_app() -> FastAPI:
    """Build and return a FastAPI application instance."""
    app = FastAPI(
        title="Hornet API",
        version=__version__,
        lifespan=lifespan,
    )

    app.include_router(countries_router)
    app.include_router(scores_router)
    app.include_router(alerts_router)
    app.include_router(quality_router)
    app.include_router(pipeline_router)
    app.include_router(narratives_router)
    app.include_router(observations_router)
    app.include_router(ask_router)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Report application health with a real database probe.

        Runs ``SELECT 1`` against Postgres so we know the connection
        pool is actually usable — not just that the engine object
        exists. Returns ``200 {"status": "ok", ...}`` on success, or
        ``503`` with a ``"degraded"`` body on any failure.
        """
        try:
            async with session_scope() as session:
                result = await session.execute(text("SELECT 1"))
                value = result.scalar()
            if value != 1:
                raise RuntimeError(f"unexpected SELECT 1 result: {value!r}")
        except Exception as exc:
            error_body: dict[str, Any] = {
                "status": "degraded",
                "version": __version__,
                "database": "unreachable",
                "error": str(exc),
            }
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=error_body,
            ) from exc

        return HealthResponse(
            status="ok",
            version=__version__,
            database="ok",
        )

    return app


# Module-level instance for uvicorn's import-string loader.
app = create_app()
