"""Read-side accessors over the ``country`` registry table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.db.models.country import CountryRow
from hornet.domain.source import CountrySpec


async def list_countries(
    session: AsyncSession,
    *,
    enabled_only: bool = True,
) -> list[CountrySpec]:
    """Return all registered countries as domain ``CountrySpec`` objects.

    ``enabled_only`` defaults to True because every normal code path
    wants live countries only. Tests or operator tooling can pass False
    to include disabled rows.
    """
    stmt = select(CountryRow).order_by(CountryRow.iso3)
    if enabled_only:
        stmt = stmt.where(CountryRow.enabled.is_(True))
    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]


async def load_iso2_to_iso3_map(
    session: AsyncSession,
    *,
    enabled_only: bool = True,
) -> dict[str, str]:
    """Return the ISO2 -> ISO3 mapping the WorldBank adapter needs.

    WorldBank responses identify countries by ISO2; Hornet's canonical
    country_iso3 column is ISO3. This is the one query the WB adapter
    runs at construction time to build its translation map. Pre-loading
    it (rather than querying per response) keeps the adapter pure and
    ensures a single DB read regardless of how many records get parsed.
    """
    stmt = select(CountryRow.iso2, CountryRow.iso3)
    if enabled_only:
        stmt = stmt.where(CountryRow.enabled.is_(True))
    result = await session.execute(stmt)
    return {iso2: iso3 for iso2, iso3 in result.all()}
