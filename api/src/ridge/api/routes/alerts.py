"""Alert record endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ridge.db.repos.alert_record import list_alert_records
from ridge.db.session import session_scope

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def get_alerts(
    country_iso3: str | None = Query(None, description="Filter by country ISO3"),
    run_id: str | None = Query(None, description="Filter by pipeline run ID"),
    effective_tier: str | None = Query(None, description="Filter by tier (watch, alert, escalate)"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, object]]:
    """List alert records with optional filters."""
    async with session_scope() as session:
        records = await list_alert_records(
            session,
            country_iso3=country_iso3,
            run_id=run_id,
            effective_tier=effective_tier,
            limit=limit,
        )
    return records
