"""Async scoring orchestrator — the single entry point for a scoring run.

Both ``ridge.cli`` and ``scripts/run_pipeline.py`` call ``run_scoring``;
they used to inline this orchestration and had drifted apart on the
load/score/persist pattern.

Memory and id discipline (both bugs the inline callers had):
1. **Streaming per country** — load → score → discard. Holds at most
   one country's observations in RAM (~30-50MB), not the
   ~14GB dict-of-all-countries pattern earlier versions tried.
2. **One run_id, one scored_at** per batch — generated once before
   the loop and passed to every ``score_country`` call so the
   ``score_result.run_id`` and ``scored_at`` columns actually group
   one logical run.

Read all observations under a single session; commit the bulk upsert
under a second session so the read transaction stays short-write-free.
"""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable, Sequence

import structlog

from ridge.db.repos.country import list_countries
from ridge.db.repos.event_record import list_events_for_scoring
from ridge.db.repos.observation import list_observations_for_scoring
from ridge.db.repos.score_result import upsert_score_results
from ridge.db.repos.source_indicator import list_source_indicators
from ridge.db.session import session_scope
from ridge.domain.scoring import ScoreResult
from ridge.scoring.engine import ScoringEngine
from ridge.seeds.loader import load_scoring_config_from_yaml

logger = structlog.get_logger(__name__)

ProgressCallback = Callable[[ScoreResult, float], None]


async def run_scoring(
    *,
    pipeline_run_id: str,
    reference_date: datetime.date | None = None,
    countries_iso3: Sequence[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[ScoreResult]:
    """Run scoring for ``countries_iso3`` and persist results.

    Parameters
    ----------
    pipeline_run_id:
        Run id stamped on every ``score_result`` row from this batch.
        Pass the outer pipeline's run id so the score, alert, and
        llm tables all share one identifier per pipeline invocation.
    reference_date:
        Date for staleness gate checks. Defaults to today.
    countries_iso3:
        Countries to score. Defaults to every enabled country in the
        registry.
    progress_callback:
        Invoked after each country with ``(score_result, elapsed_s)``
        so callers can emit their own per-country log line.

    Returns
    -------
    list[ScoreResult]
        One per country, persisted to the ``score_result`` table.
    """
    reference_date = reference_date or datetime.date.today()
    scored_at = datetime.datetime.now(datetime.UTC)

    config = load_scoring_config_from_yaml()
    async with session_scope() as session:
        indicator_map = await list_source_indicators(session)
        if countries_iso3 is None:
            countries_iso3 = [c.iso3 for c in await list_countries(session)]

    logger.info(
        "scoring.run_start",
        n_countries=len(countries_iso3),
        n_indicators=len(indicator_map),
        reference_date=str(reference_date),
        pipeline_run_id=pipeline_run_id,
    )

    engine = ScoringEngine(config, indicator_map)

    results: list[ScoreResult] = []
    async with session_scope() as session:
        for iso3 in countries_iso3:
            obs = await list_observations_for_scoring(session, country_iso3=iso3)
            events = await list_events_for_scoring(session, country_iso3=iso3)

            t0 = time.perf_counter()
            sr = engine.score_country(
                iso3,
                obs,
                events,
                reference_date,
                run_id=pipeline_run_id,
                scored_at=scored_at,
            )
            elapsed = time.perf_counter() - t0
            results.append(sr)

            if progress_callback is not None:
                progress_callback(sr, elapsed)

    async with session_scope() as session:
        n_persisted = await upsert_score_results(session, results)

    logger.info(
        "scoring.run_complete",
        n_scored=len(results),
        n_persisted=n_persisted,
        n_with_composite=sum(1 for r in results if r.composite is not None),
        pipeline_run_id=pipeline_run_id,
    )

    return results
