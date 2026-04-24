"""Read-side accessors for scoring over the observations table.

The key query: for a given country, return the latest-vintage
observation for each (indicator_code, source_id, date), filtered to
indicators that participate in scoring (dimension IS NOT NULL).

Global-signal indicators (global_signal=true, e.g. FRED US Treasury
yields) are included when scoring any country — they're stored with
their actual origin country (USA) but apply to all countries.
"""

from __future__ import annotations

import datetime

from sqlalchemy import and_, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ridge.db.models.observation import ObservationRow
from ridge.db.models.source_indicator import SourceIndicatorRow
from ridge.domain.observation import Observation


async def list_observations_for_scoring(
    session: AsyncSession,
    *,
    country_iso3: str,
    start_date: datetime.date | None = None,
) -> list[Observation]:
    """Return latest-vintage observations for a country, ready for scoring.

    Includes:
    - Observations where (source_id, indicator_code) matches a scored
      indicator (dimension IS NOT NULL) that covers this country.
    - Observations from global-signal indicators regardless of country
      (e.g. FRED DGS10 stored with country_iso3='USA').

    For each (indicator_code, source_id, date), only the latest
    vintage is returned (the most recently published value).

    Parameters
    ----------
    country_iso3:
        The country being scored.
    start_date:
        Optional earliest observation date to include. Defaults to
        no filter (all history).
    """
    # Subquery: identify (source_id, indicator_code) pairs that are
    # scored and relevant to this country (either directly or globally).
    scored_indicators = (
        select(
            SourceIndicatorRow.source_id,
            SourceIndicatorRow.indicator_code,
        )
        .where(
            and_(
                SourceIndicatorRow.enabled.is_(True),
                SourceIndicatorRow.dimension.is_not(None),
                or_(
                    # Country-specific indicators
                    SourceIndicatorRow.countries_iso3.any(literal(country_iso3)),
                    # Global indicators apply to all countries
                    SourceIndicatorRow.global_signal.is_(True),
                ),
            )
        )
        .subquery()
    )

    # Main query: observations for this country (or global-signal origin
    # countries like USA) that match scored indicators.
    #
    # We need observations where:
    # - country_iso3 = target country, OR
    # - the indicator is global_signal (observations stored with origin country)
    #
    # To get global observations, we also join on the global_signal flag.
    # Simpler approach: fetch observations for target country + all global
    # indicator observations regardless of country.

    # First, get the set of global (source_id, indicator_code) pairs
    global_indicators = (
        select(
            SourceIndicatorRow.source_id,
            SourceIndicatorRow.indicator_code,
        )
        .where(
            and_(
                SourceIndicatorRow.enabled.is_(True),
                SourceIndicatorRow.global_signal.is_(True),
            )
        )
        .subquery()
    )

    stmt = (
        select(ObservationRow)
        .where(
            or_(
                # Country-specific observations for scored indicators
                and_(
                    ObservationRow.country_iso3 == country_iso3,
                    select(text("1"))
                    .where(
                        and_(
                            scored_indicators.c.source_id == ObservationRow.source_id,
                            scored_indicators.c.indicator_code == ObservationRow.indicator_code,
                        )
                    )
                    .correlate(ObservationRow)
                    .exists(),
                ),
                # Global-signal observations (any country origin)
                select(text("1"))
                .where(
                    and_(
                        global_indicators.c.source_id == ObservationRow.source_id,
                        global_indicators.c.indicator_code == ObservationRow.indicator_code,
                    )
                )
                .correlate(ObservationRow)
                .exists(),
            )
        )
        .order_by(
            ObservationRow.indicator_code,
            ObservationRow.source_id,
            ObservationRow.date,
            ObservationRow.vintage.desc(),
        )
    )

    if start_date is not None:
        stmt = stmt.where(ObservationRow.date >= start_date)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Deduplicate to latest vintage per (indicator_code, source_id, date)
    seen: dict[tuple[str, str, str, datetime.date], ObservationRow] = {}
    for row in rows:
        key = (row.country_iso3, row.indicator_code, row.source_id, row.date)
        existing = seen.get(key)
        if existing is None or row.vintage > existing.vintage:
            seen[key] = row

    return [row.to_domain() for row in seen.values()]
