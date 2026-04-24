"""LLM narrative/rationale endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ridge.db.repos.llm_response import list_llm_responses
from ridge.db.session import session_scope

router = APIRouter(prefix="/narratives", tags=["narratives"])


@router.get("")
async def get_narratives(
    country_iso3: str | None = Query(None, description="Filter by country ISO3"),
    run_id: str | None = Query(None, description="Filter by pipeline run ID"),
    template_name: str | None = Query(
        None, description="Filter by template (country_narrative, alert_rationale)"
    ),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, object]]:
    """List LLM-generated narratives and rationales."""
    async with session_scope() as session:
        rows = await list_llm_responses(
            session,
            country_iso3=country_iso3,
            run_id=run_id,
            template_name=template_name,
            limit=limit,
        )
    return [
        {
            "response_id": r.response_id,
            "run_id": r.run_id,
            "country_iso3": r.country_iso3,
            "template_name": r.template_name,
            "task_type": r.task_type,
            "provider_id": r.provider_id,
            "model_id": r.model_id,
            "content": r.content,
            "citations_used": r.citations_used,
            "citations_available_count": r.citations_available_count,
            "ungrounded_claims": r.ungrounded_claims,
            "grounding_score": r.grounding_score,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "latency_ms": r.latency_ms,
            "generated_at": r.generated_at.isoformat(),
        }
        for r in rows
    ]
