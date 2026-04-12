"""EventRecordRow -- SQLAlchemy storage mirror of the domain EventRecord.

The ``event_record`` table is a TimescaleDB hypertable partitioned on
``date``, parallel to the ``observations`` hypertable. It stores
news/sentiment data from GDELT and GoogleNews that does not fit the
numeric Observation model.

Follows the same domain/ORM separation pattern: ``from_domain()`` /
``to_domain()`` are the only sanctioned conversion points.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    Date,
    Double,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from hornet.db.base import Base
from hornet.domain.event import EventRecord


class EventRecordRow(Base):
    """SQLAlchemy ORM row for the ``event_record`` hypertable.

    Composite primary key ``(date, dedup_key)`` -- ``date`` must be
    in the PK because TimescaleDB requires the partitioning column
    in all unique constraints. ``dedup_key`` is a computed string
    the adapter builds from the event's natural identity, ensuring
    idempotent inserts via ``ON CONFLICT DO NOTHING``.
    """

    __tablename__ = "event_record"

    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    country_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Double, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    ingested_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        PrimaryKeyConstraint("date", "dedup_key", name="event_record_pk"),
        Index(
            "event_record_country_type_date_idx",
            "country_iso3",
            "event_type",
            "date",
        ),
        Index(
            "event_record_source_date_idx",
            "source_id",
            "date",
        ),
    )

    @classmethod
    def from_domain(cls, event: EventRecord) -> EventRecordRow:
        """Construct a storage row from a canonical domain EventRecord."""
        return cls(
            date=event.date,
            dedup_key=event.dedup_key,
            country_iso3=event.country_iso3,
            source_id=event.source_id,
            event_type=event.event_type,
            value=event.value,
            title=event.title,
            url=event.url,
            metadata_=event.metadata,
            ingested_at=event.ingested_at,
        )

    def to_domain(self) -> EventRecord:
        """Convert this storage row back to a canonical domain EventRecord."""
        return EventRecord(
            country_iso3=self.country_iso3,
            source_id=self.source_id,
            event_type=self.event_type,
            date=self.date,
            dedup_key=self.dedup_key,
            value=self.value,
            title=self.title,
            url=self.url,
            metadata=self.metadata_,
            ingested_at=self.ingested_at,
        )
