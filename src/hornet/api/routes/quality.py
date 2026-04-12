"""Quality issue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from hornet.db.repos.quality_issue import list_quality_issues
from hornet.db.session import session_scope

router = APIRouter(prefix="/quality", tags=["quality"])


@router.get("/issues")
async def get_quality_issues(
    run_id: str | None = Query(None, description="Filter by pipeline run ID"),
    country_iso3: str | None = Query(None, description="Filter by country ISO3"),
    check_name: str | None = Query(None, description="Filter by check name"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, object]]:
    """List quality issues with optional filters."""
    async with session_scope() as session:
        issues = await list_quality_issues(
            session,
            run_id=run_id,
            country_iso3=country_iso3,
            check_name=check_name,
            limit=limit,
        )
    return [
        {
            "check_name": i.check_name,
            "severity": i.severity,
            "country_iso3": i.country_iso3,
            "indicator_code": i.indicator_code,
            "source_id": i.source_id,
            "run_id": i.run_id,
            "detected_at": i.detected_at.isoformat(),
            "message": i.message,
            "detail": i.detail,
        }
        for i in issues
    ]
