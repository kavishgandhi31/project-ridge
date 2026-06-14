"""Tests for the scoring runner — covers the invariants the inline
orchestration in cli.py / scripts/run_pipeline.py historically broke:

1. A single ``pipeline_run_id`` is stamped on every ``ScoreResult`` in
   the batch (engine.score_country had auto-defaulted to a fresh UUID
   per call when callers did not pass run_id).
2. A single ``scored_at`` timestamp is shared across the batch (same
   bug — engine defaulted to ``datetime.now()`` per call, drifting by
   microseconds across 183 countries).
3. The ``progress_callback`` is invoked exactly once per country with
   the freshly-scored result and the elapsed seconds.

Uses real Postgres via the existing session fixtures; the runner is
glue code over the DB layer, so a thin integration test is the honest
coverage.
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from ridge.db.models.observation import ObservationRow
from ridge.db.models.score_result import ScoreResultRow
from ridge.db.models.source_indicator import SourceIndicatorRow
from ridge.db.session import session_scope
from ridge.domain.scoring import ScoreResult
from ridge.scoring.runner import run_scoring

_TEST_COUNTRIES = ("ZZA", "ZZB", "ZZC")
_TEST_SOURCE = "fake-runner-test"
_TEST_INDICATOR = "TEST_RUNNER"
_NOW = datetime.datetime(2026, 6, 13, tzinfo=datetime.UTC)


@pytest.fixture
async def runner_test_setup() -> AsyncIterator[None]:
    """Seed an indicator + 24 monthly observations for three synthetic countries.

    24 monthly points clears the ``min_observations=12`` z-score gate
    so the scoring engine produces non-None dimension scores. Three
    distinct countries let us verify shared run_id/scored_at across a
    real batch without hitting the (country, scored_at) PK twice.
    """

    async def _wipe() -> None:
        async with session_scope() as session:
            await session.execute(
                delete(ObservationRow).where(ObservationRow.source_id == _TEST_SOURCE)
            )
            await session.execute(
                delete(SourceIndicatorRow).where(
                    SourceIndicatorRow.source_id == _TEST_SOURCE
                )
            )
            await session.execute(
                delete(ScoreResultRow).where(
                    ScoreResultRow.country_iso3.in_(_TEST_COUNTRIES)
                )
            )

    await _wipe()
    async with session_scope() as session:
        session.add(
            SourceIndicatorRow(
                source_id=_TEST_SOURCE,
                source_native_code="TEST_R",
                indicator_code=_TEST_INDICATOR,
                frequency="monthly",
                countries_iso3=list(_TEST_COUNTRIES),
                dimension="growth_momentum",
                concept="test",
                global_signal=False,
                enabled=True,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        for iso3 in _TEST_COUNTRIES:
            for month in range(24):
                obs_date = datetime.date(2024, 1, 1) + datetime.timedelta(days=30 * month)
                session.add(
                    ObservationRow(
                        country_iso3=iso3,
                        indicator_code=_TEST_INDICATOR,
                        source_id=_TEST_SOURCE,
                        date=obs_date,
                        value=100.0 + month,
                        frequency="monthly",
                        vintage=_NOW,
                        ingested_at=_NOW,
                        quality_flags=[],
                    )
                )

    yield
    await _wipe()


@pytest.mark.usefixtures("runner_test_setup")
async def test_shared_run_id_and_scored_at_across_batch() -> None:
    """All score_results from one run share one run_id and scored_at."""
    pipeline_run_id = "test-run-123"

    results = await run_scoring(
        pipeline_run_id=pipeline_run_id,
        reference_date=datetime.date(2026, 1, 1),
        countries_iso3=list(_TEST_COUNTRIES),
    )

    assert len(results) == 3
    assert {r.run_id for r in results} == {pipeline_run_id}
    assert {r.scored_at for r in results} == {results[0].scored_at}


@pytest.mark.usefixtures("runner_test_setup")
async def test_progress_callback_fires_once_per_country() -> None:
    """progress_callback receives (score_result, elapsed_s) per iteration."""
    calls: list[tuple[ScoreResult, float]] = []

    def _capture(sr: ScoreResult, elapsed: float) -> None:
        calls.append((sr, elapsed))

    await run_scoring(
        pipeline_run_id="test-callback",
        reference_date=datetime.date(2026, 1, 1),
        countries_iso3=list(_TEST_COUNTRIES),
        progress_callback=_capture,
    )

    assert len(calls) == 3
    assert all(isinstance(sr, ScoreResult) for sr, _ in calls)
    assert all(elapsed >= 0.0 for _, elapsed in calls)
    assert [sr.country_iso3 for sr, _ in calls] == list(_TEST_COUNTRIES)
