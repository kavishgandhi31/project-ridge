"""Tests for the pipeline_run repository functions.

The injection-safety test (``test_stage_name_is_bound_parameter``) is
the load-bearing one: it proves that ``mark_stage_completed`` treats
``stage_name`` as data, not SQL. The happy-path tests cover the rest
of the function's behaviour.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select, text

from ridge.db.models.pipeline_run import PipelineRunRow
from ridge.db.repos.pipeline_run import (
    ORPHAN_THRESHOLD,
    fail_orphan_runs,
    get_pipeline_run,
    mark_stage_completed,
    upsert_pipeline_run,
)
from ridge.db.session import session_scope
from ridge.domain.pipeline import PipelineRun, RunStatus, RunType

_TEST_RUN_ID_PREFIX = "test-pipeline-repo-"


@pytest.fixture
async def clean_test_runs() -> AsyncIterator[None]:
    """Wipe test-created pipeline_run rows before and after each test."""

    async def _wipe() -> None:
        async with session_scope() as session:
            await session.execute(
                delete(PipelineRunRow).where(PipelineRunRow.run_id.like(f"{_TEST_RUN_ID_PREFIX}%"))
            )

    await _wipe()
    yield
    await _wipe()


async def _seed_run(run_id: str) -> None:
    run = PipelineRun(
        run_id=run_id,
        run_type=RunType.MANUAL,
        started_at=datetime.datetime.now(datetime.UTC),
        status=RunStatus.RUNNING,
    )
    async with session_scope() as session:
        await upsert_pipeline_run(session, run)


async def _fetch_stages(run_id: str) -> list[str]:
    async with session_scope() as session:
        result = await session.execute(
            select(PipelineRunRow.stages_completed).where(PipelineRunRow.run_id == run_id)
        )
        row = result.scalar_one_or_none()
    assert row is not None
    return list(row)


class TestMarkStageCompleted:
    async def test_appends_stage_to_empty_list(
        self,
        clean_test_runs: None,
    ) -> None:
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        await _seed_run(run_id)

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, "ingest")

        assert await _fetch_stages(run_id) == ["ingest"]

    async def test_appends_in_order(
        self,
        clean_test_runs: None,
    ) -> None:
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        await _seed_run(run_id)

        for stage in ("seed", "ingest", "quality", "score"):
            async with session_scope() as session:
                await mark_stage_completed(session, run_id, stage)

        assert await _fetch_stages(run_id) == [
            "seed",
            "ingest",
            "quality",
            "score",
        ]

    async def test_stage_name_is_bound_parameter(
        self,
        clean_test_runs: None,
    ) -> None:
        """Verify mark_stage_completed treats stage_name as data, not SQL.

        Before the literal() fix, the function built SQL via an f-string
        in literal_column(), which would have interpreted this input as
        a statement terminator followed by DROP TABLE.
        """
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        await _seed_run(run_id)

        malicious = "ingest'); DROP TABLE pipeline_run; --"

        async with session_scope() as session:
            await mark_stage_completed(session, run_id, malicious)

        # The malicious string must land in the array verbatim --
        # not interpreted as SQL.
        assert await _fetch_stages(run_id) == [malicious]

        # The pipeline_run table must still exist.
        async with session_scope() as session:
            result = await session.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'pipeline_run'")
            )
            assert result.scalar() == 1


class TestFailOrphanRuns:
    async def _seed_run_at(self, run_id: str, started_at: datetime.datetime) -> None:
        run = PipelineRun(
            run_id=run_id,
            run_type=RunType.MANUAL,
            started_at=started_at,
            status=RunStatus.RUNNING,
        )
        async with session_scope() as session:
            await upsert_pipeline_run(session, run)

    async def test_marks_stale_running_run_as_failed(
        self,
        clean_test_runs: None,
    ) -> None:
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        stale_start = datetime.datetime.now(datetime.UTC) - ORPHAN_THRESHOLD - datetime.timedelta(minutes=1)
        await self._seed_run_at(run_id, stale_start)

        async with session_scope() as session:
            orphaned = await fail_orphan_runs(session)

        assert run_id in orphaned
        async with session_scope() as session:
            run = await get_pipeline_run(session, run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED
        assert run.error_message == "orphaned: process did not finish before next run started"
        assert run.completed_at is not None

    async def test_leaves_fresh_running_run_untouched(
        self,
        clean_test_runs: None,
    ) -> None:
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        fresh_start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)
        await self._seed_run_at(run_id, fresh_start)

        async with session_scope() as session:
            orphaned = await fail_orphan_runs(session)

        assert run_id not in orphaned
        async with session_scope() as session:
            run = await get_pipeline_run(session, run_id)
        assert run is not None
        assert run.status == RunStatus.RUNNING

    async def test_leaves_completed_runs_untouched(
        self,
        clean_test_runs: None,
    ) -> None:
        """A long-ago run that already transitioned out of `running`
        must never be touched, no matter how old its started_at is.
        """
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        long_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
        completed = PipelineRun(
            run_id=run_id,
            run_type=RunType.MANUAL,
            started_at=long_ago,
            completed_at=long_ago + datetime.timedelta(minutes=5),
            status=RunStatus.COMPLETED,
        )
        async with session_scope() as session:
            await upsert_pipeline_run(session, completed)

        async with session_scope() as session:
            orphaned = await fail_orphan_runs(session)

        assert run_id not in orphaned
        async with session_scope() as session:
            run = await get_pipeline_run(session, run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
