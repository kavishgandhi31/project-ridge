"""PipelineRunRow -- SQLAlchemy storage mirror of PipelineRun.

The ``pipeline_run`` table replaces v1's JSON/pickle stage snapshots
with a proper database-backed audit trail. Each pipeline execution
creates one row, updated as stages complete.

Regular table (not hypertable) -- volume is 1 row per run.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Index,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from hornet.db.base import Base
from hornet.domain.pipeline import PipelineRun, RunStatus, RunType


class PipelineRunRow(Base):
    """SQLAlchemy ORM row for the ``pipeline_run`` table."""

    __tablename__ = "pipeline_run"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_type: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stages_completed: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
    )
    n_countries_scored: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    n_escalate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_alert: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_watch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("pipeline_run_status_idx", "status"),
        Index("pipeline_run_started_idx", started_at.desc()),
    )

    @classmethod
    def from_domain(cls, run: PipelineRun) -> PipelineRunRow:
        """Construct a storage row from a PipelineRun domain object."""
        return cls(
            run_id=run.run_id,
            run_type=run.run_type.value,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status.value,
            stages_completed=list(run.stages_completed),
            n_countries_scored=run.n_countries_scored,
            n_escalate=run.n_escalate,
            n_alert=run.n_alert,
            n_watch=run.n_watch,
            error_message=run.error_message,
        )

    def to_domain(self) -> PipelineRun:
        """Convert this row back to a PipelineRun domain object."""
        return PipelineRun(
            run_id=self.run_id,
            run_type=RunType(self.run_type),
            started_at=self.started_at,
            completed_at=self.completed_at,
            status=RunStatus(self.status),
            stages_completed=tuple(self.stages_completed),
            n_countries_scored=self.n_countries_scored,
            n_escalate=self.n_escalate,
            n_alert=self.n_alert,
            n_watch=self.n_watch,
            error_message=self.error_message,
        )
