"""Read-side accessors for scoring over the observations table.

The key query: for a given country, return the latest-vintage
observation for each (indicator_code, source_id, date), filtered to
indicators that participate in scoring (dimension IS NOT NULL).

Global-signal indicators (global_signal=true, e.g. FRED US Treasury
yields) are included when scoring any country -- they're stored with
their actual origin country (USA) but apply to all countries.
"""

from __future__ import annotations

import datetime

from sqlalchemy import and_, literal, or_, select
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

    For each (country, indicator_code, source_id, date), only the
    latest vintage is returned.
    """
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
                    SourceIndicatorRow.countries_iso3.any(literal(country_iso3)),
                    SourceIndicatorRow.global_signal.is_(True),
                ),
            )
        )
        .subquery()
    )

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

    country_match = and_(
        ObservationRow.country_iso3 == country_iso3,
        select(literal(1))
        .where(
            and_(
                scored_indicators.c.source_id == ObservationRow.source_id,
                scored_indicators.c.indicator_code == ObservationRow.indicator_code,
            )
        )
        .correlate(ObservationRow)
        .exists(),
    )
    global_match = (
        select(literal(1))
        .where(
            and_(
                global_indicators.c.source_id == ObservationRow.source_id,
                global_indicators.c.indicator_code == ObservationRow.indicator_code,
            )
        )
        .correlate(ObservationRow)
        .exists()
    )

    stmt = (
        select(ObservationRow)
        .where(or_(country_match, global_match))
        .distinct(
            ObservationRow.country_iso3,
            ObservationRow.indicator_code,
            ObservationRow.source_id,
            ObservationRow.date,
        )
        .order_by(
            ObservationRow.country_iso3,
            ObservationRow.indicator_code,
            ObservationRow.source_id,
            ObservationRow.date,
            ObservationRow.vintage.desc(),
        )
    )

    if start_date is not None:
        stmt = stmt.where(ObservationRow.date >= start_date)

    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]


async def list_all_observations_for_quality(
    session: AsyncSession,
    *,
    start_date: datetime.date | None = None,
) -> list[Observation]:
    """Return latest-vintage observations across all countries for scored indicators.

    Used by the quality stage to run observation-based checks (outlier,
    flatline, structural break, cross-source divergence, revision,
    date consistency, source staleness, series audit) over the full
    dataset in a single bulk query. Called once per pipeline run,
    freed before the score stage starts.

    Same filtering semantics as ``list_observations_for_scoring`` but
    with no country filter and no global-signal expansion (each obs
    appears exactly once at its recorded country_iso3).
    """
    scored_indicators = (
        select(
            SourceIndicatorRow.source_id,
            SourceIndicatorRow.indicator_code,
        )
        .where(
            and_(
                SourceIndicatorRow.enabled.is_(True),
                SourceIndicatorRow.dimension.is_not(None),
            )
        )
        .subquery()
    )

    stmt = (
        select(ObservationRow)
        .where(
            select(literal(1))
            .where(
                and_(
                    scored_indicators.c.source_id == ObservationRow.source_id,
                    scored_indicators.c.indicator_code == ObservationRow.indicator_code,
                )
            )
            .correlate(ObservationRow)
            .exists()
        )
        .distinct(
            ObservationRow.country_iso3,
            ObservationRow.indicator_code,
            ObservationRow.source_id,
            ObservationRow.date,
        )
        .order_by(
            ObservationRow.country_iso3,
            ObservationRow.indicator_code,
            ObservationRow.source_id,
            ObservationRow.date,
            ObservationRow.vintage.desc(),
        )
    )

    if start_date is not None:
        stmt = stmt.where(ObservationRow.date >= start_date)

    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]
