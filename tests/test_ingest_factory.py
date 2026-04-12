"""Tests for the ingest adapter factory.

Integration tests — these seed the DB, then verify that
``build_fred_adapter`` and ``build_worldbank_adapter`` produce
working adapters wired to the correct indicator lists and
country maps. Also exercises the credential-missing error path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import text

from hornet.db.session import session_scope
from hornet.ingest.factory import (
    MissingCredentialError,
    build_fred_adapter,
    build_worldbank_adapter,
)
from hornet.seeds.loader import (
    load_countries_from_yaml,
    load_source_indicators_from_yaml,
    seed_countries,
    seed_source_indicators,
)

_NOW = datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC)


async def _clean_and_seed() -> None:
    async with session_scope() as session:
        await session.execute(text("DELETE FROM source_indicator"))
        await session.execute(text("DELETE FROM country"))
    country_specs = load_countries_from_yaml()
    indicator_specs = load_source_indicators_from_yaml()
    async with session_scope() as session:
        await seed_countries(session, country_specs, now=_NOW)
        await seed_source_indicators(session, indicator_specs, now=_NOW)


class TestBuildFredAdapter:
    async def test_raises_if_no_api_key(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            with patch("hornet.ingest.factory.get_settings") as mock_settings:
                mock_settings.return_value.fred_api_key = None
                with pytest.raises(MissingCredentialError, match="HORNET_FRED_API_KEY"):
                    await build_fred_adapter(session)

    async def test_builds_with_correct_indicators(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            with patch("hornet.ingest.factory.get_settings") as mock_settings:
                mock_settings.return_value.fred_api_key = type(
                    "FakeSecret", (), {"get_secret_value": lambda self: "test_key"}
                )()
                adapter = await build_fred_adapter(session)
        try:
            manifest = await adapter.discover()
            assert manifest.source_id == "fred"
            assert len(manifest.indicators) == 34  # 39 total - 5 disabled
            all_countries: set[str] = set()
            for spec in manifest.indicators:
                all_countries.update(spec.countries_iso3)
            assert all_countries == {"NGA", "TUR", "ZAF", "BRA", "POL", "USA"}
        finally:
            await adapter.close()


class TestBuildWorldBankAdapter:
    async def test_builds_with_correct_indicators_and_country_map(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            adapter = await build_worldbank_adapter(session)
        try:
            manifest = await adapter.discover()
            assert manifest.source_id == "worldbank"
            assert len(manifest.indicators) == 7
            for spec in manifest.indicators:
                assert spec.countries_iso3 == frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"})
        finally:
            await adapter.close()

    async def test_iso2_map_is_loaded_from_country_table(self) -> None:
        await _clean_and_seed()
        async with session_scope() as session:
            adapter = await build_worldbank_adapter(session)
        try:
            assert adapter._iso2_to_iso3 == {
                "NG": "NGA",
                "TR": "TUR",
                "ZA": "ZAF",
                "BR": "BRA",
                "PL": "POL",
            }
        finally:
            await adapter.close()
