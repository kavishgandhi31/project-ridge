"""Tests for the YAML seed loader and DB upsert functions.

Split into two tiers:

1. **YAML parsing** — pure functions, no DB. Exercises
   ``load_countries_from_yaml`` and ``load_source_indicators_from_yaml``
   against both the packaged seed files and hand-crafted YAML snippets.

2. **DB upserts** — integration tests against docker Postgres.
   Exercises ``seed_countries`` and ``seed_source_indicators`` for
   correctness and idempotency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from textwrap import dedent

import pytest
from sqlalchemy import select, text

from hornet.db.models.country import CountryRow
from hornet.db.models.source_indicator import SourceIndicatorRow
from hornet.db.session import session_scope
from hornet.seeds.loader import (
    load_countries_from_yaml,
    load_source_indicators_from_yaml,
    seed_all,
    seed_countries,
    seed_source_indicators,
)

_NOW = datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC)


# ------------------------------------------------------------------ #
# YAML parsing (no DB)
# ------------------------------------------------------------------ #


class TestLoadCountriesFromYaml:
    def test_parses_packaged_seed_file(self) -> None:
        specs = load_countries_from_yaml()
        assert len(specs) == 5
        iso3s = {s.iso3 for s in specs}
        assert iso3s == {"NGA", "TUR", "ZAF", "BRA", "POL"}

    def test_parses_minimal_yaml(self) -> None:
        yaml_text = dedent("""\
            countries:
              - iso3: TST
                iso2: TT
                name: Testland
        """)
        specs = load_countries_from_yaml(yaml_text)
        assert len(specs) == 1
        assert specs[0].iso3 == "TST"
        assert specs[0].iso2 == "TT"
        assert specs[0].name == "Testland"
        assert specs[0].enabled is True

    def test_rejects_non_mapping_top_level(self) -> None:
        with pytest.raises(ValueError, match="mapping"):
            load_countries_from_yaml("- foo\n- bar\n")

    def test_rejects_missing_countries_key(self) -> None:
        with pytest.raises(ValueError, match="'countries' list"):
            load_countries_from_yaml("other_key: true\n")


class TestLoadSourceIndicatorsFromYaml:
    def test_parses_packaged_seed_file(self) -> None:
        specs = load_source_indicators_from_yaml()
        # 19 FRED (10 per-country + 9 global) + 7 WB + 9 yfinance + 4 OECD
        # + 3 BIS + 15 IMF + 3 GDELT + 1 GNews = 61
        assert len(specs) == 61
        fred_count = sum(1 for s in specs if s.source_id == "fred")
        wb_count = sum(1 for s in specs if s.source_id == "worldbank")
        assert fred_count == 19
        assert wb_count == 7

    def test_parses_minimal_yaml(self) -> None:
        yaml_text = dedent("""\
            source_indicators:
              - source_id: test
                source_native_code: TEST.1
                indicator_code: TEST_IND
                frequency: annual
                countries_iso3: [TST]
        """)
        specs = load_source_indicators_from_yaml(yaml_text)
        assert len(specs) == 1
        assert specs[0].source_id == "test"
        assert specs[0].countries_iso3 == frozenset({"TST"})

    def test_countries_iso3_becomes_frozenset(self) -> None:
        yaml_text = dedent("""\
            source_indicators:
              - source_id: test
                source_native_code: TEST.1
                indicator_code: TEST_IND
                frequency: annual
                countries_iso3: [NGA, TUR, ZAF]
        """)
        specs = load_source_indicators_from_yaml(yaml_text)
        assert specs[0].countries_iso3 == frozenset({"NGA", "TUR", "ZAF"})

    def test_rejects_missing_source_indicators_key(self) -> None:
        with pytest.raises(ValueError, match="'source_indicators' list"):
            load_source_indicators_from_yaml("other: true\n")


# ------------------------------------------------------------------ #
# DB upserts (integration, needs docker Postgres)
# ------------------------------------------------------------------ #


async def _clean_registries() -> None:
    """Delete all rows from country and source_indicator tables."""
    async with session_scope() as session:
        await session.execute(text("DELETE FROM source_indicator"))
        await session.execute(text("DELETE FROM country"))


class TestSeedCountries:
    async def test_inserts_countries(self) -> None:
        await _clean_registries()
        specs = load_countries_from_yaml()

        async with session_scope() as session:
            count = await seed_countries(session, specs, now=_NOW)

        assert count == 5
        async with session_scope() as session:
            rows = (await session.execute(select(CountryRow))).scalars().all()
        assert len(rows) == 5
        assert {r.iso3 for r in rows} == {"NGA", "TUR", "ZAF", "BRA", "POL"}

    async def test_upsert_is_idempotent(self) -> None:
        await _clean_registries()
        specs = load_countries_from_yaml()

        async with session_scope() as session:
            await seed_countries(session, specs, now=_NOW)
        async with session_scope() as session:
            await seed_countries(session, specs, now=_NOW)

        async with session_scope() as session:
            rows = (await session.execute(select(CountryRow))).scalars().all()
        assert len(rows) == 5

    async def test_upsert_updates_changed_fields(self) -> None:
        await _clean_registries()
        specs = load_countries_from_yaml()

        async with session_scope() as session:
            await seed_countries(session, specs, now=_NOW)

        updated_yaml = dedent("""\
            countries:
              - iso3: NGA
                iso2: NG
                name: Nigeria (Updated)
        """)
        updated_specs = load_countries_from_yaml(updated_yaml)
        later = datetime(2026, 5, 1, tzinfo=UTC)

        async with session_scope() as session:
            await seed_countries(session, updated_specs, now=later)

        async with session_scope() as session:
            nga = (
                await session.execute(select(CountryRow).where(CountryRow.iso3 == "NGA"))
            ).scalar_one()
        assert nga.name == "Nigeria (Updated)"
        assert nga.updated_at == later

    async def test_empty_list_is_noop(self) -> None:
        async with session_scope() as session:
            count = await seed_countries(session, [], now=_NOW)
        assert count == 0


class TestSeedSourceIndicators:
    async def test_inserts_source_indicators(self) -> None:
        await _clean_registries()
        specs = load_source_indicators_from_yaml()

        async with session_scope() as session:
            count = await seed_source_indicators(session, specs, now=_NOW)

        assert count == 61
        async with session_scope() as session:
            rows = (await session.execute(select(SourceIndicatorRow))).scalars().all()
        assert len(rows) == 61

    async def test_upsert_is_idempotent(self) -> None:
        await _clean_registries()
        specs = load_source_indicators_from_yaml()

        async with session_scope() as session:
            await seed_source_indicators(session, specs, now=_NOW)
        async with session_scope() as session:
            await seed_source_indicators(session, specs, now=_NOW)

        async with session_scope() as session:
            rows = (await session.execute(select(SourceIndicatorRow))).scalars().all()
        assert len(rows) == 61


class TestSeedAll:
    async def test_seeds_both_tables(self) -> None:
        await _clean_registries()

        n_countries, n_indicators = await seed_all(now=_NOW)

        assert n_countries == 5
        assert n_indicators == 61
