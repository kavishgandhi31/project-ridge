"""Smart batching for LLM narratives -- skip countries with unchanged scores.

Compares the current scoring run against the most recent prior run.
Countries whose composite score moved less than the configured delta
threshold are skipped, saving ~2 minutes of LLM inference per skip.

For the first run (no prior scores), all countries are included.
ESCALATE countries always get rationales regardless of delta.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import structlog

from hornet.domain.scoring import ScoreResult

logger = structlog.get_logger(__name__)

# Default: regenerate narrative if composite changed by more than 0.15
DEFAULT_DELTA_THRESHOLD = 0.15


def select_narrative_countries(
    current_scores: Sequence[ScoreResult],
    prior_scores: Mapping[str, ScoreResult] | None = None,
    *,
    delta_threshold: float = DEFAULT_DELTA_THRESHOLD,
    always_include: frozenset[str] = frozenset(),
) -> list[str]:
    """Select countries that need a fresh narrative.

    A country is included if:
    1. No prior score exists (first run for this country).
    2. Composite changed by more than delta_threshold.
    3. Coverage fraction changed significantly (went from None to scored).
    4. Country is in always_include (e.g. ESCALATE countries).

    Parameters
    ----------
    current_scores:
        Score results from the current run.
    prior_scores:
        Most recent prior ScoreResult per country (keyed by iso3).
        None = first run, include all.
    delta_threshold:
        Minimum absolute composite change to trigger regeneration.
    always_include:
        Countries to always include (regardless of delta).

    Returns
    -------
    list[str]
        ISO3 codes that need fresh narratives.
    """
    if prior_scores is None:
        # First run -- generate for all
        all_countries = [sr.country_iso3 for sr in current_scores]
        logger.info(
            "batching.first_run",
            n_countries=len(all_countries),
        )
        return all_countries

    include: list[str] = []
    skip: list[str] = []

    for sr in current_scores:
        iso3 = sr.country_iso3

        # Always include if requested (e.g. ESCALATE countries)
        if iso3 in always_include:
            include.append(iso3)
            continue

        prior = prior_scores.get(iso3)

        # No prior score -- include (new country or first scoring)
        if prior is None:
            include.append(iso3)
            continue

        # Prior had no composite, now has one (or vice versa)
        if (prior.composite is None) != (sr.composite is None):
            include.append(iso3)
            continue

        # Both have composites -- check delta
        if sr.composite is not None and prior.composite is not None:
            delta = abs(sr.composite - prior.composite)
            if delta >= delta_threshold:
                include.append(iso3)
            else:
                skip.append(iso3)
        else:
            # Both None -- skip
            skip.append(iso3)

    logger.info(
        "batching.selected",
        n_include=len(include),
        n_skip=len(skip),
        threshold=delta_threshold,
    )

    if skip:
        logger.debug(
            "batching.skipped",
            countries=skip,
        )

    return include
