"""Score result endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from hornet.db.repos.score_result import list_score_results
from hornet.db.session import session_scope

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("")
async def get_scores(
    country_iso3: str | None = Query(None, description="Filter by country ISO3"),
    run_id: str | None = Query(None, description="Filter by pipeline run ID"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, object]]:
    """List score results with optional filters."""
    async with session_scope() as session:
        results = await list_score_results(
            session,
            country_iso3=country_iso3,
            run_id=run_id,
            limit=limit,
        )
    return [
        {
            "country_iso3": r.country_iso3,
            "run_id": r.run_id,
            "scored_at": r.scored_at.isoformat(),
            "composite": r.composite,
            "coverage_fraction": r.coverage_fraction,
            "dimensions": {
                k: {
                    "dimension": v.dimension,
                    "value": v.value,
                    "n_series_used": v.n_series_used,
                    "n_concepts": v.n_concepts,
                }
                for k, v in r.dimensions.items()
            },
            "news_heat": {
                "sigma": r.news_heat.sigma,
                "volume_ratio": r.news_heat.volume_ratio,
            }
            if r.news_heat
            else None,
        }
        for r in results
    ]
