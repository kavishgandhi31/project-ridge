"""Tests for the IMF SourceAdapter.

All tests use ``httpx.MockTransport`` -- no real IMF API calls.
Tests exercise all three sub-APIs (WEO, IFS, BOP), the routing
logic via source_native_code prefix, WEO bulk parsing, and the
SDMX CompactData fallback for IFS/BOP.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import httpx

from hornet.adapters.imf import IMFAdapter
from hornet.domain import FetchRequest, SourceIndicatorSpec

_ALL_PILOTS = frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"})


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    """Build a representative set: 2 WEO + 2 IFS + 1 BOP."""
    return [
        SourceIndicatorSpec(
            source_id="imf",
            source_native_code="weo:NGDP_RPCH",
            indicator_code="GDP_GROWTH",
            frequency="forecast",
            countries_iso3=_ALL_PILOTS,
        ),
        SourceIndicatorSpec(
            source_id="imf",
            source_native_code="weo:PCPIPCH",
            indicator_code="CPI_YOY",
            frequency="forecast",
            countries_iso3=_ALL_PILOTS,
        ),
        SourceIndicatorSpec(
            source_id="imf",
            source_native_code="ifs:PCPI_IX",
            indicator_code="CPI_INDEX",
            frequency="monthly",
            countries_iso3=_ALL_PILOTS,
        ),
        SourceIndicatorSpec(
            source_id="imf",
            source_native_code="ifs:FITB_PA",
            indicator_code="POLICY_RATE",
            frequency="monthly",
            countries_iso3=_ALL_PILOTS,
        ),
        SourceIndicatorSpec(
            source_id="imf",
            source_native_code="bop:BCA_BP6_USD",
            indicator_code="CURRENT_ACCOUNT_USD",
            frequency="quarterly",
            countries_iso3=_ALL_PILOTS,
        ),
    ]


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: Sequence[SourceIndicatorSpec] | None = None,
) -> IMFAdapter:
    return IMFAdapter(
        indicators=indicators if indicators is not None else _pilot_indicators(),
        requests_per_minute=600000,
        transport=httpx.MockTransport(handler),
    )


def _weo_response(indicator_id: str, country_data: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Build a WEO-shaped JSON response."""
    return {"values": {indicator_id: country_data}}


def _imf_compact_response(obs: list[tuple[str, str]]) -> dict[str, Any]:
    """Build an IMF CompactData-shaped response.

    ``obs`` is a list of (time_period, value) tuples.
    """
    return {
        "CompactData": {
            "DataSet": {
                "Series": {"Obs": [{"@TIME_PERIOD": tp, "@OBS_VALUE": val} for tp, val in obs]}
            }
        }
    }


class TestConstructor:
    async def test_drops_non_imf_indicators(self) -> None:
        mixed = [
            SourceIndicatorSpec(
                source_id="imf",
                source_native_code="weo:NGDP_RPCH",
                indicator_code="GDP_GROWTH",
                frequency="forecast",
                countries_iso3=_ALL_PILOTS,
            ),
            SourceIndicatorSpec(
                source_id="fred",
                source_native_code="FPCPITOTLZGNGA",
                indicator_code="CPI_YOY",
                frequency="annual",
                countries_iso3=frozenset({"NGA"}),
            ),
        ]
        adapter = _adapter(lambda r: httpx.Response(200, json={}), indicators=mixed)
        try:
            manifest = await adapter.discover()
            assert len(manifest.indicators) == 1
        finally:
            await adapter.close()

    async def test_drops_unknown_prefix(self) -> None:
        bad = [
            SourceIndicatorSpec(
                source_id="imf",
                source_native_code="unknown:FOO",
                indicator_code="FOO",
                frequency="monthly",
                countries_iso3=_ALL_PILOTS,
            ),
        ]
        adapter = _adapter(lambda r: httpx.Response(200, json={}), indicators=bad)
        try:
            manifest = await adapter.discover()
            assert len(manifest.indicators) == 0
        finally:
            await adapter.close()

    async def test_classifies_weo_ifs_bop(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={}))
        assert len(adapter._weo_specs) == 2
        assert len(adapter._ifs_specs) == 2
        assert len(adapter._bop_specs) == 1
        await adapter.close()


