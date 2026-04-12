"""Read/write accessors for the score_result table."""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.db.models.score_result import ScoreResultRow
from hornet.domain.scoring import ScoreResult


async def upsert_score_results(
    session: AsyncSession,
    results: Sequence[ScoreResult],
) -> int:
    """Persist scoring results, upserting on (country_iso3, scored_at).

    Idempotent: re-running with the same scored_at overwrites the
    previous scores. This is the expected behavior for re-scoring
    after a data update.

    Returns the number of rows upserted.
    """
    if not results:
        return 0

    values = [
        {
            "country_iso3": r.country_iso3,
            "run_id": r.run_id,
            "scored_at": r.scored_at,
            "dimensions": {name: ds.model_dump() for name, ds in r.dimensions.items()},
            "composite": r.composite,
            "news_heat": r.news_heat.model_dump() if r.news_heat else None,
            "coverage_fraction": r.coverage_fraction,
        }
        for r in results
    ]

    stmt = pg_insert(ScoreResultRow).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["country_iso3", "scored_at"],
        set_={
            "run_id": stmt.excluded.run_id,
            "dimensions": stmt.excluded.dimensions,
            "composite": stmt.excluded.composite,
            "news_heat": stmt.excluded.news_heat,
            "coverage_fraction": stmt.excluded.coverage_fraction,
        },
    )
    await session.execute(stmt)
    return len(values)


async def list_score_results(
    session: AsyncSession,
    *,
    country_iso3: str | None = None,
    run_id: str | None = None,
    since: datetime.datetime | None = None,
    limit: int = 100,
) -> list[ScoreResult]:
    """Query score results with optional filters.

    Parameters
    ----------
    country_iso3:
        Filter to one country.
    run_id:
        Filter to one scoring run.
    since:
        Only results scored after this timestamp.
    limit:
        Maximum rows to return.
    """
    stmt = select(ScoreResultRow).order_by(ScoreResultRow.scored_at.desc()).limit(limit)
    if country_iso3 is not None:
        stmt = stmt.where(ScoreResultRow.country_iso3 == country_iso3)
    if run_id is not None:
        stmt = stmt.where(ScoreResultRow.run_id == run_id)
    if since is not None:
        stmt = stmt.where(ScoreResultRow.scored_at >= since)

    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]
