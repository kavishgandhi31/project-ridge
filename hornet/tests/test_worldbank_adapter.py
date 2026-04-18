"""Tests for the WorldBank SourceAdapter.

All tests use ``httpx.MockTransport`` — no real WorldBank API calls,
no network. Tests exercise the parse quirks (ISO2->ISO3 mapping, null
handling, year-string dates), the fetch orchestration (pagination,
country filter, bulk strategy), and the discover manifest.

Phase 2 note: the adapter no longer carries a hardcoded indicator
list or ISO2->ISO3 map. Tests now provide both explicitly in the
constructor — the same shapes the ingest factory loads from the DB.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import httpx

from hornet.adapters.worldbank import WorldBankAdapter
from hornet.domain import FetchRequest, SourceIndicatorSpec


def _pilot_iso_map() -> dict[str, str]:
    """ISO2 -> ISO3 map for the 5 pilot countries."""
    return {
        "NG": "NGA",
        "TR": "TUR",
        "ZA": "ZAF",
        "BR": "BRA",
        "PL": "POL",
    }


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    """Build the 7 WorldBank indicator fixture used across tests.

    Mirrors the hardcoded Phase 1 ``_INDICATORS`` list that the
    adapter used to own internally. Test-only; production callers
    load the same data from the ``source_indicator`` DB table.
    """
    all_pilots = frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"})
    pairs: list[tuple[str, str]] = [
        ("NY.GDP.MKTP.KD.ZG", "GDP_GROWTH"),
        ("FP.CPI.TOTL.ZG", "CPI_YOY"),
        ("BN.CAB.XOKA.GD.ZS", "CURRENT_ACCOUNT_GDP"),
        ("FI.RES.TOTL.MO", "RESERVES_MONTHS_IMPORTS"),
        ("GC.DOD.TOTL.GD.ZS", "GOVT_DEBT_GDP"),
        ("SL.UEM.TOTL.ZS", "UNEMPLOYMENT"),
        ("NE.TRD.GNFS.ZS", "TRADE_OPENNESS"),
    ]
    return [
        SourceIndicatorSpec(
            source_id="worldbank",
            source_native_code=wb_id,
            indicator_code=canonical,
            frequency="annual",
            countries_iso3=all_pilots,
        )
        for wb_id, canonical in pairs
    ]


# A minimal two-page WorldBank-shaped response for one indicator.
_PAGE_1 = [
    {"page": 1, "pages": 2, "per_page": 2, "total": 4},
    [
        {"country": {"id": "NG"}, "date": "2023", "value": 3.5},
        {"country": {"id": "TR"}, "date": "2023", "value": 4.2},
    ],
]
_PAGE_2 = [
    {"page": 2, "pages": 2, "per_page": 2, "total": 4},
    [
        {"country": {"id": "BR"}, "date": "2023", "value": 2.9},
        {"country": {"id": "PL"}, "date": "2023", "value": 3.1},
    ],
]

# Records demonstrating every parse quirk.
_QUIRKY_RECORDS: list[dict[str, object]] = [
    {"country": {"id": "NG"}, "date": "2022", "value": 5.0},  # valid
    {"country": {"id": "NG"}, "date": "2023", "value": None},  # null, skip
    {"country": {"id": "ZA"}, "date": "2023", "value": 7.2},  # valid
    {"country": {"id": "WLD"}, "date": "2023", "value": 3.3},  # regional aggregate, skip
    {"country": {"id": "HIC"}, "date": "2023", "value": 4.1},  # aggregate, skip
    {"country": {"id": "BR"}, "date": "2023", "value": "nope"},  # unparseable, skip
    {"country": {"id": "PL"}, "date": "", "value": 1.2},  # empty date, skip
]


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: Sequence[SourceIndicatorSpec] | None = None,
    iso2_to_iso3: Mapping[str, str] | None = None,
) -> WorldBankAdapter:
    return WorldBankAdapter(
        indicators=indicators if indicators is not None else _pilot_indicators(),
        iso2_to_iso3=iso2_to_iso3 if iso2_to_iso3 is not None else _pilot_iso_map(),
        requests_per_minute=600000,
        transport=httpx.MockTransport(handler),
    )


class TestParse:
    def test_parses_happy_path(self) -> None:
        records = [
            {"country": {"id": "NG"}, "date": "2023", "value": 3.5},
            {"country": {"id": "BR"}, "date": "2023", "value": 2.9},
        ]
        df = WorldBankAdapter._parse(records, _pilot_iso_map())
        assert len(df) == 2
        assert set(df["iso3"]) == {"NGA", "BRA"}

    def test_skips_null_values(self) -> None:
        df = WorldBankAdapter._parse(_QUIRKY_RECORDS, _pilot_iso_map())
        # Expected to keep: NG/2022 (5.0), ZA/2023 (7.2). 5 others skipped.
        assert len(df) == 2
        assert set(df["iso3"]) == {"NGA", "ZAF"}

    def test_maps_iso2_to_iso3(self) -> None:
        records = [{"country": {"id": "NG"}, "date": "2023", "value": 3.5}]
        df = WorldBankAdapter._parse(records, _pilot_iso_map())
        assert df["iso3"].iloc[0] == "NGA"

    def test_skips_regional_aggregates(self) -> None:
        # WLD and HIC look like valid country codes to the WB API but
        # don't map to any ISO3 country — they should be dropped.
        records = [
            {"country": {"id": "WLD"}, "date": "2023", "value": 1.0},
            {"country": {"id": "HIC"}, "date": "2023", "value": 2.0},
        ]
        df = WorldBankAdapter._parse(records, _pilot_iso_map())
        assert df.empty

    def test_parses_year_string_as_datetime(self) -> None:
        records = [{"country": {"id": "NG"}, "date": "2024", "value": 3.5}]
        df = WorldBankAdapter._parse(records, _pilot_iso_map())
        assert df["date"].iloc[0].year == 2024
        assert df["date"].iloc[0].month == 1
        assert df["date"].iloc[0].day == 1

    def test_empty_input_returns_empty_df(self) -> None:
        assert WorldBankAdapter._parse([], _pilot_iso_map()).empty

    def test_unknown_iso2_is_dropped(self) -> None:
        """A country code not in the injected map is silently dropped.

        Exercises the "caller controls the map, not a hardcoded dict"
        property of the Phase 2 refactor: if BRA is removed from the
        map, BR records are dropped even though they're valid ISO2.
        """
        records = [
            {"country": {"id": "NG"}, "date": "2023", "value": 3.5},
            {"country": {"id": "BR"}, "date": "2023", "value": 2.9},
        ]
        narrow_map = {"NG": "NGA"}  # deliberately omits BR
        df = WorldBankAdapter._parse(records, narrow_map)
        assert len(df) == 1
        assert df["iso3"].iloc[0] == "NGA"


class TestConstructor:
    async def test_drops_non_worldbank_indicators(self) -> None:
        """Foreign source_ids are filtered out, not passed to discover/fetch."""
        mixed = [
            SourceIndicatorSpec(
                source_id="worldbank",
                source_native_code="NY.GDP.MKTP.KD.ZG",
                indicator_code="GDP_GROWTH",
                frequency="annual",
                countries_iso3=frozenset({"NGA"}),
            ),
            SourceIndicatorSpec(
                source_id="fred",  # wrong source
                source_native_code="FPCPITOTLZGNGA",
                indicator_code="CPI_YOY",
                frequency="annual",
                countries_iso3=frozenset({"NGA"}),
            ),
        ]
        adapter = _adapter(
            lambda r: httpx.Response(200, json=[{"pages": 1}, []]),
            indicators=mixed,
        )
        try:
            manifest = await adapter.discover()
            # Only the WB row should appear in the manifest.
            assert len(manifest.indicators) == 1
            assert manifest.indicators[0].indicator_code == "GDP_GROWTH"
        finally:
            await adapter.close()


class TestFetch:
    async def test_pagination_walks_multiple_pages(self) -> None:
        """Handler returns page 1 or page 2 depending on the query params."""

        def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(200, json=_PAGE_1)
            return httpx.Response(200, json=_PAGE_2)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="worldbank",
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()

        # 4 records on 2 pages, all 4 pilot countries (NGA/TUR/BRA/POL),
        # all with the same indicator code.
        assert len(result) == 4
        countries_seen = {obs.country_iso3 for obs in result}
        assert countries_seen == {"NGA", "TUR", "BRA", "POL"}
        assert all(obs.indicator_code == "GDP_GROWTH" for obs in result)
        assert all(obs.source_id == "worldbank" for obs in result)
        assert all(obs.frequency == "annual" for obs in result)

    async def test_country_filter_restricts_output(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(200, json=_PAGE_1)
            return httpx.Response(200, json=_PAGE_2)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="worldbank",
                    countries_iso3=frozenset({"NGA"}),
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 1
        assert result[0].country_iso3 == "NGA"
        assert result[0].value == 3.5

    async def test_malformed_response_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="worldbank",
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []

    async def test_404_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "indicator not found"})

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="worldbank",
                    indicator_codes=frozenset({"GDP_GROWTH"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []


class TestDiscover:
    async def test_manifest_exposes_seven_indicators(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json=[{"pages": 1}, []]))
        try:
            manifest = await adapter.discover()
        finally:
            await adapter.close()

        assert manifest.source_id == "worldbank"
        assert len(manifest.indicators) == 7

        canonical_codes = {spec.indicator_code for spec in manifest.indicators}
        assert canonical_codes == {
            "GDP_GROWTH",
            "CPI_YOY",
            "CURRENT_ACCOUNT_GDP",
            "RESERVES_MONTHS_IMPORTS",
            "GOVT_DEBT_GDP",
            "UNEMPLOYMENT",
            "TRADE_OPENNESS",
        }

    async def test_each_indicator_covers_all_pilots(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json=[{"pages": 1}, []]))
        try:
            manifest = await adapter.discover()
        finally:
            await adapter.close()

        for spec in manifest.indicators:
            assert spec.countries_iso3 == frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"})
            assert spec.frequency == "annual"


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, json=[]))
        try:
            report = await adapter.health()
        finally:
            await adapter.close()
        assert report.source_id == "worldbank"
        assert report.healthy is True
