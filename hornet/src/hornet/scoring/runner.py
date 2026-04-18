"""Async scoring orchestrator — wires DB repos to the scoring engine.

This is the entry point for a scoring run. It:
1. Loads ScoringConfig from YAML seed
2. Loads indicator map and country list from DB
3. For each country, queries observations and events
4. Runs the ScoringEngine
5. Persists results to the score_result table

Usage:
    results = await run_scoring()
"""

from __future__ import annotations

import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from hornet.db.repos.country import list_countries
from hornet.db.repos.event_record import list_events_for_scoring
from hornet.db.repos.observation import list_observations_for_scoring
from hornet.db.repos.score_result import upsert_score_results
from hornet.db.repos.source_indicator import list_source_indicators
from hornet.domain.scoring import ScoreResult
from hornet.scoring.engine import ScoringEngine
from hornet.seeds.loader import load_scoring_config_from_yaml

logger = structlog.get_logger(__name__)


async def run_scoring(
    session: AsyncSession,
    *,
    reference_date: datetime.date | None = None,
    countries_iso3: list[str] | None = None,
) -> list[ScoreResult]:
    """Execute a full scoring run.

    Parameters
    ----------
    session:
        Active DB session (caller owns the transaction).
    reference_date:
        Date for staleness gate checks. Defaults to today.
    countries_iso3:
        Optional list of countries to score. Defaults to all
        enabled countries in the registry.

    Returns
    -------
    list[ScoreResult]
        One per country, persisted to the score_result table.
    """
    reference_date = reference_date or datetime.date.today()

    # Load config and indicator map
    config = load_scoring_config_from_yaml()
    indicator_map = await list_source_indicators(session)

    # Determine which countries to score
    if countries_iso3 is None:
        country_specs = await list_countries(session)
        countries_iso3 = [c.iso3 for c in country_specs]

    logger.info(
        "scoring.run_start",
        n_countries=len(countries_iso3),
        n_indicators=len(indicator_map),
        reference_date=str(reference_date),
    )

    # Build scoring engine
    engine = ScoringEngine(config, indicator_map)

    # Fetch data and score each country
    observations_by_country = {}
    events_by_country = {}

    for iso3 in countries_iso3:
        observations_by_country[iso3] = await list_observations_for_scoring(
            session,
            country_iso3=iso3,
        )
        events_by_country[iso3] = await list_events_for_scoring(
            session,
            country_iso3=iso3,
        )

    # Run scoring engine
    results = engine.score_all(
        countries_iso3,
        observations_by_country,
        events_by_country,
        reference_date,
    )

    # Persist results
    n_persisted = await upsert_score_results(session, results)
    logger.info(
        "scoring.run_complete",
        n_scored=len(results),
        n_persisted=n_persisted,
        n_with_composite=sum(1 for r in results if r.composite is not None),
    )

    return results
