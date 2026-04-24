"""Read-side accessors for scoring over the event_record table.

The scoring engine needs GDELT tone and volume EventRecords. Headline
events are not used for scoring (they're display-only for the digest
and LLM layer).
"""

from __future__ import annotations

import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ridge.db.models.event_record import EventRecordRow
from ridge.domain.event import EventRecord


async def list_events_for_scoring(
    session: AsyncSession,
    *,
    country_iso3: str,
    event_types: tuple[str, ...] = ("tone", "volume"),
    start_date: datetime.date | None = None,
) -> list[EventRecord]:
    """Return EventRecords for a country, filtered to scoring-relevant types.

    Parameters
    ----------
    country_iso3:
        The country being scored.
    event_types:
        Event types to include. Defaults to tone + volume (used by
        risk_sentiment and news_heat).
    start_date:
        Optional earliest event date. Defaults to no filter.
    """
    stmt = (
        select(EventRecordRow)
        .where(
            and_(
                EventRecordRow.country_iso3 == country_iso3,
                EventRecordRow.event_type.in_(event_types),
            )
        )
        .order_by(EventRecordRow.date)
    )

    if start_date is not None:
        stmt = stmt.where(EventRecordRow.date >= start_date)

    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]
