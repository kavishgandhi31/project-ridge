"""Tests for the BIS SourceAdapter.

All tests use ``httpx.MockTransport`` -- no real BIS API calls.
Tests exercise the CSV parsing with BIS date format quirks
(quarterly, monthly, annual), country/indicator filtering,
and the discover manifest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import httpx

from hornet.adapters.bis import BISAdapter
from hornet.domain import FetchRequest, SourceIndicatorSpec


def _pilot_iso_map() -> dict[str, str]:
    """ISO3 -> ISO2 map for pilot countries."""
    return {
        "TUR": "TR",
        "ZAF": "ZA",
        "BRA": "BR",
        "POL": "PL",
    }


def _pilot_indicators() -> list[SourceIndicatorSpec]:
    """3 BIS indicators for 4 pilot countries (NGA excluded)."""
    covered = frozenset({"TUR", "ZAF", "BRA", "POL"})
    indicators = [
        ("WS_CREDIT_GAP", "CREDIT_GAP", "quarterly"),
        ("WS_SPP", "PROPERTY_PRICE", "quarterly"),
        ("WS_EER", "REER", "monthly"),
    ]
    return [
        SourceIndicatorSpec(
            source_id="bis",
            source_native_code=native,
            indicator_code=canonical,
            frequency=freq,
            countries_iso3=covered,
        )
        for native, canonical, freq in indicators
    ]


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    indicators: Sequence[SourceIndicatorSpec] | None = None,
    iso3_to_iso2: Mapping[str, str] | None = None,
) -> BISAdapter:
    return BISAdapter(
        indicators=indicators if indicators is not None else _pilot_indicators(),
        iso3_to_iso2=iso3_to_iso2 if iso3_to_iso2 is not None else _pilot_iso_map(),
        requests_per_minute=600000,
        transport=httpx.MockTransport(handler),
    )


# Sample BIS CSV responses
_QUARTERLY_CSV = (
    "TIME_PERIOD,OBS_VALUE,REF_AREA\n"
    "2023-Q1,5.2,TR\n"
    "2023-Q2,6.1,TR\n"
    "2023-Q3,7.0,TR\n"
    "2023-Q4,8.3,TR\n"
)

_MONTHLY_CSV = (
    "TIME_PERIOD,OBS_VALUE,REF_AREA\n2024-01,105.2,TR\n2024-02,106.1,TR\n2024-03,104.8,TR\n"
)

_ANNUAL_CSV = "TIME_PERIOD,OBS_VALUE\n2022,150.0\n2023,155.5\n"


class TestParseCsv:
    def test_parses_quarterly_dates(self) -> None:
        df = BISAdapter._parse_csv(_QUARTERLY_CSV)
        assert len(df) == 4
        assert df["date"].iloc[0].year == 2023
        assert df["date"].iloc[0].month == 1  # Q1 -> January
        assert df["date"].iloc[1].month == 4  # Q2 -> April
        assert df["date"].iloc[2].month == 7  # Q3 -> July
        assert df["date"].iloc[3].month == 10  # Q4 -> October

    def test_parses_monthly_dates(self) -> None:
        df = BISAdapter._parse_csv(_MONTHLY_CSV)
        assert len(df) == 3
        assert df["date"].iloc[0].month == 1
        assert df["date"].iloc[1].month == 2

    def test_parses_annual_dates(self) -> None:
        df = BISAdapter._parse_csv(_ANNUAL_CSV)
        assert len(df) == 2
        assert df["date"].iloc[0].year == 2022
        assert df["date"].iloc[0].month == 1  # snaps to Jan 1

    def test_coerces_non_numeric_values(self) -> None:
        csv = "TIME_PERIOD,OBS_VALUE\n2024-Q1,5.2\n2024-Q2,N/A\n2024-Q3,6.0\n"
        df = BISAdapter._parse_csv(csv)
        assert len(df) == 2

    def test_empty_csv_returns_empty_df(self) -> None:
        assert BISAdapter._parse_csv("").empty
        assert BISAdapter._parse_csv("   ").empty

    def test_missing_columns_returns_empty(self) -> None:
        csv = "FOO,BAR\n1,2\n"
        assert BISAdapter._parse_csv(csv).empty

    def test_handles_alternative_column_names(self) -> None:
        csv = "DATE,VALUE\n2024-Q1,3.0\n"
        df = BISAdapter._parse_csv(csv)
        assert len(df) == 1


class TestParseBisDate:
    def test_quarterly(self) -> None:
        ts = BISAdapter._parse_bis_date("2024-Q3")
        assert ts is not None
        assert ts.year == 2024
        assert ts.month == 7

    def test_monthly(self) -> None:
        ts = BISAdapter._parse_bis_date("2024-06")
        assert ts is not None
        assert ts.year == 2024
        assert ts.month == 6

    def test_annual(self) -> None:
        ts = BISAdapter._parse_bis_date("2024")
        assert ts is not None
        assert ts.year == 2024
        assert ts.month == 1

    def test_invalid_returns_none(self) -> None:
        assert BISAdapter._parse_bis_date("not-a-date") is None


class TestFetch:
    async def test_returns_observations_from_csv_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_QUARTERLY_CSV)

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="bis",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"CREDIT_GAP"}),
                )
            )
        finally:
            await adapter.close()

        assert len(result) == 4
        for obs in result:
            assert obs.country_iso3 == "TUR"
            assert obs.indicator_code == "CREDIT_GAP"
            assert obs.source_id == "bis"
            assert obs.frequency == "quarterly"
        assert [o.value for o in result] == [5.2, 6.1, 7.0, 8.3]

    async def test_error_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="error")

        adapter = _adapter(handler)
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="bis",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"CREDIT_GAP"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []

    async def test_unknown_country_skipped(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, text=_QUARTERLY_CSV))
        try:
            result = await adapter.fetch(
                FetchRequest(
                    source_id="bis",
                    countries_iso3=frozenset({"XYZ"}),
                )
            )
        finally:
            await adapter.close()
        assert result == []

    async def test_country_without_iso2_mapping_skipped(self) -> None:
        """If a country is in the indicator list but not in the ISO map, skip it."""
        indicators = [
            SourceIndicatorSpec(
                source_id="bis",
                source_native_code="WS_CREDIT_GAP",
                indicator_code="CREDIT_GAP",
                frequency="quarterly",
                countries_iso3=frozenset({"NGA"}),
            )
        ]
        adapter = _adapter(
            lambda r: httpx.Response(200, text=_QUARTERLY_CSV),
            indicators=indicators,
            iso3_to_iso2={},  # NGA has no ISO2 mapping
        )
        try:
            result = await adapter.fetch(FetchRequest(source_id="bis"))
        finally:
            await adapter.close()
        assert result == []

    async def test_indicator_filter_restricts_output(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, text=_QUARTERLY_CSV)

        adapter = _adapter(handler)
        try:
            await adapter.fetch(
                FetchRequest(
                    source_id="bis",
                    countries_iso3=frozenset({"TUR"}),
                    indicator_codes=frozenset({"CREDIT_GAP"}),
                )
            )
        finally:
            await adapter.close()

        assert call_count == 1


class TestDiscover:
    async def test_manifest_covers_all_indicators(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, text=""))
        try:
            manifest = await adapter.discover()
        finally:
            await adapter.close()

        assert manifest.source_id == "bis"
        assert len(manifest.indicators) == 3
        codes = {s.indicator_code for s in manifest.indicators}
        assert codes == {"CREDIT_GAP", "PROPERTY_PRICE", "REER"}


class TestHealth:
    async def test_health_returns_report(self) -> None:
        adapter = _adapter(lambda r: httpx.Response(200, text=""))
        try:
            report = await adapter.health()
        finally:
            await adapter.close()
        assert report.source_id == "bis"
        assert report.healthy is True
