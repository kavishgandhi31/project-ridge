"""Tests for the read-side repository functions.

Integration tests — these seed the DB via the seed loader, then
verify that the repo functions return the correct domain shapes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from hornet.db.repos.country import list_countries, load_iso2_to_iso3_map
from hornet.db.repos.source_indicator import list_source_indicators
from hornet.db.session import session_scope
from hornet.seeds.loader import (
    load_countries_from_yaml,
    load_source_indicators_from_yaml,
    seed_countries,
    seed_source_indicators,
)

_NOW = datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC)


async def _clean_and_seed() -> None:
    """Wipe registries and reseed from the packaged YAML files."""
    async with session_scope() as session:
        await session.execute(text("DELETE FROM source_indicator"))
        await session.execute(text("DELETE FROM country"))
    country_specs = load_countries_from_yaml()
    indicator_specs = load_source_indicators_from_yaml()
    async with session_scope() as session:
        await seed_countries(session, country_specs, now=_NOW)
        await seed_source_indicators(session, indicator_specs, now=_NOW)


class TestListCountries:
    async def test_returns_all_enabled_countries(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            countries = await list_countries(session)
        assert len(countries) == 5
        assert {c.iso3 for c in countries} == {"NGA", "TUR", "ZAF", "BRA", "POL"}

    async def test_results_are_sorted_by_iso3(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            countries = await list_countries(session)
        iso3s = [c.iso3 for c in countries]
        assert iso3s == sorted(iso3s)


class TestLoadIso2ToIso3Map:
    async def test_returns_correct_mapping(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            mapping = await load_iso2_to_iso3_map(session)
        assert mapping == {
            "NG": "NGA",
            "TR": "TUR",
            "ZA": "ZAF",
            "BR": "BRA",
            "PL": "POL",
        }


class TestListSourceIndicators:
    async def test_returns_all_enabled(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            indicators = await list_source_indicators(session)
        assert len(indicators) == 93  # expanded with treasury curve, commodities, global equity

    async def test_filter_by_source_id(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            fred_indicators = await list_source_indicators(session, source_id="fred")
        assert len(fred_indicators) == 39  # 10 per-country + 29 global
        assert all(s.source_id == "fred" for s in fred_indicators)

    async def test_filter_by_indicator_code(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            cpi_indicators = await list_source_indicators(session, indicator_code="CPI_YOY")
        # 5 FRED CPI (annual) + 1 WB CPI (annual) + 1 IMF WEO CPI (forecast) = 7
        assert len(cpi_indicators) == 7
        assert all(s.indicator_code == "CPI_YOY" for s in cpi_indicators)

    async def test_combined_filters(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            indicators = await list_source_indicators(
                session, source_id="worldbank", indicator_code="GDP_GROWTH"
            )
        assert len(indicators) == 1
        assert indicators[0].source_id == "worldbank"
        assert indicators[0].source_native_code == "NY.GDP.MKTP.KD.ZG"

    async def test_results_are_domain_objects(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            indicators = await list_source_indicators(session, source_id="fred")
        for spec in indicators:
            assert isinstance(spec.countries_iso3, frozenset)
            assert spec.enabled is True
