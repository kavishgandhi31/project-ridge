"""Read/write accessors for the llm_response table.

Provides persistence for LLM generations and query access for the
API, eval harness, and Phase 8 citation-chip renderer.
"""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.db.models.llm_response import LLMResponseRow
from hornet.domain.llm import GroundedResponse


async def upsert_llm_response(
    session: AsyncSession,
    response: GroundedResponse,
) -> str:
    """Persist a grounded LLM response. Returns the response_id.

    Uses INSERT ... ON CONFLICT DO UPDATE on response_id so that
    re-running the same generation (e.g. during eval) overwrites
    rather than duplicating.
    """
    row = LLMResponseRow.from_domain(response)

    stmt = pg_insert(LLMResponseRow).values(
        response_id=row.response_id,
        run_id=row.run_id,
        country_iso3=row.country_iso3,
        template_name=row.template_name,
        task_type=row.task_type,
        provider_id=row.provider_id,
        model_id=row.model_id,
        content=row.content,
        citations_used=row.citations_used,
        citations_available_count=row.citations_available_count,
        ungrounded_claims=row.ungrounded_claims,
        grounding_score=row.grounding_score,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        latency_ms=row.latency_ms,
        generated_at=row.generated_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["response_id"],
        set_={
            "content": stmt.excluded.content,
            "citations_used": stmt.excluded.citations_used,
            "citations_available_count": stmt.excluded.citations_available_count,
            "ungrounded_claims": stmt.excluded.ungrounded_claims,
            "grounding_score": stmt.excluded.grounding_score,
            "tokens_in": stmt.excluded.tokens_in,
            "tokens_out": stmt.excluded.tokens_out,
            "latency_ms": stmt.excluded.latency_ms,
            "generated_at": stmt.excluded.generated_at,
        },
    )
    await session.execute(stmt)
    return row.response_id


async def list_llm_responses(
    session: AsyncSession,
    *,
    run_id: str | None = None,
    country_iso3: str | None = None,
    template_name: str | None = None,
    since: datetime.datetime | None = None,
    limit: int = 100,
) -> list[LLMResponseRow]:
    """Query LLM responses with optional filters.

    Returns rows (not domain objects) since GroundedResponse requires
    the full citation table which we don't store back in domain form.
    Consumers that need structured citations can parse the JSONB.
    """
    stmt = select(LLMResponseRow).order_by(LLMResponseRow.generated_at.desc())

    if run_id is not None:
        stmt = stmt.where(LLMResponseRow.run_id == run_id)
    if country_iso3 is not None:
        stmt = stmt.where(LLMResponseRow.country_iso3 == country_iso3)
    if template_name is not None:
        stmt = stmt.where(LLMResponseRow.template_name == template_name)
    if since is not None:
        stmt = stmt.where(LLMResponseRow.generated_at >= since)

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_responses_for_run(
    session: AsyncSession,
    run_id: str,
) -> list[LLMResponseRow]:
    """All LLM responses for a specific pipeline run."""
    return await list_llm_responses(session, run_id=run_id, limit=500)
