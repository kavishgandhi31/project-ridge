"""Tests for the FastAPI application and its routes.

``test_openapi_exposes_health`` is hermetic — it never talks to Postgres,
it just introspects the OpenAPI schema that FastAPI generates from the
route definitions. That catches route-wiring bugs without needing the DB.

``test_health_returns_ok_when_db_reachable`` IS an integration test —
it sends a real HTTP request through the app, which runs ``SELECT 1``
against the live docker-compose Postgres. If the database is down the
test fails loudly, which is intentional.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from ridge.api.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Yield an httpx AsyncClient wired to a fresh FastAPI app.

    ASGITransport routes requests through the app in-process without
    spinning up a real uvicorn server, so these tests run in milliseconds.
    """
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    async def test_openapi_exposes_health(self, client: AsyncClient) -> None:
        """The /health route should appear in the OpenAPI schema.

        Hermetic — no database involved. Just confirms the route was
        registered correctly.
        """
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert "/health" in paths
        assert "get" in paths["/health"]

    async def test_health_returns_ok_when_db_reachable(self, client: AsyncClient) -> None:
        """With Postgres running, /health should return 200 + status=ok.

        Integration test — hits the live docker-compose database.
        """
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert body["version"]
