"""LLM stage runner -- generates grounded narratives for pipeline runs.

Plugs into the pipeline after the alert stage: given a DispatchResult,
it generates narratives for scored countries and rationales for
ESCALATE-tier countries.

This module is the hinge between the pipeline (which produces scores
and tier assignments) and the LLM layer (which generates narratives).
Like the ingest runner, it keeps business logic (template selection,
context building) separate from the provider layer (which only knows
how to call an LLM API).

Usage:
    from hornet.llm.runner import run_llm_stage

    results = await run_llm_stage(
        router=router,
        dispatch=dispatch_result,
        observations_by_country=obs_map,
        scores_by_country=scores_map,
        events_by_country=events_map,
        country_names=name_map,
        run_id=run_id,
        reference_date=today,
    )
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence

import structlog

from hornet.domain.alerting import DispatchResult, TierAssignment
from hornet.domain.event import EventRecord
from hornet.domain.llm import GroundedResponse
from hornet.domain.observation import Observation
from hornet.domain.scoring import ScoreResult
from hornet.llm.citations import validate_response
from hornet.llm.context import build_grounded_context
from hornet.llm.router import LLMRouter, NoProviderAvailableError
from hornet.llm.templates.alert_rationale import AlertRationaleTemplate
from hornet.llm.templates.country_narrative import CountryNarrativeTemplate

logger = structlog.get_logger(__name__)


def _extract_score_values(score: ScoreResult | None) -> frozenset[float]:
    """Extract numeric values from a ScoreResult that appear in the context.

    These are dimension scores and the composite -- the LLM may reference
    them without citation markers since they come from the score summary
    section, not from observation data.
    """
    if score is None:
        return frozenset()
    values: set[float] = set()
    if score.composite is not None:
        values.add(score.composite)
    for dim in score.dimensions.values():
        if dim.value is not None:
            values.add(dim.value)
    return frozenset(values)


class LLMStageResult:
    """Summary of the LLM stage's output.

    Collects narratives, rationales, and any errors that occurred
    during generation.
    """

    def __init__(self) -> None:
        self.narratives: list[GroundedResponse] = []
        self.rationales: list[GroundedResponse] = []
        self.errors: list[dict[str, str]] = []

    @property
    def total_generated(self) -> int:
        return len(self.narratives) + len(self.rationales)

    @property
    def total_errors(self) -> int:
        return len(self.errors)


async def run_llm_stage(
    *,
    router: LLMRouter,
    dispatch: DispatchResult,
    observations_by_country: Mapping[str, Sequence[Observation]],
    scores_by_country: Mapping[str, ScoreResult],
    events_by_country: Mapping[str, Sequence[EventRecord]] | None = None,
    country_names: Mapping[str, str],
    run_id: str,
    reference_date: datetime.date,
    narrative_countries: Sequence[str] | None = None,
    token_budget: int = 8000,
) -> LLMStageResult:
    """Run the LLM stage for a pipeline run.

    Generates:
    1. Country narratives for all scored countries (or a subset).
    2. Alert rationales for ESCALATE-tier countries.

    Errors are caught per-country -- a failed generation for one
    country does not block others. Failed countries are logged and
    recorded in the result.

    Parameters
    ----------
    router:
        The LLM router with providers configured.
    dispatch:
        Tier assignments from the alert stage.
    observations_by_country:
        Latest observations keyed by iso3.
    scores_by_country:
        Score results keyed by iso3.
    events_by_country:
        Events keyed by iso3 (optional).
    country_names:
        iso3 -> human name mapping.
    run_id:
        Pipeline run ID.
    reference_date:
        As-of date for context building.
    narrative_countries:
        If provided, generate narratives only for these countries.
        If None, generate for all countries in scores_by_country.
    token_budget:
        Token budget for context building per country.
    """
    result = LLMStageResult()
    narrative_template = CountryNarrativeTemplate()
    rationale_template = AlertRationaleTemplate()

    # Determine which countries get narratives
    if narrative_countries is not None:
        narr_countries = list(narrative_countries)
    else:
        narr_countries = list(scores_by_country.keys())

    # 1. Generate country narratives
    logger.info(
        "llm_stage.narratives.start",
        n_countries=len(narr_countries),
        run_id=run_id,
    )

    for iso3 in narr_countries:
        observations = observations_by_country.get(iso3, [])
        score = scores_by_country.get(iso3)
        events = (events_by_country or {}).get(iso3, [])
        name = country_names.get(iso3, iso3)

        try:
            context = build_grounded_context(
                country_iso3=iso3,
                reference_date=reference_date,
                observations=observations,
                score_result=score,
                events=events,
                token_budget=token_budget,
            )

            request = narrative_template.build_request(
                context,
                country_name=name,
                run_id=run_id,
            )

            llm_response = await router.generate(request)

            grounded = validate_response(
                llm_response,
                context.citations,
                task_type=narrative_template.task_type,
                template_name=narrative_template.template_name,
                country_iso3=iso3,
                run_id=run_id,
                known_score_values=_extract_score_values(score),
            )
            result.narratives.append(grounded)

        except NoProviderAvailableError as e:
            logger.warning("llm_stage.narrative.no_provider", country=iso3, error=str(e))
            result.errors.append(
                {"country_iso3": iso3, "template": "country_narrative", "error": str(e)}
            )
        except Exception as e:
            logger.error("llm_stage.narrative.error", country=iso3, error=str(e))
            result.errors.append(
                {"country_iso3": iso3, "template": "country_narrative", "error": str(e)}
            )

    logger.info(
        "llm_stage.narratives.done",
        n_generated=len(result.narratives),
        n_errors=len(result.errors),
    )

    # 2. Generate alert rationales for ESCALATE countries
    escalate_countries: list[TierAssignment] = list(dispatch.escalate)

    if escalate_countries:
        logger.info(
            "llm_stage.rationales.start",
            n_escalate=len(escalate_countries),
            run_id=run_id,
        )

        for assignment in escalate_countries:
            iso3 = assignment.country_iso3
            observations = observations_by_country.get(iso3, [])
            score = scores_by_country.get(iso3)
            events = (events_by_country or {}).get(iso3, [])
            name = country_names.get(iso3, iso3)

            try:
                context = build_grounded_context(
                    country_iso3=iso3,
                    reference_date=reference_date,
                    observations=observations,
                    score_result=score,
                    events=events,
                    token_budget=token_budget,
                )

                request = rationale_template.build_request(
                    context,
                    country_name=name,
                    run_id=run_id,
                )

                llm_response = await router.generate(request)

                grounded = validate_response(
                    llm_response,
                    context.citations,
                    task_type=rationale_template.task_type,
                    template_name=rationale_template.template_name,
                    country_iso3=iso3,
                    run_id=run_id,
                    known_score_values=_extract_score_values(score),
                )
                result.rationales.append(grounded)

            except NoProviderAvailableError as e:
                logger.warning("llm_stage.rationale.no_provider", country=iso3, error=str(e))
                result.errors.append(
                    {"country_iso3": iso3, "template": "alert_rationale", "error": str(e)}
                )
            except Exception as e:
                logger.error("llm_stage.rationale.error", country=iso3, error=str(e))
                result.errors.append(
                    {"country_iso3": iso3, "template": "alert_rationale", "error": str(e)}
                )

        logger.info(
            "llm_stage.rationales.done",
            n_generated=len(result.rationales),
        )

    logger.info(
        "llm_stage.complete",
        total_generated=result.total_generated,
        total_errors=result.total_errors,
        run_id=run_id,
    )

    return result
