"""Read/write accessors for the alert_record table."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.db.models.alert_record import AlertRecordRow
from hornet.domain.alerting import TierAssignment


async def upsert_alert_records(
    session: AsyncSession,
    assignments: Sequence[TierAssignment],
) -> int:
    """Persist tier assignments, upserting on (country_iso3, run_id).

    Returns the number of rows upserted.
    """
    if not assignments:
        return 0

    values = [
        {
            "country_iso3": a.country_iso3,
            "run_id": a.run_id,
            "evaluated_at": a.evaluated_at,
            "composite": a.composite,
            "coverage_fraction": a.coverage_fraction,
            "raw_tier": a.raw_tier.value if a.raw_tier else None,
            "effective_tier": a.effective_tier.value if a.effective_tier else None,
            "streak_length": a.streak_length,
            "velocity": a.velocity,
            "modifiers_applied": list(a.modifiers_applied),
        }
        for a in assignments
    ]

    stmt = pg_insert(AlertRecordRow).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="alert_record_pk",
        set_={
            "evaluated_at": stmt.excluded.evaluated_at,
            "composite": stmt.excluded.composite,
            "coverage_fraction": stmt.excluded.coverage_fraction,
            "raw_tier": stmt.excluded.raw_tier,
            "effective_tier": stmt.excluded.effective_tier,
            "streak_length": stmt.excluded.streak_length,
            "velocity": stmt.excluded.velocity,
            "modifiers_applied": stmt.excluded.modifiers_applied,
        },
    )
    await session.execute(stmt)
    return len(values)


async def list_prior_records(
    session: AsyncSession,
    country_iso3: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch the most recent alert records for a country.

    Returns dicts ordered most-recent-first, suitable for passing
    directly to ``assign_tier`` as ``prior_records``.

    Parameters
    ----------
    country_iso3:
        The country to query.
    limit:
        Maximum records to return. Default 10 is more than enough
        for streak counting (which only needs streak_required + 1).
    """
    stmt = (
        select(AlertRecordRow)
        .where(AlertRecordRow.country_iso3 == country_iso3)
        .order_by(AlertRecordRow.evaluated_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [row.to_domain_dict() for row in result.scalars().all()]


async def list_alert_records(
    session: AsyncSession,
    *,
    country_iso3: str | None = None,
    run_id: str | None = None,
    effective_tier: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query alert records with optional filters.

    Returns dicts suitable for API serialization.
    """
    stmt = select(AlertRecordRow).order_by(AlertRecordRow.evaluated_at.desc())

    if country_iso3 is not None:
        stmt = stmt.where(AlertRecordRow.country_iso3 == country_iso3)
    if run_id is not None:
        stmt = stmt.where(AlertRecordRow.run_id == run_id)
    if effective_tier is not None:
        stmt = stmt.where(AlertRecordRow.effective_tier == effective_tier)

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return [row.to_domain_dict() for row in result.scalars().all()]
