"""Tests for FastAPI data endpoints.

Integration tests -- hit the live docker-compose database.
Endpoints return empty lists when no data exists, which is correct.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from ridge.api.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_countries_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/countries")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


async def test_scores_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/scores")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_scores_with_filter(client: AsyncClient) -> None:
    resp = await client.get("/scores", params={"country_iso3": "NGA", "limit": 5})
    assert resp.status_code == 200
    for s in resp.json():
        assert s["country_iso3"] == "NGA"


async def test_alerts_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/alerts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_alerts_tier_filter(client: AsyncClient) -> None:
    resp = await client.get("/alerts", params={"effective_tier": "ESCALATE"})
    assert resp.status_code == 200


async def test_quality_issues_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/quality/issues")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_pipeline_runs_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/pipeline/runs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_pipeline_run_not_found(client: AsyncClient) -> None:
    resp = await client.get("/pipeline/runs/nonexistent-id")
    assert resp.status_code == 404


async def test_narratives_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/narratives")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_narratives_with_filter(client: AsyncClient) -> None:
    resp = await client.get("/narratives", params={"template_name": "country_narrative"})
    assert resp.status_code == 200


async def test_openapi_lists_all_routes(client: AsyncClient) -> None:
    """Verify all route paths are registered in OpenAPI schema."""
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = set(resp.json()["paths"].keys())
    expected = {
        "/health",
        "/countries",
        "/scores",
        "/alerts",
        "/quality/issues",
        "/pipeline/runs",
        "/pipeline/runs/{run_id}",
        "/narratives",
    }
    assert expected.issubset(paths), f"Missing routes: {expected - paths}"
