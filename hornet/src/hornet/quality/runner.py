"""Quality runner -- orchestrates all 10 quality checks.

Wires DB repos to pure check functions and persists QualityIssue
records. Same pattern as the scoring runner.

Usage:
    issues = await run_quality_checks(session)
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.db.repos.quality_issue import insert_quality_issues
from hornet.db.repos.score_result import list_score_results
from hornet.db.repos.source_indicator import list_source_indicators
from hornet.domain.observation import Observation
from hornet.domain.scoring import ScoreResult
from hornet.domain.source import SourceIndicatorSpec
from hornet.quality.backfill import detect_backfills
from hornet.quality.config import QualityConfig
from hornet.quality.cross_source import validate_cross_source
from hornet.quality.date_consistency import check_date_consistency
from hornet.quality.flatline import detect_flatlines
from hornet.quality.issue import QualityIssue
from hornet.quality.outlier import detect_outliers
from hornet.quality.revision import detect_revisions
from hornet.quality.score_stability import check_score_stability
from hornet.quality.series_audit import audit_series_coverage
from hornet.quality.source_staleness import check_source_staleness
from hornet.quality.structural_break import detect_structural_breaks
from hornet.seeds.loader import load_quality_config_from_yaml

logger = structlog.get_logger(__name__)


async def run_quality_checks(
    session: AsyncSession,
    *,
    observations: Sequence[Observation] | None = None,
    indicator_specs: Sequence[SourceIndicatorSpec] | None = None,
    current_scores: Sequence[ScoreResult] | None = None,
    prior_scores: Sequence[ScoreResult] | None = None,
    reference_date: datetime.date | None = None,
    config: QualityConfig | None = None,
) -> list[QualityIssue]:
    """Execute all quality checks and persist results.

    Parameters
    ----------
    session:
        Active DB session. Used to load data if not provided and
        to persist quality issues.
    observations:
        Pre-loaded observations. If None, loads from DB for all
        countries (expensive — prefer passing pre-loaded data).
    indicator_specs:
        Pre-loaded indicator registry. If None, loads from DB.
    current_scores:
        Current scoring run results. If None, loads latest from DB.
    prior_scores:
        Prior scoring run results. If None, loads second-latest from DB.
    reference_date:
        Date for staleness checks. Defaults to today.
    config:
        Quality configuration. Defaults to YAML seed.
    """
    run_id = str(uuid.uuid4())
    detected_at = datetime.datetime.now(datetime.UTC)
    reference_date = reference_date or datetime.date.today()
    config = config or load_quality_config_from_yaml()

    # Load data if not provided
    if indicator_specs is None:
        indicator_specs = await list_source_indicators(session)

    if current_scores is None:
        current_scores = await list_score_results(session, limit=500)

    if prior_scores is None:
        # Get a different run's scores for comparison
        if current_scores:
            current_run = current_scores[0].run_id
            prior_scores = [
                r for r in await list_score_results(session, limit=1000) if r.run_id != current_run
            ]
        else:
            prior_scores = []

    logger.info(
        "quality.run_start",
        run_id=run_id,
        n_observations=len(observations) if observations is not None else "not_loaded",
        n_indicators=len(indicator_specs),
        n_current_scores=len(current_scores),
        n_prior_scores=len(prior_scores),
    )

    all_issues: list[QualityIssue] = []

    # --- Observation-based checks (Controls #1, #3, #5, #6, #7, #8, #10) ---
    if observations is not None:
        all_issues.extend(detect_outliers(observations, config, run_id, detected_at))
        all_issues.extend(detect_flatlines(observations, config, run_id, detected_at))
        all_issues.extend(detect_structural_breaks(observations, config, run_id, detected_at))
        all_issues.extend(validate_cross_source(observations, config, run_id, detected_at))
        all_issues.extend(detect_revisions(observations, config, run_id, detected_at))
        all_issues.extend(check_date_consistency(observations, config, run_id, detected_at))
        all_issues.extend(
            check_source_staleness(
                observations,
                reference_date,
                config,
                run_id,
                detected_at,
            )
        )

    # --- Score-based checks (Controls #4, #9) ---
    if current_scores and prior_scores:
        all_issues.extend(
            check_score_stability(
                current_scores,
                prior_scores,
                config,
                run_id,
                detected_at,
            )
        )
        all_issues.extend(
            detect_backfills(
                current_scores,
                prior_scores,
                config,
                run_id,
                detected_at,
            )
        )

    # --- Registry check (Control #2) ---
    if observations is not None:
        # Build observation counts from the provided observations
        obs_counts: dict[tuple[str, str, str], int] = {}
        for obs in observations:
            key = (obs.country_iso3, obs.indicator_code, obs.source_id)
            obs_counts[key] = obs_counts.get(key, 0) + 1

        all_issues.extend(
            audit_series_coverage(
                indicator_specs,
                obs_counts,
                config,
                run_id,
                detected_at,
            )
        )

    # Persist
    n_persisted = await insert_quality_issues(session, all_issues)

    by_severity: dict[str, int] = {}
    for issue in all_issues:
        by_severity[issue.severity.value] = by_severity.get(issue.severity.value, 0) + 1

    logger.info(
        "quality.run_complete",
        run_id=run_id,
        total_issues=len(all_issues),
        persisted=n_persisted,
        by_severity=by_severity,
    )

    return all_issues
