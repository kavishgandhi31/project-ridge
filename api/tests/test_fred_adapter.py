"""Tests for the FRED SourceAdapter.

All tests use ``httpx.MockTransport`` — no real FRED API calls, no
network, no API key needed. Tests exercise the parser quirks (dot
sentinel, invalid values, missing fields), the fetch orchestration
(country/indicator filtering, graceful 404 handling, pilot-set
fallback), and the discover manifest.

Phase 2 note: the adapter no longer carries a hardcoded pilot-series
dict. Tests now provide an explicit list of SourceIndicatorSpec in
the constructor — the same shape the ingest factory loads from the
DB. ``_pilot_indicators()`` below builds the 5-country x 2-indicator
fixture the original tests depended on.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx

from ridge.adapters.fred import FredAdapter
from ridge.domain import FetchRequest, SourceIndicatorSpec

_VALID_RESPONSE = {
    "observations": [
        {"date": "2022-01-01", "value": "15.7"},
        {"date": "2023-01-01", "value": "24.5"},
        {"date": "2024-01-01", "value": "28.9"},
    ]
}

_RESPONSE_WITH_MISSING = {
    "observations": [
        {"date": "2020-01-01", "value": "5.0"},
        {"date": "2021-01-01", "value": "."},  # dot sentinel
        {"date": "2022-01-01", "value": "7.2"},
        {"date": "2023-01-01", "value": "not-a-number"},  # invalid string
    ]
}


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    """Build the 10-series pilot fixture: 5 countries x 2 indicators.

    Mirrors the hardcoded Phase 1 ``_PILOT_SERIES`` dict that the
    adapter used to own internally. Test-only; production callers
    load the same data from the ``source_indicator`` DB table.
    """
    countries = [
        ("NGA", "FPCPITOTLZGNGA", "NGANGDPRPCH"),
        ("TUR", "FPCPITOTLZGTUR", "TURNGDPRPCH"),
        ("ZAF", "FPCPITOTLZGZAF", "ZAFNGDPRPCH"),
        ("BRA", "FPCPITOTLZGBRA", "BRANGDPRPCH"),
        ("POL", "FPCPITOTLZGPOL", "POLNGDPRPCH"),
    ]
    specs: list[SourceIndicatorSpec] = []
    for iso3, cpi_code, gdp_code in countries:
        specs.append(
            SourceIndicatorSpec(
                source_id="fred",
                source_native_code=cpi_code,
                indicator_code="CPI_YOY",
                frequency="annual",
                countries_iso3=frozenset({iso3}),
            )
        )
        specs.append(
            SourceIndicatorSpec(
                source_id="fred",
                source_native_code=gdp_code,
                indicator_code="GDP_GROWTH",
                frequency="annual",
                countries_iso3=frozenset({iso3}),
            )
        )
    return specs


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: Sequence[SourceIndicatorSpec] | None = None,
) -> FredAdapter:
    """Build a FredAdapter with a mock transport and optional custom indicators."""
    return FredAdapter(
        api_key="test_key",
        indicators=indicators if indicators is not None else _pilot_indicators(),
        requests_per_minute=600000,  # effectively disable rate limit
        transport=httpx.MockTransport(handler),
    )


class TestParse:
    def test_parses_valid_response(self) -> None:
        df = FredAdapter._parse(_VALID_RESPONSE)
        assert len(df) == 3
        assert df["value"].tolist() == [15.7, 24.5, 28.9]

    def test_drops_dot_sentinel_rows(self) -> None:
        df = FredAdapter._parse(_RESPONSE_WITH_MISSING)
        # Two rows dropped: the "." sentinel and the "not-a-number" string.
        assert len(df) == 2
        assert df["value"].tolist() == [5.0, 7.2]

    def test_empty_observations_returns_empty_df(self) -> None:
        df = FredAdapter._parse({"observations": []})
        assert df.empty

    def test_non_dict_returns_empty_df(self) -> None:
        df = FredAdapter._parse("not a dict")
        assert df.empty

    def test_missing_columns_returns_empty_df(self) -> None:
        df = FredAdapter._parse({"observations": [{"irrelevant": "data"}]})
        assert df.empty


class TestConstructor:
    async def test_drops_non_fred_indicators(self) -> None:
        """Foreign source_ids are filtered out with a warning, not kept."""
        mixed = [
            SourceIndicatorSpec(
                source_id="fred",
                source_native_code="FPCPITOTLZGNGA",
                indicator_code="CPI_YOY",
                frequency="annual",
                countries_iso3=frozenset({"NGA"}),
            ),
            SourceIndicatorSpec(
                source_id="worldbank",  # wrong source
                source_native_code="NY.GDP.MKTP.KD.ZG",
                indicator_code="GDP_GROWTH",
                frequency="annual",
                countries_iso3=frozenset({"NGA"}),
            ),
        ]
        adapter = _adapter(
            lambda r: httpx.Response(200, json={"observations": []}),
            indicators=mixed,
        )
        try:
            # Only the FRED row should have made it into _by_country.
            assert set(adapter._by_country.keys()) == {"NGA"}
            nga_specs = adapter._by_country["NGA"]
            assert len(nga_specs) == 1
            assert nga_specs[0].source_id == "fred"
        finally:
            await adapter.close()


class TestFetch:
    async def test_returns_observations_with_correct_fields(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_VALID_RESPONSE)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="fred",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"CPI_YOY"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 3
        for obs in result:
            assert obs.country_iso3 == "NGA"
            assert obs.indicator_code == "CPI_YOY"
            assert obs.source_id == "fred"
            assert obs.frequency == "annual"
        assert [o.value for o in result] == [15.7, 24.5, 28.9]

    async def test_404_returns_empty_list_gracefully(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error_message": "series not found"})

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="fred",
                    countries_iso3=frozenset({"NGA"}),
                )
            )
        finally:
            await adapter.close()

        # 404 is caught inside _fetch_series; the adapter returns []
        # rather than raising. This is the v1 graceful-degradation
        # pattern: one broken series never tanks the whole fetch.
        assert result == []

    async def test_unknown_country_is_skipped(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_VALID_RESPONSE)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="fred",
                    countries_iso3=frozenset({"XYZ"}),  # not in the fixture
                )
            )
        finally:
            await adapter.close()

        assert result == []

    async def test_empty_country_filter_means_all_pilots(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_VALID_RESPONSE)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="fred",
                    indicator_codes=frozenset({"CPI_YOY"}),
                )
            )
        finally:
            await adapter.close()

        countries_seen = {obs.country_iso3 for obs in result}
        assert countries_seen == {"NGA", "TUR", "ZAF", "BRA", "POL"}

    async def test_indicator_filter_restricts_output(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_VALID_RESPONSE)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="fred",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()

        assert all(obs.indicator_code == "GDP_GROWTH" for obs in result)
        assert len(result) == 3  # only one series matched


class TestDiscover:
    async def test_manifest_covers_all_pilot_countries(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={"observations": []}))
        try:
            manifest = await adapter.discover()
        finally:
            await adapter.close()

        assert manifest.source_id == "fred"
        # 5 countries x 2 indicators each = 10 IndicatorSpec entries.
        assert len(manifest.indicators) == 10

        all_countries: set[str] = set()
        all_canonical_codes: set[str] = set()
        for spec in manifest.indicators:
            all_countries.update(spec.countries_iso3)
            all_canonical_codes.add(spec.indicator_code)

        assert all_countries == {"NGA", "TUR", "ZAF", "BRA", "POL"}
        assert all_canonical_codes == {"CPI_YOY", "GDP_GROWTH"}


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json={}))
        try:
            report = await adapter.health()
        finally:
            await adapter.close()

        assert report.source_id == "fred"
        assert report.healthy is True
