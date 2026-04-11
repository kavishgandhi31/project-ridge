"""ObservationRow — the SQLAlchemy storage mirror of the domain Observation.

The domain ``Observation`` (Pydantic) is what business logic passes
around. The ``ObservationRow`` (SQLAlchemy) is what the database holds.
They mirror each other but are intentionally separate types so that
schema evolution and domain evolution can move at different speeds.
Use ``from_domain()`` and ``to_domain()`` to convert between them —
nothing else should ever touch the ORM instance directly.
"""

from __future__ import annotations

import datetime
from typing import cast

from sqlalchemy import (
    ARRAY,
    Date,
    Double,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from hornet.db.base import Base
from hornet.domain.observation import Frequency, Observation


class ObservationRow(Base):
    """SQLAlchemy ORM row for the ``observations`` hypertable.

    The table is a TimescaleDB hypertable partitioned on ``date``.
    Hypertable creation is done in the first Alembic migration, not
    here — SQLAlchemy's declarative metadata doesn't know about the
    Timescale-specific ``create_hypertable()`` DDL, so that lives in
    the migration file.

    Composite primary key ``(country_iso3, indicator_code, source_id,
    date, vintage)`` — ``vintage`` is part of the PK because source
    revisions append a new row rather than mutating the old one.
    """

    __tablename__ = "observations"

    country_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    indicator_code: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    vintage: Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ingested_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    __table_args__ = (
        PrimaryKeyConstraint(
            "country_iso3",
            "indicator_code",
            "source_id",
            "date",
            "vintage",
            name="observations_pk",
        ),
        Index(
            "observations_country_indicator_date_idx",
            "country_iso3",
            "indicator_code",
            "date",
        ),
    )

    @classmethod
    def from_domain(cls, obs: Observation) -> ObservationRow:
        """Construct a storage row from a canonical domain Observation."""
        return cls(
            country_iso3=obs.country_iso3,
            indicator_code=obs.indicator_code,
            source_id=obs.source_id,
            date=obs.date,
            value=obs.value,
            frequency=obs.frequency,
            vintage=obs.vintage,
            ingested_at=obs.ingested_at,
            quality_flags=list(obs.quality_flags),
        )

    def to_domain(self) -> Observation:
        """Convert this storage row back to a canonical domain Observation."""
        return Observation(
            country_iso3=self.country_iso3,
            indicator_code=self.indicator_code,
            source_id=self.source_id,
            date=self.date,
            value=self.value,
            frequency=cast(Frequency, self.frequency),
            vintage=self.vintage,
            ingested_at=self.ingested_at,
            quality_flags=tuple(self.quality_flags),
        )
