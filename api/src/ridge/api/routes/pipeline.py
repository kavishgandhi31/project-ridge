"""Pipeline run endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ridge.db.repos.pipeline_run import get_pipeline_run, list_pipeline_runs
from ridge.db.session import session_scope

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/runs")
async def get_runs(
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, object]]:
    """List recent pipeline runs."""
    async with session_scope() as session:
        runs = await list_pipeline_runs(session, limit=limit)
    return [
        {
            "run_id": r.run_id,
            "run_type": r.run_type,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "status": r.status,
            "stages_completed": list(r.stages_completed),
            "n_countries_scored": r.n_countries_scored,
            "n_escalate": r.n_escalate,
            "n_alert": r.n_alert,
            "n_watch": r.n_watch,
            "error_message": r.error_message,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, object]:
    """Get a single pipeline run by ID."""
    async with session_scope() as session:
        run = await get_pipeline_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": run.run_id,
        "run_type": run.run_type,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "status": run.status,
        "stages_completed": list(run.stages_completed),
        "n_countries_scored": run.n_countries_scored,
        "n_escalate": run.n_escalate,
        "n_alert": run.n_alert,
        "n_watch": run.n_watch,
        "error_message": run.error_message,
    }
