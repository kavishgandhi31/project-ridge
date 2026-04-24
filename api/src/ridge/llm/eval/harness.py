"""Eval harness -- runs regression questions and collects results.

Two modes:
    1. offline_eval: Scores pre-recorded responses against questions.
       No model needed -- for CI and development.
    2. live_eval: Builds context, calls a real model via the router,
       scores the response. For nightly eval.

Questions are loaded from YAML (eval/questions.yaml).
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import resources
from typing import Any, cast

import structlog
import yaml

from ridge.domain.llm import EvalQuestion, EvalResult, GroundedResponse
from ridge.llm.eval.metrics import evaluate_response

logger = structlog.get_logger(__name__)

_EVAL_PACKAGE = "ridge.llm.eval"
_QUESTIONS_FILENAME = "questions.yaml"


def load_eval_questions(yaml_text: str | None = None) -> list[EvalQuestion]:
    """Load eval questions from YAML.

    When yaml_text is None, loads the packaged default. Tests pass
    explicit YAML strings.
    """
    if yaml_text is None:
        ref = resources.files(_EVAL_PACKAGE) / _QUESTIONS_FILENAME
        text = ref.read_text(encoding="utf-8")
    else:
        text = yaml_text

    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("questions.yaml must deserialize to a mapping")

    entries = raw.get("questions")
    if not isinstance(entries, list):
        raise ValueError("questions.yaml must have a top-level 'questions' list")

    questions: list[EvalQuestion] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Each question must be a mapping, got: {entry!r}")
        questions.append(EvalQuestion(**cast(dict[str, Any], entry)))
    return questions


def offline_eval(
    questions: Sequence[EvalQuestion],
    responses: dict[str, GroundedResponse],
    *,
    min_grounding: float = 0.8,
) -> list[EvalResult]:
    """Score pre-recorded responses against eval questions.

    Parameters
    ----------
    questions:
        The eval question set.
    responses:
        Pre-recorded GroundedResponses keyed by question_id.
    min_grounding:
        Minimum grounding score threshold for pass.

    Returns
    -------
    list[EvalResult]
        One result per question that has a matching response.
        Questions without responses are skipped with a warning.
    """
    results: list[EvalResult] = []

    for question in questions:
        response = responses.get(question.question_id)
        if response is None:
            logger.warning(
                "eval.offline.missing_response",
                question_id=question.question_id,
            )
            continue

        result = evaluate_response(response, question, min_grounding=min_grounding)
        results.append(result)

        log_fn = logger.info if result.passed else logger.warning
        log_fn(
            "eval.offline.result",
            question_id=result.question_id,
            passed=result.passed,
            grounding_score=f"{result.grounding_score:.2f}",
            n_citations=result.n_citations_used,
            n_ungrounded=result.n_ungrounded,
        )

    n_passed = sum(1 for r in results if r.passed)
    logger.info(
        "eval.offline.summary",
        total=len(results),
        passed=n_passed,
        failed=len(results) - n_passed,
        skipped=len(questions) - len(results),
    )

    return results


def summarize_results(results: Sequence[EvalResult]) -> dict[str, Any]:
    """Compute aggregate metrics from a list of eval results.

    Returns a dict suitable for structured logging or dashboard display.
    """
    if not results:
        return {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0}

    n_passed = sum(1 for r in results if r.passed)
    avg_grounding = sum(r.grounding_score for r in results) / len(results)
    avg_completeness = sum(r.citation_completeness for r in results) / len(results)
    total_ungrounded = sum(r.n_ungrounded for r in results)

    return {
        "total": len(results),
        "passed": n_passed,
        "failed": len(results) - n_passed,
        "pass_rate": n_passed / len(results),
        "avg_grounding_score": round(avg_grounding, 3),
        "avg_citation_completeness": round(avg_completeness, 3),
        "total_ungrounded_claims": total_ungrounded,
    }
