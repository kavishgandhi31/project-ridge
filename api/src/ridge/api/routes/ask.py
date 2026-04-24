"""Interactive Ask-a-Question endpoint.

POST /ask accepts a user question and country context,
routes it through the LLM layer with grounded citations,
and returns the response.

GET /ask/warmup/{iso3} pre-builds and caches the grounded context
for a country so subsequent questions skip the DB fetch + context build.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ridge.config import get_settings
from ridge.db.models.observation import ObservationRow
from ridge.db.session import session_scope
from ridge.domain.llm import GroundedContext
from ridge.llm.citations import validate_response
from ridge.llm.context import build_grounded_context
from ridge.llm.router import LLMRouter, NoProviderAvailableError
from ridge.llm.templates.interactive_query import InteractiveQueryTemplate

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ask"])

# Lazily initialized router -- constructed on first request.
_llm_router: LLMRouter | None = None
_template = InteractiveQueryTemplate()

# Context cache: (iso3, date) -> GroundedContext.
# Cleared daily by the date key. In-memory is fine -- this is a
# single-server product on a Mac Mini, not a distributed system.
_context_cache: dict[tuple[str, str], GroundedContext] = {}


def _get_llm_router() -> LLMRouter:
    """Construct or return the cached LLM router.

    The router is a module-level singleton so provider health checks
    and token budget tracking persist across requests within a process.
    """
    global _llm_router
    if _llm_router is not None:
        return _llm_router

    from ridge.seeds.loader import load_llm_config_from_yaml

    llm_config = load_llm_config_from_yaml()
    providers: dict[str, Any] = {}

    settings = get_settings()

    # Claude is required for interactive queries
    if settings.anthropic_api_key:
        from ridge.llm.providers.claude import ClaudeProvider

        providers["claude"] = ClaudeProvider(
            llm_config.claude,
            api_key=settings.anthropic_api_key.get_secret_value(),
        )
    else:
        logger.warning(
            "ask.no_anthropic_key",
            msg="RIDGE_ANTHROPIC_API_KEY not set -- /ask endpoint will fail",
        )

    # Ollama as optional fallback
    try:
        import httpx

        resp = httpx.get(f"{llm_config.ollama.base_url}/api/tags", timeout=3)
        if resp.status_code == 200:
            from ridge.llm.providers.ollama import OllamaProvider

            providers["ollama"] = OllamaProvider(llm_config.ollama)
    except Exception:
        pass  # Ollama not available -- fine, Claude is the primary

    _llm_router = LLMRouter(llm_config, providers)
    return _llm_router


async def _build_context(iso3: str) -> GroundedContext:
    """Fetch observations and build grounded context for a country.

    Checks the in-memory cache first. Cache key is (iso3, today's date)
    so context refreshes daily when new pipeline data arrives.
    """
    reference_date = datetime.date.today()
    cache_key = (iso3, reference_date.isoformat())

    cached = _context_cache.get(cache_key)
    if cached is not None:
        logger.debug("ask.context_cache_hit", country=iso3)
        return cached

    # Fetch observations
    async with session_scope() as session:
        stmt = (
            select(ObservationRow)
            .where(ObservationRow.country_iso3 == iso3)
            .order_by(
                ObservationRow.date.desc(),
                ObservationRow.vintage.desc(),
            )
            .limit(500)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No observations found for {iso3}",
        )

    observations = [r.to_domain() for r in rows]

    context = build_grounded_context(
        country_iso3=iso3,
        reference_date=reference_date,
        observations=observations,
        token_budget=12000,
    )

    # Evict stale entries for this country (old dates)
    for key in [k for k in _context_cache if k[0] == iso3 and k[1] != cache_key[1]]:
        del _context_cache[key]

    _context_cache[cache_key] = context
    logger.info(
        "ask.context_built",
        country=iso3,
        n_citations=len(context.citations),
        token_estimate=context.token_estimate,
    )
    return context


class AskRequest(BaseModel):
    """Request body for the /ask endpoint."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="The user's question about the country.",
    )
    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 3-letter country code.",
    )


class AskResponse(BaseModel):
    """Response body for the /ask endpoint."""

    content: str
    citations_used: list[dict[str, Any]]
    grounding_score: float


@router.get("/ask/warmup/{iso3}")
async def warmup_context(iso3: str) -> dict[str, object]:
    """Pre-build and cache the grounded context for a country.

    Called by the frontend when a country page loads. This way
    the context is ready before the user types a question,
    eliminating DB fetch + context build latency from the ask flow.
    """
    iso3 = iso3.upper()
    context = await _build_context(iso3)
    return {
        "country_iso3": iso3,
        "n_citations": len(context.citations),
        "token_estimate": context.token_estimate,
        "cached": True,
    }


@router.post("/ask")
async def ask_question(body: AskRequest) -> AskResponse:
    """Answer a grounded question about a country.

    Uses cached context if available (from warmup), otherwise
    builds it on the fly.
    """
    iso3 = body.country_iso3.upper()
    run_id = f"ask-{uuid.uuid4().hex[:12]}"

    # Get context (cache hit if warmup was called)
    context = await _build_context(iso3)

    # Build LLM request
    request = _template.build_request(
        context,
        country_name=iso3,
        run_id=run_id,
        user_question=body.question,
    )

    # Route to provider
    try:
        llm_router = _get_llm_router()
        llm_response = await llm_router.generate(request)
    except NoProviderAvailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No LLM provider available: {e}",
        ) from e

    # Validate and extract citations
    grounded = validate_response(
        llm_response,
        context.citations,
        task_type=_template.task_type,
        template_name=_template.template_name,
        country_iso3=iso3,
        run_id=run_id,
    )

    # Serialize citations for the response
    citations_json = [
        {
            "ref_number": c.ref_number,
            "country_iso3": c.country_iso3,
            "indicator_code": c.indicator_code,
            "source_id": c.source_id,
            "date": c.date.isoformat(),
            "value": c.value,
            "vintage": c.vintage.isoformat(),
            "display_label": c.display_label,
        }
        for c in grounded.citations_used
    ]

    logger.info(
        "ask.complete",
        country=iso3,
        question_len=len(body.question),
        grounding_score=grounded.grounding_score,
        n_citations=len(grounded.citations_used),
    )

    return AskResponse(
        content=grounded.content,
        citations_used=citations_json,
        grounding_score=grounded.grounding_score,
    )
