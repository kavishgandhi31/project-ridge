"""Observation data endpoints."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from hornet.db.models.observation import ObservationRow
from hornet.db.session import session_scope

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("")
async def get_observations(
    country_iso3: str | None = Query(None, description="Filter by country ISO3"),
    indicator_code: str | None = Query(None, description="Filter by indicator code"),
    source_id: str | None = Query(None, description="Filter by source (fred, yfinance, etc.)"),
    start_date: str | None = Query(None, description="Earliest date (YYYY-MM-DD)"),
    limit: int = Query(200, ge=1, le=5000),
) -> list[dict[str, object]]:
    """List observations with optional filters. Returns latest vintage per date."""
    async with session_scope() as session:
        stmt = select(ObservationRow).order_by(
            ObservationRow.date.desc(),
            ObservationRow.vintage.desc(),
        )

        if country_iso3 is not None:
            stmt = stmt.where(ObservationRow.country_iso3 == country_iso3)
        if indicator_code is not None:
            stmt = stmt.where(ObservationRow.indicator_code == indicator_code)
        if source_id is not None:
            stmt = stmt.where(ObservationRow.source_id == source_id)
        if start_date is not None:
            stmt = stmt.where(ObservationRow.date >= datetime.date.fromisoformat(start_date))

        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "country_iso3": r.country_iso3,
            "indicator_code": r.indicator_code,
            "source_id": r.source_id,
            "date": r.date.isoformat(),
            "value": r.value,
            "frequency": r.frequency,
            "vintage": r.vintage.isoformat(),
        }
        for r in rows
    ]
