"""Tests for the IMF SourceAdapter (new SDMX 3.0 API).

All tests use ``httpx.MockTransport`` -- no real IMF API calls, no network.
Captured fixtures under ``tests/fixtures/imf_sdmx3/`` provide realistic
response bodies; tests route the mock transport to serve the right
fixture based on the request URL.

Coverage: constructor prefix-routing validation, SDMX 3.0 URL + header
construction, WEO bulk-per-indicator parse path, and the unified
``fetch`` orchestration that mixes WEO and SDMX 3.0 specs.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ridge.adapters.imf import IMFAdapter
from ridge.domain import FetchRequest, SourceIndicatorSpec

FIXTURES = Path(__file__).parent / "fixtures" / "imf_sdmx3"


def _load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


def _cpi_spec(iso3: str) -> SourceIndicatorSpec:
    return SourceIndicatorSpec(
        source_id="imf",
        source_native_code="cpi:CPI._T.IX.M",
        indicator_code="CPI_INDEX",
        frequency="monthly",
        countries_iso3=frozenset({iso3}),
    )


def _bop_spec(iso3: str) -> SourceIndicatorSpec:
    return SourceIndicatorSpec(
        source_id="imf",
        source_native_code="bop:NETCD_T.CAB.USD.Q",
        indicator_code="CURRENT_ACCOUNT_USD",
        frequency="quarterly",
        countries_iso3=frozenset({iso3}),
    )


def _weo_spec(iso3: str) -> SourceIndicatorSpec:
    return SourceIndicatorSpec(
        source_id="imf",
        source_native_code="weo:NGDP_RPCH",
        indicator_code="GDP_GROWTH",
        frequency="forecast",
        countries_iso3=frozenset({iso3}),
    )


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: list[SourceIndicatorSpec],
) -> IMFAdapter:
    return IMFAdapter(
        indicators=indicators,
        requests_per_minute=600000,  # effectively disable rate limit
        transport=httpx.MockTransport(handler),
    )


_WEO_RESPONSE: dict[str, Any] = {
    "values": {
        "NGDP_RPCH": {
            "USA": {"2024": 2.8, "2025": 2.1, "2026": 2.0},
            "POL": {"2024": 3.0, "2025": 3.2, "2026": 3.4},
        }
    }
}


# ---------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------


class TestConstructor:
    async def test_drops_non_imf_indicators(self) -> None:
        foreign = SourceIndicatorSpec(
            source_id="worldbank",
            source_native_code="cpi:CPI._T.IX.M",
            indicator_code="CPI_INDEX",
            frequency="monthly",
            countries_iso3=frozenset({"USA"}),
        )
        adapter = _adapter(
            lambda r: httpx.Response(200, json={"data": {}}),
            indicators=[_cpi_spec("USA"), foreign],
        )
        assert len(adapter._indicators) == 1
        assert adapter._indicators[0].source_id == "imf"
        await adapter.close()

    async def test_drops_unknown_prefix(self) -> None:
        unknown = SourceIndicatorSpec(
            source_id="imf",
            source_native_code="zzz:NGDP_RPCH",
            indicator_code="GDP_GROWTH",
            frequency="forecast",
            countries_iso3=frozenset({"USA"}),
        )
        adapter = _adapter(
            lambda r: httpx.Response(200, json={}),
            indicators=[_cpi_spec("USA"), unknown],
        )
        assert len(adapter._indicators) == 1
        assert adapter._indicators[0].source_native_code.startswith("cpi:")
        await adapter.close()

    async def test_partitions_specs_by_prefix(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(200, json={}),
            indicators=[_weo_spec("USA"), _cpi_spec("USA"), _bop_spec("USA")],
        )
        assert len(adapter._weo_specs) == 1
        assert len(adapter._sdmx3_specs) == 2
        await adapter.close()


# ---------------------------------------------------------------------
# SDMX 3.0 fetch path
# ---------------------------------------------------------------------


class TestSdmx3Fetch:
    async def test_builds_correct_url_and_sends_accept_header(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["accept"] = request.headers.get("accept")
            return httpx.Response(200, json=_load_fixture("cpi_usa_monthly.json"))

        adapter = _adapter(handler, indicators=[_cpi_spec("USA")])
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA"}))
        await adapter.fetch(req)
        await adapter.close()

        assert (
            "api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/+/USA.CPI._T.IX.M"
            in captured["url"]
        )
        assert "lastNObservations=60" in captured["url"]
        assert "application/vnd.sdmx.data+json" in captured["accept"]

    async def test_cpi_fixture_produces_observations(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(200, json=_load_fixture("cpi_usa_monthly.json")),
            indicators=[_cpi_spec("USA")],
        )
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA"}))
        obs = await adapter.fetch(req)
        await adapter.close()

        assert len(obs) == 12
        for o in obs:
            assert o.country_iso3 == "USA"
            assert o.indicator_code == "CPI_INDEX"
            assert o.source_id == "imf"
            assert o.frequency == "monthly"
            assert isinstance(o.date, datetime.date)
            assert isinstance(o.value, float)

    async def test_bop_fixture_produces_quarterly_observations(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(200, json=_load_fixture("bop_usa_current_account.json")),
            indicators=[_bop_spec("USA")],
        )
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA"}))
        obs = await adapter.fetch(req)
        await adapter.close()

        assert len(obs) >= 1
        assert all(o.frequency == "quarterly" for o in obs)
        assert all(o.indicator_code == "CURRENT_ACCOUNT_USD" for o in obs)
        # USA current account balance is structurally negative
        assert all(o.value < 0 for o in obs)

    async def test_404_returns_empty_observations(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(404, json={"status": 404, "message": "not found"}),
            indicators=[_cpi_spec("USA")],
        )
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA"}))
        obs = await adapter.fetch(req)
        await adapter.close()
        assert obs == []

    async def test_empty_response_returns_empty_observations(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(200, json={"data": {"dataSets": [], "structures": []}}),
            indicators=[_cpi_spec("USA")],
        )
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA"}))
        obs = await adapter.fetch(req)
        await adapter.close()
        assert obs == []


# ---------------------------------------------------------------------
# WEO fetch path
# ---------------------------------------------------------------------


class TestWeoFetch:
    async def test_weo_single_bulk_call_covers_multiple_countries(self) -> None:
        # Production shape: one spec per indicator with a frozenset of all
        # covered countries -- not one spec per country.
        spec = SourceIndicatorSpec(
            source_id="imf",
            source_native_code="weo:NGDP_RPCH",
            indicator_code="GDP_GROWTH",
            frequency="forecast",
            countries_iso3=frozenset({"USA", "POL"}),
        )
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_WEO_RESPONSE)

        adapter = _adapter(handler, indicators=[spec])
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA", "POL"}))
        obs = await adapter.fetch(req)
        await adapter.close()

        assert call_count == 1
        usa = [o for o in obs if o.country_iso3 == "USA"]
        pol = [o for o in obs if o.country_iso3 == "POL"]
        assert len(usa) == 3
        assert len(pol) == 3
        assert all(o.indicator_code == "GDP_GROWTH" for o in obs)

    async def test_weo_respects_country_filter(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(200, json=_WEO_RESPONSE),
            indicators=[_weo_spec("USA"), _weo_spec("POL")],
        )
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA"}))
        obs = await adapter.fetch(req)
        await adapter.close()
        assert {o.country_iso3 for o in obs} == {"USA"}

    async def test_weo_skips_none_values(self) -> None:
        resp: dict[str, Any] = {"values": {"NGDP_RPCH": {"USA": {"2023": 2.9, "2024": None}}}}
        adapter = _adapter(
            lambda r: httpx.Response(200, json=resp),
            indicators=[_weo_spec("USA")],
        )
        req = FetchRequest(
            source_id="imf",
            countries_iso3=frozenset({"USA"}),
            indicator_codes=frozenset({"GDP_GROWTH"}),
        )
        obs = await adapter.fetch(req)
        await adapter.close()
        assert len(obs) == 1
        assert obs[0].value == 2.9

    async def test_weo_error_returns_empty(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(500, json={}),
            indicators=[_weo_spec("USA")],
        )
        req = FetchRequest(source_id="imf", indicator_codes=frozenset({"GDP_GROWTH"}))
        obs = await adapter.fetch(req)
        await adapter.close()
        assert obs == []


# ---------------------------------------------------------------------
# Mixed orchestration
# ---------------------------------------------------------------------


class TestMixedFetch:
    async def test_mixed_specs_route_to_correct_endpoints(self) -> None:
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            urls.append(url)
            if "datamapper" in url:
                return httpx.Response(200, json=_WEO_RESPONSE)
            if "api.imf.org" in url:
                return httpx.Response(200, json=_load_fixture("cpi_usa_monthly.json"))
            return httpx.Response(404)

        adapter = _adapter(
            handler,
            indicators=[_weo_spec("USA"), _cpi_spec("USA")],
        )
        req = FetchRequest(source_id="imf", countries_iso3=frozenset({"USA"}))
        obs = await adapter.fetch(req)
        await adapter.close()

        assert any("datamapper" in u for u in urls)
        assert any("api.imf.org" in u for u in urls)
        assert {o.indicator_code for o in obs} == {"GDP_GROWTH", "CPI_INDEX"}

    async def test_indicator_code_filter_applies(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "datamapper" in str(request.url):
                return httpx.Response(200, json=_WEO_RESPONSE)
            return httpx.Response(200, json=_load_fixture("cpi_usa_monthly.json"))

        adapter = _adapter(
            handler,
            indicators=[_weo_spec("USA"), _cpi_spec("USA")],
        )
        req = FetchRequest(
            source_id="imf",
            countries_iso3=frozenset({"USA"}),
            indicator_codes=frozenset({"GDP_GROWTH"}),
        )
        obs = await adapter.fetch(req)
        await adapter.close()
        assert {o.indicator_code for o in obs} == {"GDP_GROWTH"}


# ---------------------------------------------------------------------
# Manifest + health
# ---------------------------------------------------------------------


class TestDiscover:
    async def test_manifest_covers_all_indicators(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(200, json={}),
            indicators=[_weo_spec("USA"), _cpi_spec("USA"), _bop_spec("USA")],
        )
        manifest = await adapter.discover()
        await adapter.close()
        assert manifest.source_id == "imf"
        assert len(manifest.indicators) == 3


class TestHealth:
    async def test_health_reports_healthy(self) -> None:
        adapter = _adapter(
            lambda r: httpx.Response(200, json={}),
            indicators=[_weo_spec("USA")],
        )
        report = await adapter.health()
        await adapter.close()
        assert report.source_id == "imf"
        assert report.healthy is True
