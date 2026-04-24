"""Country registry endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ridge.db.repos.country import list_countries
from ridge.db.session import session_scope

router = APIRouter(prefix="/countries", tags=["countries"])


@router.get("")
async def get_countries() -> list[dict[str, object]]:
    """List all enabled countries."""
    async with session_scope() as session:
        specs = await list_countries(session)
    return [
        {
            "iso3": s.iso3,
            "iso2": s.iso2,
            "name": s.name,
            "region": s.region,
            "income_group": s.income_group,
        }
        for s in specs
    ]
