"""Tests for the eval harness and metrics."""

from __future__ import annotations

import datetime

from hornet.domain.llm import (
    Citation,
    EvalQuestion,
    GroundedResponse,
    TaskType,
)
from hornet.llm.eval.harness import (
    load_eval_questions,
    offline_eval,
    summarize_results,
)
from hornet.llm.eval.metrics import evaluate_response


def _citation(ref: int, indicator: str = "CPI_YOY") -> Citation:
    return Citation(
        ref_number=ref,
        country_iso3="NGA",
        indicator_code=indicator,
        source_id="worldbank",
        date=datetime.date(2026, 3, 1),
        value=33.2,
        vintage=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        display_label=f"{indicator} (NGA, 2026-03): 33.20%",
    )


def _grounded_response(
    *,
    grounding_score: float = 0.9,
    citations: tuple[Citation, ...] = (),
    ungrounded: tuple[str, ...] = (),
) -> GroundedResponse:
    return GroundedResponse(
        content="Test response with data [1] [2]",
        citations_used=citations,
        citations_available=citations,
        ungrounded_claims=ungrounded,
        grounding_score=grounding_score,
        provider_id="test",
        model_id="test-model",
        tokens_in=100,
        tokens_out=50,
        latency_ms=500,
        task_type=TaskType.COUNTRY_NARRATIVE,
        template_name="country_narrative",
        country_iso3="NGA",
        run_id="test-run",
        generated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
    )


# -- load_eval_questions --


def test_load_eval_questions_from_default() -> None:
    """Packaged questions.yaml loads without errors."""
    questions = load_eval_questions()
    assert len(questions) >= 10
    # All questions have valid fields
    for q in questions:
        assert q.question_id
        assert q.template_name in ("country_narrative", "alert_rationale")
        assert len(q.country_iso3) == 3


def test_load_eval_questions_from_custom_yaml() -> None:
    yaml_text = """
questions:
  - question_id: "test_01"
    template_name: "country_narrative"
    country_iso3: "NGA"
    reference_date: "2026-04-01"
    description: "Test question"
    min_citations: 2
    max_ungrounded: 1
"""
    questions = load_eval_questions(yaml_text)
    assert len(questions) == 1
    assert questions[0].question_id == "test_01"
    assert questions[0].min_citations == 2


# -- evaluate_response --


def test_evaluate_passing() -> None:
    question = EvalQuestion(
        question_id="test",
        template_name="country_narrative",
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        description="Test",
        min_citations=1,
        max_ungrounded=1,
        required_indicators=("CPI_YOY",),
    )
    response = _grounded_response(
        grounding_score=0.9,
        citations=(_citation(1, "CPI_YOY"), _citation(2, "GDP_GROWTH")),
    )
    result = evaluate_response(response, question)
    assert result.passed is True
    assert result.failure_reasons == ()


def test_evaluate_failing_low_grounding() -> None:
    question = EvalQuestion(
        question_id="test",
        template_name="country_narrative",
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        description="Test",
    )
    response = _grounded_response(grounding_score=0.3)
    result = evaluate_response(response, question, min_grounding=0.8)
    assert result.passed is False
    assert any("Grounding score" in r for r in result.failure_reasons)


def test_evaluate_failing_missing_indicator() -> None:
    question = EvalQuestion(
        question_id="test",
        template_name="country_narrative",
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        description="Test",
        required_indicators=("POLICY_RATE",),
    )
    response = _grounded_response(
        citations=(_citation(1, "CPI_YOY"),),
    )
    result = evaluate_response(response, question)
    assert result.passed is False
    assert result.citation_completeness == 0.0


def test_evaluate_forbidden_pattern() -> None:
    question = EvalQuestion(
        question_id="test",
        template_name="country_narrative",
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        description="Test",
        forbidden_patterns=("bad_pattern",),
        max_ungrounded=10,
    )
    response = GroundedResponse(
        content="This has bad_pattern in it",
        grounding_score=1.0,
        provider_id="test",
        model_id="test",
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        task_type=TaskType.COUNTRY_NARRATIVE,
        template_name="country_narrative",
        country_iso3="NGA",
        run_id="test",
        generated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
    )
    result = evaluate_response(response, question)
    assert result.passed is False
    assert result.n_forbidden_matches == 1


# -- offline_eval --


def test_offline_eval_runs() -> None:
    questions = [
        EvalQuestion(
            question_id="q1",
            template_name="country_narrative",
            country_iso3="NGA",
            reference_date=datetime.date(2026, 4, 1),
            description="Test 1",
            max_ungrounded=5,
        ),
        EvalQuestion(
            question_id="q2",
            template_name="country_narrative",
            country_iso3="TUR",
            reference_date=datetime.date(2026, 4, 1),
            description="Test 2",
            max_ungrounded=5,
        ),
    ]
    responses = {
        "q1": _grounded_response(grounding_score=0.9, citations=(_citation(1),)),
    }
    results = offline_eval(questions, responses)
    assert len(results) == 1  # q2 skipped (no response)
    assert results[0].question_id == "q1"


# -- summarize_results --


def test_summarize_results() -> None:
    from hornet.domain.llm import EvalResult

    results = [
        EvalResult(
            question_id="q1",
            grounding_score=0.9,
            citation_completeness=1.0,
            n_citations_used=5,
            n_ungrounded=1,
            passed=True,
            evaluated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
            provider_id="test",
            model_id="test",
            latency_ms=500,
        ),
        EvalResult(
            question_id="q2",
            grounding_score=0.5,
            citation_completeness=0.5,
            n_citations_used=2,
            n_ungrounded=3,
            passed=False,
            evaluated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
            provider_id="test",
            model_id="test",
            latency_ms=600,
        ),
    ]
    summary = summarize_results(results)
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["avg_grounding_score"] == 0.7
