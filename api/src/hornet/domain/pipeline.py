"""Pipeline run domain type -- DB-backed run state.

Replaces v1's JSON/pickle stage snapshots with a typed domain model
that maps to the ``pipeline_run`` table. Each pipeline execution
creates one PipelineRun, updates ``stages_completed`` as stages
finish, and sets ``completed_at`` + ``status`` at the end.

Unlike v1 (which only tracked whole-run completion), this model
records per-stage progress so a failed run can be inspected to see
exactly which stage broke.
"""

from __future__ import annotations

import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    """Pipeline run lifecycle states."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunType(StrEnum):
    """How the pipeline run was triggered."""

    DAILY = "daily"
    MANUAL = "manual"
    BACKFILL = "backfill"


class PipelineRun(BaseModel):
    """One execution of the pipeline -- the unit of audit history.

    Stages are tracked as an ordered tuple of names (e.g.
    ``("ingest", "quality", "score", "alert", "digest")``).
    The runner appends to ``stages_completed`` as each stage finishes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(
        ...,
        min_length=1,
        description="UUID string for this pipeline execution.",
    )
    run_type: RunType = Field(
        ...,
        description="How this run was triggered.",
    )
    started_at: datetime.datetime = Field(
        ...,
        description="UTC timestamp when the run began.",
    )
    completed_at: datetime.datetime | None = Field(
        default=None,
        description="UTC timestamp when the run finished (None if still running).",
    )
    status: RunStatus = Field(
        ...,
        description="Current lifecycle state.",
    )
    stages_completed: tuple[str, ...] = Field(
        default=(),
        description="Ordered list of stages that finished successfully.",
    )
    n_countries_scored: int = Field(
        default=0,
        description="Number of countries that received scores.",
    )
    n_escalate: int = Field(
        default=0,
        description="Countries at ESCALATE tier.",
    )
    n_alert: int = Field(
        default=0,
        description="Countries at ALERT tier.",
    )
    n_watch: int = Field(
        default=0,
        description="Countries at WATCH tier.",
    )
    error_message: str | None = Field(
        default=None,
        description="Error message if status is FAILED.",
    )
