"""Tests for the OECD SourceAdapter.

All tests use ``httpx.MockTransport`` -- no real OECD API calls.
Tests exercise the bulk-fetch pattern, SDMX-JSON parsing integration,
country/indicator filtering, and the discover manifest.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import httpx

from hornet.adapters.oecd import OECDAdapter
from hornet.domain import FetchRequest, SourceIndicatorSpec


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    """4 OECD indicators for 4 pilot countries (NGA excluded)."""
    covered = frozenset({"TUR", "ZAF", "BRA", "POL"})
    codes = ["CLI", "BCI", "CCI", "INDPROD"]
    return [
        SourceIndicatorSpec(
            source_id="oecd",
            source_native_code=code,
            indicator_code=code,
            frequency="monthly",
            countries_iso3=covered,
        )
        for code in codes
    ]


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: Sequence[SourceIndicatorSpec] | None = None,
) -> OECDAdapter:
    return OECDAdapter(
        indicators=indicators if indicators is not None else _pilot_indicators(),
        requests_per_minute=600000,
        transport=httpx.MockTransport(handler),
    )


def _oecd_bulk_response(
    country_values: dict[str, list[float]],
    time_periods: list[str],
) -> dict[str, Any]:
    """Build an OECD SDMX-JSON response with multiple countries."""
    country_codes = sorted(country_values.keys())
    series: dict[str, Any] = {}
    for i, code in enumerate(country_codes):
        obs = {str(t): [v] for t, v in enumerate(country_values[code])}
        series[f"{i}:0:0:0:0:0:0"] = {"observations": obs}

    return {
        "data": {
            "dataSets": [{"series": series}],
            "structure": {
                "dimensions": {
                    "series": [
                        {
                            "id": "REF_AREA",
                            "values": [{"id": code} for code in country_codes],
                        },
                    ],
                    "observation": [
                        {
                            "id": "TIME_PERIOD",
                            "role": "time",
                            "values": [{"id": tp} for tp in time_periods],
                        },
                    ],
                },
            },
        },
    }


class TestConstructor:
    async def test_drops_non_oecd_indicators(self) -> None:
        mixed = [
            SourceIndicatorSpec(
                source_id="oecd",
                source_native_code="CLI",
                indicator_code="CLI",
                frequency="monthly",
                countries_iso3=frozenset({"TUR"}),
            ),
            SourceIndicatorSpec(
                source_id="fred",
                source_native_code="FPCPITOTLZGTUR",
                indicator_code="CPI_YOY",
                frequency="annual",
                countries_iso3=frozenset({"TUR"}),
            ),
        ]
        adapter = _adapter(
            lambda r: httpx.Response(200, json={}),
            indicators=mixed,
        )
        try:
            manifest = await adapter.discover()
            assert len(manifest.indicators) == 1
            assert manifest.indicators[0].indicator_code == "CLI"
        finally:
            await adapter.close()

    async def test_drops_unknown_dataflow_indicators(self) -> None:
        unknown = [
            SourceIndicatorSpec(
                source_id="oecd",
                source_native_code="NONEXISTENT",
                indicator_code="NONEXISTENT",
                frequency="monthly",
                countries_iso3=frozenset({"TUR"}),
            ),
        ]
        adapter = _adapter(
            lambda r: httpx.Response(200, json={}),
            indicators=unknown,
        )
        try:
            manifest = await adapter.discover()
            assert len(manifest.indicators) == 0
        finally:
            await adapter.close()


class TestFetch:
    async def test_returns_observations_from_bulk_response(self) -> None:
        resp = _oecd_bulk_response(
            {"BRA": [99.0, 100.5], "TUR": [101.0, 102.5]},
            ["2024-01", "2024-02"],
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=resp)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="oecd",
                    indicator_codes=frozenset({"CLI"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 4  # 2 countries x 2 periods
        countries_seen = {obs.country_iso3 for obs in result}
        # BRA + TUR returned; ZAF and POL not in mock response
        assert countries_seen == {"BRA", "TUR"}
        assert all(obs.indicator_code == "CLI" for obs in result)
        assert all(obs.source_id == "oecd" for obs in result)
        assert all(obs.frequency == "monthly" for obs in result)

    async def test_country_filter_restricts_output(self) -> None:
        resp = _oecd_bulk_response(
            {"BRA": [99.0], "TUR": [101.0]},
            ["2024-01"],
        )

        adapter = _adapter(lambda r: httpx.Response(200, json=resp))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="oecd",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"CLI"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 1
        assert result[0].country_iso3 == "TUR"

    async def test_error_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal"})

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="oecd",
                    indicator_codes=frozenset({"CLI"}),
                )
            )
        finally:
            await adapter.close()

        assert result == []

    async def test_indicator_filter_restricts_which_dataflows_are_fetched(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            resp = _oecd_bulk_response({"TUR": [100.0]}, ["2024-01"])
            return httpx.Response(200, json=resp)

        adapter = _adapter(handler)
        try:
            await adapter.fetch(
                FetchRequest(
                    source_id="oecd",
                    indicator_codes=frozenset({"CLI"}),
                )
            )
        finally:
            await adapter.close()

        # Only one indicator requested, so only one bulk fetch should occur
        assert call_count == 1


class TestDiscover:
    async def test_manifest_covers_all_indicators(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={}))
        try:
            manifest = await adapter.discover()
        finally:
            await adapter.close()

        assert manifest.source_id == "oecd"
        assert len(manifest.indicators) == 4

        codes = {spec.indicator_code for spec in manifest.indicators}
        assert codes == {"CLI", "BCI", "CCI", "INDPROD"}

    async def test_each_indicator_covers_pilot_countries(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={}))
        try:
            manifest = await adapter.discover()
        finally:
            await adapter.close()

        for spec in manifest.indicators:
            assert spec.countries_iso3 == frozenset({"TUR", "ZAF", "BRA", "POL"})
            assert spec.frequency == "monthly"


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={}))
        try:
            report = await adapter.health()
        finally:
            await adapter.close()
        assert report.source_id == "oecd"
        assert report.healthy is True