class TestWeoFetch:
    async def test_parses_weo_bulk_response(self) -> None:
        resp = _weo_response(
            "NGDP_RPCH",
            {
                "NGA": {"2023": 2.9, "2024": 3.1},
                "TUR": {"2023": 4.5, "2024": 3.2},
                "XYZ": {"2023": 1.0},  # not in pilot set, should be filtered
            },
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=resp)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 4  # 2 countries x 2 years
        countries_seen = {obs.country_iso3 for obs in result}
        assert countries_seen == {"NGA", "TUR"}
        assert all(obs.indicator_code == "GDP_GROWTH" for obs in result)
        assert all(obs.frequency == "forecast" for obs in result)

    async def test_weo_country_filter(self) -> None:
        resp = _weo_response(
            "NGDP_RPCH",
            {
                "NGA": {"2023": 2.9},
                "TUR": {"2023": 4.5},
            },
        )

        adapter = _adapter(lambda r: httpx.Response(200, json=resp))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 1
        assert result[0].country_iso3 == "NGA"

    async def test_weo_skips_none_values(self) -> None:
        raw: dict[str, Any] = {"values": {"NGDP_RPCH": {"NGA": {"2023": 2.9, "2024": None}}}}

        adapter = _adapter(lambda r: httpx.Response(200, json=raw))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 1

    async def test_weo_error_returns_empty(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(500, json={}))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []


class TestIfsFetch:
    async def test_parses_compact_data(self) -> None:
        compact = _imf_compact_response([("2024-01", "105.2"), ("2024-02", "106.1")])

        adapter = _adapter(lambda r: httpx.Response(200, json=compact))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"CPI_INDEX"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 2
        assert all(obs.country_iso3 == "NGA" for obs in result)
        assert all(obs.indicator_code == "CPI_INDEX" for obs in result)
        assert all(obs.frequency == "monthly" for obs in result)

    async def test_ifs_monthly_to_quarterly_fallback(self) -> None:
        """When monthly IFS returns empty, the adapter retries with quarterly."""
        empty_compact: dict[str, Any] = {"CompactData": {"DataSet": {"Series": {"Obs": []}}}}
        quarterly_compact = _imf_compact_response([("2024-Q1", "110.5")])
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(request.url)
            if "/IFS/M." in url:
                return httpx.Response(200, json=empty_compact)
            if "/IFS/Q." in url:
                return httpx.Response(200, json=quarterly_compact)
            return httpx.Response(200, json={})

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"CPI_INDEX"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 1
        assert result[0].value == 110.5
        assert call_count >= 2

    async def test_ifs_error_returns_empty(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(500, json={}))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"CPI_INDEX"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []


class TestBopFetch:
    async def test_parses_bop_compact_data(self) -> None:
        compact = _imf_compact_response([("2023", "500.0"), ("2024", "-200.0")])

        adapter = _adapter(lambda r: httpx.Response(200, json=compact))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="imf",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"CURRENT_ACCOUNT_USD"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 2
        assert result[0].indicator_code == "CURRENT_ACCOUNT_USD"
        assert result[0].frequency == "quarterly"


class TestDiscover:
    async def test_manifest_covers_all_sub_apis(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={}))
        try:
            manifest = await adapter.discover()
        finally:
            await adapter.close()

        assert manifest.source_id == "imf"
        assert len(manifest.indicators) == 5
        codes = {s.indicator_code for s in manifest.indicators}
        assert codes == {"GDP_GROWTH", "CPI_YOY", "CPI_INDEX", "POLICY_RATE", "CURRENT_ACCOUNT_USD"}


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={}))
        try:
            report = await adapter.health()
        finally:
            await adapter.close()
        assert report.source_id == "imf"
        assert report.healthy is True
