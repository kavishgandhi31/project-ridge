"""Async alert orchestrator -- wires DB repos to pure alert functions.

This is the entry point for the alert stage of a pipeline run. It:
1. Loads AlertConfig from YAML seed
2. Queries prior alert records for streak/velocity computation
3. Runs the tier evaluator for each country
4. Dispatches into tier buckets
5. Composes a structured Digest
6. Persists alert records and pipeline run state

Usage:
    result, digest = await run_alerts(session, score_results, quality_issues, run_id)
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.alerts.config import AlertConfig
from hornet.alerts.digest import compose_digest
from hornet.alerts.dispatcher import dispatch
from hornet.alerts.tier import assign_tier
from hornet.db.repos.alert_record import list_prior_records, upsert_alert_records
from hornet.db.repos.country import list_countries
from hornet.domain.alerting import Digest, DispatchResult, TierAssignment
from hornet.domain.scoring import ScoreResult
from hornet.quality.issue import QualityIssue
from hornet.seeds.loader import load_alert_config_from_yaml

logger = structlog.get_logger(__name__)


async def run_alerts(
    session: AsyncSession,
    score_results: Sequence[ScoreResult],
    quality_issues: Sequence[QualityIssue],
    run_id: str,
    *,
    config: AlertConfig | None = None,
) -> tuple[DispatchResult, Digest]:
    """Execute the alert stage of a pipeline run.

    Parameters
    ----------
    session:
        Active DB session (caller owns the transaction).
    score_results:
        ScoreResults from the scoring stage.
    quality_issues:
        QualityIssues from the quality stage.
    run_id:
        Pipeline run ID for grouping.
    config:
        Optional AlertConfig override. Defaults to YAML seed.

    Returns
    -------
    tuple[DispatchResult, Digest]
        The dispatch result (for pipeline state tracking) and the
        structured digest (for rendering/API).
    """
    if config is None:
        config = load_alert_config_from_yaml()

    # Build country name/region lookup from registry.
    country_specs = await list_countries(session)
    country_map = {c.iso3: c for c in country_specs}

    logger.info(
        "alerts.run_start",
        n_scores=len(score_results),
        n_quality_issues=len(quality_issues),
        run_id=run_id,
    )

    # Evaluate tier for each country.
    assignments: list[TierAssignment] = []

    for score in score_results:
        iso3 = score.country_iso3
        spec = country_map.get(iso3)
        country_name = spec.name if spec else iso3
        region = spec.region if spec else None

        # Fetch prior alert records for streak/velocity.
        prior = await list_prior_records(session, iso3, limit=10)

        assignment = assign_tier(
            score_result=score,
            config=config,
            country_name=country_name,
            region=region,
            prior_records=prior,
        )
        assignments.append(assignment)

    # Dispatch into tier buckets.
    dispatch_result = dispatch(assignments, config)

    # Persist alert records.
    all_assignments = (
        list(dispatch_result.escalate)
        + list(dispatch_result.alert)
        + list(dispatch_result.watch)
        + list(dispatch_result.no_signal)
    )
    n_persisted = await upsert_alert_records(session, all_assignments)

    # Compose structured digest.
    digest = compose_digest(
        dispatch_result=dispatch_result,
        quality_issues=quality_issues,
        score_results=score_results,
        run_id=run_id,
    )

    logger.info(
        "alerts.run_complete",
        n_evaluated=len(assignments),
        n_persisted=n_persisted,
        n_escalate=len(dispatch_result.escalate),
        n_alert=len(dispatch_result.alert),
        n_watch=len(dispatch_result.watch),
    )

    return dispatch_result, digest
