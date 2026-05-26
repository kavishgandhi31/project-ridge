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
