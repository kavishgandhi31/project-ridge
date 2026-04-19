"""CountryRow — SQLAlchemy storage mirror of the domain CountrySpec.

The ``country`` table is the authoritative registry of every country
Hornet tracks. Keeping country identity in the database (rather than a
YAML file or a hardcoded dict) is what lets other layers join against
it: WorldBank ISO2 lookups, Phase 3 regional scoring, Phase 6 LLM
country narratives.

Follows the same domain/ORM separation as ``ObservationRow``:
``from_domain()`` / ``to_domain()`` are the only permitted conversion
points. Nothing else should ever touch the ORM instance directly.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from hornet.db.base import Base
from hornet.domain.source import CountrySpec


class CountryRow(Base):
    """SQLAlchemy ORM row for the ``country`` table.

    Primary key is ``iso3`` — that's the canonical identity used
    everywhere else (``observations.country_iso3``, scoring joins,
    API responses). ``iso2`` is kept as a unique secondary column so
    the WorldBank adapter can resolve its native ISO2 codes without
    embedding a hardcoded map in the adapter.
    """

    __tablename__ = "country"

    iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    iso2: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    income_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    @classmethod
    def from_domain(
        cls,
        spec: CountrySpec,
        *,
        created_at: datetime.datetime,
        updated_at: datetime.datetime,
    ) -> CountryRow:
        """Construct a storage row from a canonical domain CountrySpec.

        ``created_at`` / ``updated_at`` are not part of the domain type —
        they are storage concerns and must be supplied by the caller
        (typically the seed loader, which passes ``datetime.now(UTC)``).
        """
        return cls(
            iso3=spec.iso3,
            iso2=spec.iso2,
            name=spec.name,
            region=spec.region,
            income_group=spec.income_group,
            enabled=spec.enabled,
            notes=spec.notes,
            created_at=created_at,
            updated_at=updated_at,
        )

    def to_domain(self) -> CountrySpec:
        """Convert this storage row back to a canonical domain CountrySpec."""
        return CountrySpec(
            iso3=self.iso3,
            iso2=self.iso2,
            name=self.name,
            region=self.region,
            income_group=self.income_group,
            enabled=self.enabled,
            notes=self.notes,
        )
