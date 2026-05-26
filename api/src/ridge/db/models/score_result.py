"""ScoreResultRow -- SQLAlchemy storage mirror of the domain ScoreResult.

The ``score_result`` table is a TimescaleDB hypertable partitioned on
``scored_at``. Each row represents one country's complete scoring
output (all dimensions + composite) for one scoring run. The
``run_id`` groups all countries from the same batch.

Dimensions and news_heat are stored as JSONB because:
- The number of dimensions may evolve
- Each dimension carries metadata (n_series_used, etc.)
- The API layer returns this as nested JSON anyway
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    Double,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from ridge.db.base import Base
from ridge.domain.scoring import DimensionScore, NewsHeat, ScoreResult


class ScoreResultRow(Base):
    """SQLAlchemy ORM row for the ``score_result`` hypertable.

    Composite PK ``(country_iso3, scored_at)`` — TimescaleDB requires
    the partitioning column in all unique constraints.

    JSONB schema contract:

    ``dimensions`` is a mapping of dimension name to serialized
    ``DimensionScore``. ``DimensionScore`` is a Pydantic model, and
    ``from_domain`` writes its ``model_dump()``. If a field is added,
    renamed, or removed on ``DimensionScore``, historic rows will
    silently fail ``to_domain()`` -- the historic-row test in
    ``tests/test_score_result_db_models.py`` pins the current shape
    so the breakage is caught at PR time, not in production::

        {
          "<dimension_name>": {
            "dimension":      str,           # e.g. "growth_momentum"
            "value":          float | None,  # clamped score or None
            "n_series_used":  int,
            "n_series_stale": int,
            "n_concepts":     int,
          },
          ...
        }

    ``news_heat`` is either NULL or a serialized ``NewsHeat``::

        {"sigma": float, "volume_ratio": float}
    """

    __tablename__ = "score_result"

    country_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    scored_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    composite: Mapped[float | None] = mapped_column(Double, nullable=True)
    news_heat: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    coverage_fraction: Mapped[float] = mapped_column(Double, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint(
            "country_iso3",
            "scored_at",
            name="score_result_pk",
        ),
        Index("score_result_run_idx", "run_id"),
        Index(
            "score_result_country_idx",
            "country_iso3",
            scored_at.desc(),
        ),
    )

    @classmethod
    def from_domain(cls, result: ScoreResult) -> ScoreResultRow:
        """Construct a storage row from a canonical domain ScoreResult."""
        dimensions_json = {name: ds.model_dump() for name, ds in result.dimensions.items()}
        news_heat_json = result.news_heat.model_dump() if result.news_heat else None

        return cls(
            country_iso3=result.country_iso3,
            run_id=result.run_id,
            scored_at=result.scored_at,
            dimensions=dimensions_json,
            composite=result.composite,
            news_heat=news_heat_json,
            coverage_fraction=result.coverage_fraction,
        )

    def to_domain(self) -> ScoreResult:
        """Convert this storage row back to a canonical domain ScoreResult."""
        dimensions = {name: DimensionScore(**ds_data) for name, ds_data in self.dimensions.items()}
        news_heat = NewsHeat(**self.news_heat) if self.news_heat else None

        return ScoreResult(
            country_iso3=self.country_iso3,
            run_id=self.run_id,
            scored_at=self.scored_at,
            dimensions=dimensions,
            composite=self.composite,
            news_heat=news_heat,
            coverage_fraction=self.coverage_fraction,
        )
