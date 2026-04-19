"""Ingest runner — fetches from a SourceAdapter and writes to Postgres.

Keeps the adapter layer (which only knows how to produce canonical
Observations) separate from the storage layer (which only knows how
to persist them). This module is the hinge between them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.dialects.postgresql import insert as pg_insert

from hornet.adapters import SourceAdapter
from hornet.db.models import EventRecordRow, ObservationRow
from hornet.db.session import session_scope
from hornet.domain import FetchRequest
from hornet.domain.event import EventRecord


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
    #
    # Postgres has a parameter limit of ~32,767. Each observation has
    # 9 columns, so we chunk at 3,000 rows (27,000 params) to stay
    # safely under the limit. yfinance can return 10,000+ observations
    # in one fetch -- without chunking, the INSERT fails.
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

    _CHUNK_SIZE = 3000
    written = 0

    async with session_scope() as session:
        for i in range(0, len(values), _CHUNK_SIZE):
            chunk = values[i : i + _CHUNK_SIZE]
            stmt = (
                pg_insert(ObservationRow)
                .values(chunk)
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
            result = await session.execute(stmt)
            written += len(result.all())

    return IngestResult(
        source_id=request.source_id,
        observations_fetched=len(observations),
        observations_written=written,
    )


class EventIngestResult(BaseModel):
    """Summary of an event ingest invocation."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    events_received: int
    events_written: int


async def run_event_ingest(
    source_id: str,
    events: list[EventRecord],
) -> EventIngestResult:
    """Persist a list of EventRecord objects idempotently.

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` against the composite
    primary key ``(date, dedup_key)`` so running the same events twice
    is safe -- duplicates are skipped.
    """
    if not events:
        return EventIngestResult(
            source_id=source_id,
            events_received=0,
            events_written=0,
        )

    values = [
        {
            "date": event.date,
            "dedup_key": event.dedup_key,
            "country_iso3": event.country_iso3,
            "source_id": event.source_id,
            "event_type": event.event_type,
            "value": event.value,
            "title": event.title,
            "url": event.url,
            "metadata_": event.metadata,
            "ingested_at": event.ingested_at,
        }
        for event in events
    ]

    _CHUNK_SIZE = 3000
    written = 0

    async with session_scope() as session:
        for i in range(0, len(values), _CHUNK_SIZE):
            chunk = values[i : i + _CHUNK_SIZE]
            stmt = (
                pg_insert(EventRecordRow)
                .values(chunk)
                .on_conflict_do_nothing(
                    index_elements=["date", "dedup_key"],
                )
                .returning(EventRecordRow.dedup_key)
            )
            result = await session.execute(stmt)
            written += len(result.all())

    return EventIngestResult(
        source_id=source_id,
        events_received=len(events),
        events_written=written,
    )
