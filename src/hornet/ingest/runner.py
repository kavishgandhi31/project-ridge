"""Ingest runner — fetches from a SourceAdapter and writes to Postgres.

Keeps the adapter layer (which only knows how to produce canonical
Observations) separate from the storage layer (which only knows how
to persist them). This module is the hinge between them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.dialects.postgresql import insert as pg_insert

from hornet.adapters import SourceAdapter
from hornet.db.models import ObservationRow
from hornet.db.session import session_scope
from hornet.domain import FetchRequest


class IngestResult(BaseModel):
    """Summary of a single ingest invocation.

    ``observations_fetched`` is how many the adapter produced.
    ``observations_written`` is how many Postgres actually accepted —
    the delta is duplicates skipped by the ``ON CONFLICT DO NOTHING``
    clause, which is how idempotent re-runs work.
    """

    model_config = ConfigDict(frozen=True)

    source_id: str
    observations_fetched: int
    observations_written: int


async def run_ingest(
    adapter: SourceAdapter,
    request: FetchRequest,
) -> IngestResult:
    """Fetch observations from ``adapter`` and persist them idempotently.

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` against the composite
    primary key ``(country_iso3, indicator_code, source_id, date,
    vintage)`` so running the same request twice is safe — duplicates
    are skipped, not raised. A source revision (same series, later
    vintage) is treated as a *new* row, not a conflict, because
    ``vintage`` is part of the PK. This is how append-only revision
    tracking works without any application-level logic.

    Returns an ``IngestResult`` summarizing the fetch/write counts.
    The delta between them is the de-duplication count on this run.
    """
    observations = await adapter.fetch(request)

    if not observations:
        return IngestResult(
            source_id=request.source_id,
            observations_fetched=0,
            observations_written=0,
        )

    # Convert to value dicts for bulk insert. We deliberately use a raw
    # INSERT ... ON CONFLICT DO NOTHING rather than session.add_all()
    # so that re-runs skip existing rows silently. session.add_all()
    # would try to INSERT every row and raise IntegrityError on the
    # first primary-key collision.
    values = [
        {
            "country_iso3": obs.country_iso3,
            "indicator_code": obs.indicator_code,
            "source_id": obs.source_id,
            "date": obs.date,
            "value": obs.value,
            "frequency": obs.frequency,
            "vintage": obs.vintage,
            "ingested_at": obs.ingested_at,
            "quality_flags": list(obs.quality_flags),
        }
        for obs in observations
    ]

    stmt = (
        pg_insert(ObservationRow)
        .values(values)
        .on_conflict_do_nothing(
            index_elements=[
                "country_iso3",
                "indicator_code",
                "source_id",
                "date",
                "vintage",
            ],
        )
        .returning(ObservationRow.country_iso3)
    )

    # INSERT ... ON CONFLICT DO NOTHING RETURNING <col> returns exactly
    # the rows that were inserted — skipped rows are absent from the
    # result set. Counting the returned rows gives us the write count
    # directly, avoiding the driver-dependent `rowcount` attribute which
    # can return -1 when the driver doesn't know the definitive count.
    async with session_scope() as session:
        result = await session.execute(stmt)
        written = len(result.all())

    return IngestResult(
        source_id=request.source_id,
        observations_fetched=len(observations),
        observations_written=written,
    )
