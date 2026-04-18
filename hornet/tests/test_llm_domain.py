"""Tests for LLM domain types -- validation, immutability, serialization."""

from __future__ import annotations

import datetime

import pytest

from hornet.domain.llm import (
    Citation,
    EvalQuestion,
    EvalResult,
    GroundedContext,
    GroundedResponse,
    LLMRequest,
    LLMResponse,
    TaskType,
)

# -- TaskType --


def test_task_type_values() -> None:
    assert TaskType.COUNTRY_NARRATIVE.value == "country_narrative"
    assert TaskType.ALERT_RATIONALE.value == "alert_rationale"
    assert TaskType.INTERACTIVE_QUERY.value == "interactive_query"
    assert TaskType.CLASSIFICATION.value == "classification"


# -- Citation --


def _sample_citation(ref: int = 1) -> Citation:
    return Citation(
        ref_number=ref,
        country_iso3="NGA",
        indicator_code="CPI_YOY",
        source_id="worldbank",
        date=datetime.date(2026, 3, 1),
        value=33.2,
        vintage=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        display_label="CPI_YOY (NGA, 2026-03): 33.20%",
    )


def test_citation_frozen() -> None:
    c = _sample_citation()
    with pytest.raises((TypeError, ValueError)):
        c.ref_number = 99  # type: ignore[misc]


def test_citation_ref_must_be_positive() -> None:
    with pytest.raises((TypeError, ValueError)):
        _sample_citation(ref=0)


def test_citation_iso3_validation() -> None:
    with pytest.raises((TypeError, ValueError)):
        Citation(
            ref_number=1,
            country_iso3="NG",  # too short
            indicator_code="CPI_YOY",
            source_id="worldbank",
            date=datetime.date(2026, 3, 1),
            value=33.2,
            vintage=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
            display_label="test",
        )


# -- LLMRequest --


def test_llm_request_defaults() -> None:
    req = LLMRequest(
        system_prompt="You are a macro analyst.",
        user_prompt="Analyze Nigeria.",
        task_type=TaskType.COUNTRY_NARRATIVE,
    )
    assert req.max_tokens == 4000
    assert req.temperature == 0.3
    assert req.response_format == "json"
    assert req.metadata == {}


def test_llm_request_temperature_bounds() -> None:
    with pytest.raises((TypeError, ValueError)):
        LLMRequest(
            system_prompt="x",
            user_prompt="y",
            task_type=TaskType.COUNTRY_NARRATIVE,
            temperature=3.0,  # > 2.0
        )


# -- LLMResponse --


def _sample_response() -> LLMResponse:
    return LLMResponse(
        content="Nigeria faces headwinds [1] [2]",
        provider_id="ollama",
        model_id="qwen3:14b",
        tokens_in=500,
        tokens_out=200,
        latency_ms=1500,
        finish_reason="stop",
        generated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
    )


def test_llm_response_frozen() -> None:
    r = _sample_response()
    with pytest.raises((TypeError, ValueError)):
        r.content = "new"  # type: ignore[misc]


# -- GroundedContext --


def test_grounded_context_construction() -> None:
    ctx = GroundedContext(
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        context_block="[1] CPI_YOY (NGA, 2026-03): 33.20%",
        citations=(_sample_citation(),),
        token_estimate=20,
        indicators_included=("CPI_YOY",),
        indicators_truncated=(),
    )
    assert ctx.score_result_included is False
    assert ctx.events_included == 0


# -- GroundedResponse --


def test_grounded_response_score_bounds() -> None:
    with pytest.raises((TypeError, ValueError)):
        GroundedResponse(
            content="x",
            grounding_score=1.5,  # > 1.0
            provider_id="test",
            model_id="test",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            task_type=TaskType.COUNTRY_NARRATIVE,
            template_name="test",
            country_iso3="NGA",
            run_id="abc",
            generated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
        )


# -- EvalQuestion --


def test_eval_question_defaults() -> None:
    q = EvalQuestion(
        question_id="test_01",
        template_name="country_narrative",
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        description="Test question",
    )
    assert q.min_citations == 1
    assert q.max_ungrounded == 0
    assert q.required_indicators == ()
    assert q.forbidden_patterns == ()


# -- EvalResult --


def test_eval_result_construction() -> None:
    r = EvalResult(
        question_id="test_01",
        grounding_score=0.9,
        citation_completeness=1.0,
        n_citations_used=5,
        n_ungrounded=1,
        passed=True,
        evaluated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
        provider_id="ollama",
        model_id="qwen3:14b",
        latency_ms=1500,
    )
    assert r.failure_reasons == ()
    assert r.n_forbidden_matches == 0
