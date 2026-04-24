"""Eval metrics for grounded LLM output.

Given a GroundedResponse and an EvalQuestion, compute all quality
metrics and produce an EvalResult with a pass/fail verdict.
"""

from __future__ import annotations

import datetime
import re

import structlog

from ridge.domain.llm import EvalQuestion, EvalResult, GroundedResponse

logger = structlog.get_logger(__name__)

# Default minimum grounding score to pass
DEFAULT_MIN_GROUNDING = 0.8


def evaluate_response(
    response: GroundedResponse,
    question: EvalQuestion,
    *,
    min_grounding: float = DEFAULT_MIN_GROUNDING,
) -> EvalResult:
    """Score a grounded response against an eval question.

    Checks:
    1. Grounding score >= threshold.
    2. Ungrounded claims <= max_ungrounded.
    3. No forbidden patterns match.
    4. Citations used >= min_citations.
    5. All required indicators are cited.

    Returns an EvalResult with metrics and pass/fail verdict.
    """
    failures: list[str] = []

    # 1. Grounding score
    if response.grounding_score < min_grounding:
        failures.append(
            f"Grounding score {response.grounding_score:.2f} " f"< threshold {min_grounding:.2f}"
        )

    # 2. Ungrounded claims
    n_ungrounded = len(response.ungrounded_claims)
    if n_ungrounded > question.max_ungrounded:
        failures.append(
            f"Ungrounded claims: {n_ungrounded} " f"> max allowed {question.max_ungrounded}"
        )

    # 3. Forbidden patterns
    n_forbidden = 0
    for pattern in question.forbidden_patterns:
        if re.search(pattern, response.content):
            n_forbidden += 1
            failures.append(f"Forbidden pattern matched: {pattern!r}")

    # 4. Citation count
    n_citations = len(response.citations_used)
    if n_citations < question.min_citations:
        failures.append(
            f"Citations used: {n_citations} " f"< minimum required {question.min_citations}"
        )

    # 5. Required indicators
    cited_indicators = frozenset(c.indicator_code for c in response.citations_used)
    required = frozenset(question.required_indicators)
    missing = required - cited_indicators
    completeness = (len(required) - len(missing)) / len(required) if required else 1.0
    if missing:
        failures.append(f"Missing required indicators: {', '.join(sorted(missing))}")

    passed = len(failures) == 0

    return EvalResult(
        question_id=question.question_id,
        grounding_score=response.grounding_score,
        citation_completeness=completeness,
        n_citations_used=n_citations,
        n_ungrounded=n_ungrounded,
        n_forbidden_matches=n_forbidden,
        passed=passed,
        failure_reasons=tuple(failures),
        evaluated_at=datetime.datetime.now(datetime.UTC),
        provider_id=response.provider_id,
        model_id=response.model_id,
        latency_ms=response.latency_ms,
    )
