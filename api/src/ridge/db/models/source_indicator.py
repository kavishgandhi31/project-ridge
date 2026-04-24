"""SourceIndicatorRow — SQLAlchemy storage mirror of SourceIndicatorSpec.

The ``source_indicator`` table is the registry of every
(source_id, source_native_code) -> canonical indicator_code mapping.
Replaces the hardcoded ``_PILOT_SERIES`` / ``_INDICATORS`` dicts that
Phase 1 shipped in the FRED and WorldBank adapters. Every Phase 2
adapter loads its series list from this table at startup; nothing
about which indicators a source exposes lives in code any more.

Follows the same domain/ORM separation pattern as ``ObservationRow``
and ``CountryRow``: ``from_domain()`` / ``to_domain()`` are the only
sanctioned conversion points.
"""

from __future__ import annotations

import datetime
from typing import cast

from sqlalchemy import (
    ARRAY,
    Boolean,
    Index,
    PrimaryKeyConstraint,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from ridge.db.base import Base
from ridge.domain.observation import Frequency
from ridge.domain.source import SourceIndicatorSpec


class SourceIndicatorRow(Base):
    """SQLAlchemy ORM row for the ``source_indicator`` table.

    Composite primary key ``(source_id, source_native_code)`` — a
    source's native identifier is unique within that source, and both
    are needed to resolve a row unambiguously across the whole table.

    Two partial indexes on ``enabled = true`` accelerate the two most
    common queries: "list all live series for this source" (used by
    adapter construction at startup) and "find everything mapped to
    this canonical indicator" (used by cross-source validation in
    Phase 4 and by the API).
    """

    __tablename__ = "source_indicator"

    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_native_code: Mapped[str] = mapped_column(Text, nullable=False)
    indicator_code: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    countries_iso3: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dimension: Mapped[str | None] = mapped_column(Text, nullable=True)
    concept: Mapped[str | None] = mapped_column(Text, nullable=True)
    global_signal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "source_id",
            "source_native_code",
            name="source_indicator_pk",
        ),
        Index(
            "source_indicator_source_enabled_idx",
            "source_id",
            postgresql_where=text("enabled"),
        ),
        Index(
            "source_indicator_indicator_enabled_idx",
            "indicator_code",
            postgresql_where=text("enabled"),
        ),
    )

    @classmethod
    def from_domain(
        cls,
        spec: SourceIndicatorSpec,
        *,
        created_at: datetime.datetime,
        updated_at: datetime.datetime,
    ) -> SourceIndicatorRow:
        """Construct a storage row from a canonical domain SourceIndicatorSpec.

        ``created_at`` / ``updated_at`` are storage concerns, not part
        of the domain type, and must be supplied by the caller.
        """
        return cls(
            source_id=spec.source_id,
            source_native_code=spec.source_native_code,
            indicator_code=spec.indicator_code,
            frequency=spec.frequency,
            countries_iso3=sorted(spec.countries_iso3),
            name=spec.name,
            unit=spec.unit,
            enabled=spec.enabled,
            dimension=spec.dimension,
            concept=spec.concept,
            global_signal=spec.global_signal,
            notes=spec.notes,
            created_at=created_at,
            updated_at=updated_at,
        )

    def to_domain(self) -> SourceIndicatorSpec:
        """Convert this storage row back to a canonical SourceIndicatorSpec."""
        return SourceIndicatorSpec(
            source_id=self.source_id,
            source_native_code=self.source_native_code,
            indicator_code=self.indicator_code,
            frequency=cast(Frequency, self.frequency),
            countries_iso3=frozenset(self.countries_iso3),
            name=self.name,
            unit=self.unit,
            enabled=self.enabled,
            dimension=self.dimension,
            concept=self.concept,
            global_signal=self.global_signal,
            notes=self.notes,
        )
