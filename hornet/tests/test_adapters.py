"""Tests for the SourceAdapter protocol contract."""

from __future__ import annotations

from datetime import UTC, datetime

from hornet.adapters import HealthReport, SourceAdapter
from hornet.domain import FetchRequest, Observation, SourceManifest


class TestHealthReport:
    def test_healthy_report(self) -> None:
        report = HealthReport(source_id="fred", healthy=True, latency_ms=120)
        assert report.healthy is True
        assert report.latency_ms == 120
        assert report.last_error is None

    def test_unhealthy_report(self) -> None:
        report = HealthReport(
            source_id="fred",
            healthy=False,
            last_error="503 Service Unavailable",
        )
        assert report.healthy is False
        assert report.last_error == "503 Service Unavailable"


class _StubAdapter:
    """Minimal adapter that satisfies the SourceAdapter protocol.

    Used to prove the protocol is satisfiable and runtime-checkable.
    """

    source_id = "stub"

    async def discover(self) -> SourceManifest:
        return SourceManifest(
            source_id=self.source_id,
            indicators=(),
            discovered_at=datetime(2026, 4, 11, tzinfo=UTC),
        )

    async def fetch(self, request: FetchRequest) -> list[Observation]:
        return []

    async def health(self) -> HealthReport:
        return HealthReport(source_id=self.source_id, healthy=True)


class TestSourceAdapterProtocol:
    def test_stub_satisfies_protocol(self) -> None:
        stub = _StubAdapter()
        assert isinstance(stub, SourceAdapter)

    async def test_stub_discover_returns_manifest(self) -> None:
        stub = _StubAdapter()
        manifest = await stub.discover()
        assert manifest.source_id == "stub"
        assert manifest.indicators == ()

    async def test_stub_fetch_returns_empty_list(self) -> None:
        stub = _StubAdapter()
        result = await stub.fetch(FetchRequest(source_id="stub"))
        assert result == []
