"""Tests for the llm_response repository functions.

The true-upsert test is the load-bearing one -- it would have caught
the original duplicate-row bug. The others cover idempotency and
round-trip.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from ridge.db.models.llm_response import LLMResponseRow
from ridge.db.repos.llm_response import upsert_llm_response
from ridge.db.session import session_scope
from ridge.domain.llm import Citation, GroundedResponse, TaskType

_TEST_RUN_ID_PREFIX = "test-llm-repo-"


@pytest.fixture
async def clean_test_responses() -> AsyncIterator[None]:
    """Wipe test-created llm_response rows before and after each test."""

    async def _wipe() -> None:
        async with session_scope() as session:
            await session.execute(
                delete(LLMResponseRow).where(LLMResponseRow.run_id.like(f"{_TEST_RUN_ID_PREFIX}%"))
            )

    await _wipe()
    yield
    await _wipe()


def _make_response(
    *,
    run_id: str,
    country_iso3: str = "NGA",
    template_name: str = "country_narrative",
    content: str = "Nigeria's inflation is elevated at [1].",
    grounding_score: float = 1.0,
) -> GroundedResponse:
    """Build a minimal GroundedResponse with one citation."""
    citation = Citation(
        ref_number=1,
        country_iso3="NGA",
        indicator_code="CPI_YOY",
        source_id="fred",
        date=datetime.date(2026, 3, 1),
        value=33.2,
        vintage=datetime.datetime(2026, 3, 15, tzinfo=datetime.UTC),
        display_label="CPI_YOY (NGA, 2026-03): 33.20%",
    )
    return GroundedResponse(
        content=content,
        citations_used=(citation,),
        citations_available=(citation,),
        ungrounded_claims=(),
        grounding_score=grounding_score,
        provider_id="ollama",
        model_id="qwen3:14b",
        tokens_in=100,
        tokens_out=50,
        latency_ms=2000,
        task_type=TaskType.COUNTRY_NARRATIVE,
        template_name=template_name,
        country_iso3=country_iso3,
        run_id=run_id,
        generated_at=datetime.datetime.now(datetime.UTC),
    )


async def _fetch_rows(run_id: str) -> list[LLMResponseRow]:
    async with session_scope() as session:
        result = await session.execute(
            select(LLMResponseRow).where(LLMResponseRow.run_id == run_id)
        )
        return list(result.scalars().all())


class TestFromDomain:
    def test_is_deterministic_for_same_natural_key(self) -> None:
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        response = _make_response(run_id=run_id)

        row_a = LLMResponseRow.from_domain(response)
        row_b = LLMResponseRow.from_domain(response)

        assert row_a.response_id == row_b.response_id

    def test_differs_across_natural_keys(self) -> None:
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"

        nga = _make_response(run_id=run_id, country_iso3="NGA")
        tur = _make_response(run_id=run_id, country_iso3="TUR")
        narrative = _make_response(run_id=run_id, template_name="country_narrative")
        rationale = _make_response(run_id=run_id, template_name="alert_rationale")

        ids = {
            LLMResponseRow.from_domain(nga).response_id,
            LLMResponseRow.from_domain(tur).response_id,
            LLMResponseRow.from_domain(narrative).response_id,
            LLMResponseRow.from_domain(rationale).response_id,
        }
        # nga and narrative share the same natural key, so 3 distinct ids.
        assert len(ids) == 3


class TestToDomain:
    async def test_round_trips_a_stored_response(
        self,
        clean_test_responses: None,
    ) -> None:
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        original = _make_response(run_id=run_id)

        async with session_scope() as session:
            await upsert_llm_response(session, original)

        rows = await _fetch_rows(run_id)
        assert len(rows) == 1

        reconstructed = rows[0].to_domain()
        assert reconstructed.content == original.content
        assert reconstructed.citations_used == original.citations_used
        assert reconstructed.grounding_score == original.grounding_score
        assert reconstructed.provider_id == original.provider_id
        assert reconstructed.model_id == original.model_id
        assert reconstructed.task_type == original.task_type
        assert reconstructed.template_name == original.template_name
        assert reconstructed.country_iso3 == original.country_iso3
        assert reconstructed.run_id == original.run_id
        # Documented lossiness: citations_available collapses to citations_used.
        assert reconstructed.citations_available == reconstructed.citations_used


class TestUpsertOverwrites:
    async def test_re_persist_updates_in_place(
        self,
        clean_test_responses: None,
    ) -> None:
        """The original bug: re-persisting the same generation produced a
        duplicate row instead of updating. The deterministic-id fix makes
        ON CONFLICT DO UPDATE actually fire.
        """
        run_id = f"{_TEST_RUN_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        first = _make_response(run_id=run_id, content="first version", grounding_score=0.8)
        second = _make_response(run_id=run_id, content="second version", grounding_score=0.95)

        async with session_scope() as session:
            await upsert_llm_response(session, first)
            await upsert_llm_response(session, second)

        rows = await _fetch_rows(run_id)
        assert len(rows) == 1
        assert rows[0].content == "second version"
        assert rows[0].grounding_score == 0.95
