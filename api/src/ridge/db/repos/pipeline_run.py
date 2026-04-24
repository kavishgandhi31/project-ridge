"""Read/write accessors for the pipeline_run table."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ridge.db.models.pipeline_run import PipelineRunRow
from ridge.domain.pipeline import PipelineRun


async def upsert_pipeline_run(
    session: AsyncSession,
    run: PipelineRun,
) -> None:
    """Insert or update a pipeline run.

    Uses ON CONFLICT to allow updating an existing run (e.g. when
    marking it as completed or recording a failure).
    """
    values = {
        "run_id": run.run_id,
        "run_type": run.run_type.value,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "status": run.status.value,
        "stages_completed": list(run.stages_completed),
        "n_countries_scored": run.n_countries_scored,
        "n_escalate": run.n_escalate,
        "n_alert": run.n_alert,
        "n_watch": run.n_watch,
        "error_message": run.error_message,
    }

    stmt = pg_insert(PipelineRunRow).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["run_id"],
        set_={
            "completed_at": stmt.excluded.completed_at,
            "status": stmt.excluded.status,
            "stages_completed": stmt.excluded.stages_completed,
            "n_countries_scored": stmt.excluded.n_countries_scored,
            "n_escalate": stmt.excluded.n_escalate,
            "n_alert": stmt.excluded.n_alert,
            "n_watch": stmt.excluded.n_watch,
            "error_message": stmt.excluded.error_message,
        },
    )
    await session.execute(stmt)


async def mark_stage_completed(
    session: AsyncSession,
    run_id: str,
    stage_name: str,
) -> None:
    """Append a stage name to stages_completed for the given run.

    Uses Postgres array_append to atomically add the stage without
    re-reading the row.
    """
    from sqlalchemy import func, literal_column

    stmt = (
        update(PipelineRunRow)
        .where(PipelineRunRow.run_id == run_id)
        .values(
            stages_completed=func.array_append(
                PipelineRunRow.stages_completed,
                literal_column(f"'{stage_name}'"),
            ),
        )
    )
    await session.execute(stmt)


async def get_pipeline_run(
    session: AsyncSession,
    run_id: str,
) -> PipelineRun | None:
    """Fetch a single pipeline run by ID."""
    stmt = select(PipelineRunRow).where(PipelineRunRow.run_id == run_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return row.to_domain() if row else None


async def list_pipeline_runs(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> list[PipelineRun]:
    """List recent pipeline runs, most recent first."""
    stmt = select(PipelineRunRow).order_by(PipelineRunRow.started_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]
