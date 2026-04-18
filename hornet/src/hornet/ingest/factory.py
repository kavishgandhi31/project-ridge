"""Composition functions that build DB-backed adapters.

The adapter classes themselves are pure — they take pre-loaded
indicator lists and (for WB) ISO2->ISO3 maps in their constructors.
This module is where the DB reads happen to produce those arguments.

Split out of the ingest runner so that tests of the adapters can
construct them with literal fixtures and skip all of this — and so
tests of the factory can mock only the repo layer without pulling in
adapter parsing logic.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.adapters.bis import BISAdapter
from hornet.adapters.fred import FredAdapter
from hornet.adapters.gdelt import GDELTAdapter
from hornet.adapters.googlenews import GoogleNewsAdapter
from hornet.adapters.imf import IMFAdapter
from hornet.adapters.oecd import OECDAdapter
from hornet.adapters.worldbank import WorldBankAdapter
from hornet.adapters.yfinance_adapter import YFinanceAdapter
from hornet.config import get_settings
from hornet.db.repos.country import list_countries, load_iso2_to_iso3_map
from hornet.db.repos.source_indicator import list_source_indicators

logger = structlog.get_logger(__name__)


class MissingCredentialError(RuntimeError):
    """Raised when a factory cannot find a credential it needs in Settings."""


async def build_fred_adapter(session: AsyncSession) -> FredAdapter:
    """Construct a FredAdapter wired up against the DB registry.

    Reads:
    * ``source_indicator`` rows where ``source_id = 'fred'`` from the
      registry, via the repo layer.
    * ``HORNET_FRED_API_KEY`` from Settings.

    Raises:
        MissingCredentialError: if ``HORNET_FRED_API_KEY`` is unset.

    Tests that exercise the adapter directly should bypass this
    factory and construct ``FredAdapter(api_key=..., indicators=...)``
    themselves with literal fixtures.
    """
    settings = get_settings()
    if settings.fred_api_key is None:
        raise MissingCredentialError(
            "HORNET_FRED_API_KEY is not set; FredAdapter cannot be constructed "
            "against a live FRED API. Set the env var or build the adapter "
            "directly with a literal key for tests."
        )

    indicators = await list_source_indicators(session, source_id=FredAdapter.source_id)
    logger.info(
        "factory.fred.built",
        indicator_count=len(indicators),
    )
    return FredAdapter(
        api_key=settings.fred_api_key.get_secret_value(),
        indicators=indicators,
    )


async def build_worldbank_adapter(session: AsyncSession) -> WorldBankAdapter:
    """Construct a WorldBankAdapter wired up against the DB registry.

    Reads:
    * ``source_indicator`` rows where ``source_id = 'worldbank'``.
    * The ISO2 -> ISO3 map from the ``country`` table.

    WorldBank has no credentials (public API), so no secret lookups.
    """
    indicators = await list_source_indicators(session, source_id=WorldBankAdapter.source_id)
    iso2_to_iso3 = await load_iso2_to_iso3_map(session)
    logger.info(
        "factory.worldbank.built",
        indicator_count=len(indicators),
        country_count=len(iso2_to_iso3),
    )
    return WorldBankAdapter(
        indicators=indicators,
        iso2_to_iso3=iso2_to_iso3,
    )


async def build_yfinance_adapter(session: AsyncSession) -> YFinanceAdapter:
    """Construct a YFinanceAdapter wired up against the DB registry.

    Reads ``source_indicator`` rows where ``source_id = 'yfinance'``.
    yfinance has no credentials (public library wrapping Yahoo Finance).
    """
    indicators = await list_source_indicators(session, source_id=YFinanceAdapter.source_id)
    logger.info(
        "factory.yfinance.built",
        indicator_count=len(indicators),
    )
    return YFinanceAdapter(indicators=indicators)


async def build_oecd_adapter(session: AsyncSession) -> OECDAdapter:
    """Construct an OECDAdapter wired up against the DB registry.

    Reads ``source_indicator`` rows where ``source_id = 'oecd'``.
    OECD has no credentials (public SDMX API).
    """
    indicators = await list_source_indicators(session, source_id=OECDAdapter.source_id)
    logger.info(
        "factory.oecd.built",
        indicator_count=len(indicators),
    )
    return OECDAdapter(indicators=indicators)


async def build_bis_adapter(session: AsyncSession) -> BISAdapter:
    """Construct a BISAdapter wired up against the DB registry.

    Reads:
    * ``source_indicator`` rows where ``source_id = 'bis'``.
    * The ISO3 -> ISO2 map (reversed from the ``country`` table's
      ISO2 -> ISO3 map) because BIS uses ISO2 in its API.

    BIS has no credentials (public SDMX API).
    """
    indicators = await list_source_indicators(session, source_id=BISAdapter.source_id)
    iso2_to_iso3 = await load_iso2_to_iso3_map(session)
    iso3_to_iso2 = {iso3: iso2 for iso2, iso3 in iso2_to_iso3.items()}
    logger.info(
        "factory.bis.built",
        indicator_count=len(indicators),
        country_count=len(iso3_to_iso2),
    )
    return BISAdapter(
        indicators=indicators,
        iso3_to_iso2=iso3_to_iso2,
    )


async def build_imf_adapter(session: AsyncSession) -> IMFAdapter:
    """Construct an IMFAdapter wired up against the DB registry.

    Reads ``source_indicator`` rows where ``source_id = 'imf'``.
    IMF has no credentials (all three sub-APIs are public).
    """
    indicators = await list_source_indicators(session, source_id=IMFAdapter.source_id)
    logger.info(
        "factory.imf.built",
        indicator_count=len(indicators),
    )
    return IMFAdapter(indicators=indicators)


async def build_gdelt_adapter(session: AsyncSession) -> GDELTAdapter:
    """Construct a GDELTAdapter wired up against the DB registry.

    Reads:
    * ``source_indicator`` rows where ``source_id = 'gdelt'``.
    * Country names and ISO2 codes from the ``country`` table for
      GDELT query building (GDELT searches by country name, not code).

    GDELT has no credentials (free public API).
    """
    indicators = await list_source_indicators(session, source_id=GDELTAdapter.source_id)
    countries = await list_countries(session)
    country_names = {c.iso3: c.name for c in countries}
    country_iso2s = {c.iso3: c.iso2 for c in countries}
    logger.info(
        "factory.gdelt.built",
        indicator_count=len(indicators),
        country_count=len(country_names),
    )
    return GDELTAdapter(
        indicators=indicators,
        country_names=country_names,
        country_iso2s=country_iso2s,
    )


async def build_googlenews_adapter(session: AsyncSession) -> GoogleNewsAdapter:
    """Construct a GoogleNewsAdapter wired up against the DB registry.

    Reads:
    * ``source_indicator`` rows where ``source_id = 'googlenews'``.
    * Country names from the ``country`` table for query building.

    Google News RSS is free, no credentials.
    """
    indicators = await list_source_indicators(session, source_id=GoogleNewsAdapter.source_id)
    countries = await list_countries(session)
    country_names = {c.iso3: c.name for c in countries}
    logger.info(
        "factory.googlenews.built",
        indicator_count=len(indicators),
        country_count=len(country_names),
    )
    return GoogleNewsAdapter(
        indicators=indicators,
        country_names=country_names,
    )
