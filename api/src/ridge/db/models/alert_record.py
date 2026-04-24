"""AlertRecordRow -- SQLAlchemy storage mirror of TierAssignment.

The ``alert_record`` table persists tier assignments per country
per pipeline run. This enables:
    - Streak queries: "last N runs for country X at ALERT+"
    - Velocity computation: "composite delta from prior run"
    - Audit trail: "what tier was assigned and why"

Regular table (not hypertable) -- volume is ~183 rows/day.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Double,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from ridge.db.base import Base
from ridge.domain.alerting import TierAssignment


class AlertRecordRow(Base):
    """SQLAlchemy ORM row for the ``alert_record`` table."""

    __tablename__ = "alert_record"

    country_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    composite: Mapped[float | None] = mapped_column(Double, nullable=True)
    coverage_fraction: Mapped[float] = mapped_column(Double, nullable=False)
    raw_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    streak_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    velocity: Mapped[float | None] = mapped_column(Double, nullable=True)
    modifiers_applied: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "country_iso3",
            "run_id",
            name="alert_record_pk",
        ),
        Index("alert_record_run_idx", "run_id"),
        Index(
            "alert_record_country_eval_idx",
            "country_iso3",
            evaluated_at.desc(),
        ),
    )

    @classmethod
    def from_domain(cls, assignment: TierAssignment) -> AlertRecordRow:
        """Construct a storage row from a TierAssignment domain object."""
        return cls(
            country_iso3=assignment.country_iso3,
            run_id=assignment.run_id,
            evaluated_at=assignment.evaluated_at,
            composite=assignment.composite,
            coverage_fraction=assignment.coverage_fraction,
            raw_tier=assignment.raw_tier.value if assignment.raw_tier else None,
            effective_tier=assignment.effective_tier.value if assignment.effective_tier else None,
            streak_length=assignment.streak_length,
            velocity=assignment.velocity,
            modifiers_applied=list(assignment.modifiers_applied),
        )

    def to_domain_dict(self) -> dict[str, object]:
        """Convert to a dict suitable for streak/velocity queries.

        Returns a plain dict (not a TierAssignment) because the tier
        evaluator needs ``effective_tier`` and ``composite`` for
        streak counting and velocity computation, but does not need
        country_name or region (which are not stored in this table).
        """
        return {
            "country_iso3": self.country_iso3,
            "run_id": self.run_id,
            "evaluated_at": self.evaluated_at,
            "composite": self.composite,
            "coverage_fraction": self.coverage_fraction,
            "raw_tier": self.raw_tier,
            "effective_tier": self.effective_tier,
            "streak_length": self.streak_length,
            "velocity": self.velocity,
            "modifiers_applied": list(self.modifiers_applied),
        }
