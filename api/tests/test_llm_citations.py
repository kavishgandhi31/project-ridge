"""Tests for citation extraction, resolution, and grounding validation."""

from __future__ import annotations

import datetime

import pytest

from ridge.domain.llm import Citation, LLMResponse, TaskType
from ridge.llm.citations import (
    compute_grounding_score,
    detect_ungrounded_claims,
    extract_citation_refs,
    resolve_citations,
    validate_response,
)


def _citation(ref: int, indicator: str = "CPI_YOY", value: float = 33.2) -> Citation:
    return Citation(
        ref_number=ref,
        country_iso3="NGA",
        indicator_code=indicator,
        source_id="worldbank",
        date=datetime.date(2026, 3, 1),
        value=value,
        vintage=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        display_label=f"{indicator} (NGA, 2026-03): {value}",
    )


# -- extract_citation_refs --


def test_extract_refs_basic() -> None:
    text = "Inflation is at 33.2% [1] and GDP grew 3.1% [2]."
    refs = extract_citation_refs(text)
    assert refs == (1, 2)


def test_extract_refs_duplicates_removed() -> None:
    text = "CPI [1] is high [1] but GDP [2] is ok."
    refs = extract_citation_refs(text)
    assert refs == (1, 2)


def test_extract_refs_none_present() -> None:
    text = "No citations here."
    refs = extract_citation_refs(text)
    assert refs == ()


def test_extract_refs_multi_digit() -> None:
    text = "Reference [12] and [3]."
    refs = extract_citation_refs(text)
    assert refs == (12, 3)


# -- resolve_citations --


def test_resolve_all_found() -> None:
    table = {1: _citation(1), 2: _citation(2, "GDP_GROWTH", 3.1)}
    resolved, unresolved = resolve_citations((1, 2), table)
    assert len(resolved) == 2
    assert unresolved == ()


def test_resolve_with_unresolved() -> None:
    table = {1: _citation(1)}
    resolved, unresolved = resolve_citations((1, 5, 99), table)
    assert len(resolved) == 1
    assert unresolved == (5, 99)


# -- detect_ungrounded_claims --


def test_detect_no_ungrounded() -> None:
    text = "Inflation is at 33.2% [1]."
    claims = detect_ungrounded_claims(text, frozenset({1}))
    assert claims == ()


def test_detect_ungrounded_number() -> None:
    text = "Inflation is at 33.2% and GDP grew 3.1%."
    claims = detect_ungrounded_claims(text, frozenset())
    assert len(claims) >= 1
    # Should find at least 33.2% or 3.1%
    claim_strs = " ".join(claims)
    assert "33.2%" in claim_strs or "3.1%" in claim_strs


def test_detect_skips_years() -> None:
    text = "In 2026, the economy shifted."
    claims = detect_ungrounded_claims(text, frozenset())
    assert claims == ()


def test_detect_skips_small_integers() -> None:
    text = "There are 4 dimensions and 2 risks."
    claims = detect_ungrounded_claims(text, frozenset())
    assert claims == ()


def test_detect_signed_numbers() -> None:
    text = "Score is -2.1 with no citation."
    claims = detect_ungrounded_claims(text, frozenset())
    # Should detect -2.1
    assert any("2.1" in c for c in claims)


def test_detect_grounded_nearby_citation() -> None:
    text = "Inflation at 33.2% [1] is concerning."
    claims = detect_ungrounded_claims(text, frozenset({1}))
    # 33.2% has [1] nearby, should be grounded
    assert claims == ()


# -- compute_grounding_score --


def test_grounding_perfect() -> None:
    assert compute_grounding_score(5, 0) == 1.0


def test_grounding_zero() -> None:
    assert compute_grounding_score(0, 5) == 0.0


def test_grounding_mixed() -> None:
    score = compute_grounding_score(3, 1)
    assert score == pytest.approx(0.75)


def test_grounding_vacuous() -> None:
    # No claims at all -> vacuously grounded
    assert compute_grounding_score(0, 0) == 1.0


# -- validate_response --


def test_validate_response_well_grounded() -> None:
    citations = (_citation(1), _citation(2, "GDP_GROWTH", 3.1))
    llm_resp = LLMResponse(
        content="Inflation is at 33.2% [1] and GDP grew 3.1% [2].",
        provider_id="test",
        model_id="test",
        tokens_in=100,
        tokens_out=50,
        latency_ms=500,
        generated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
    )

    grounded = validate_response(
        llm_resp,
        citations,
        task_type=TaskType.COUNTRY_NARRATIVE,
        template_name="country_narrative",
        country_iso3="NGA",
        run_id="test-run",
    )

    assert grounded.grounding_score > 0.5
    assert len(grounded.citations_used) == 2
    assert grounded.provider_id == "test"
    assert grounded.country_iso3 == "NGA"
    assert grounded.run_id == "test-run"


def test_validate_response_no_citations() -> None:
    citations = (_citation(1),)
    llm_resp = LLMResponse(
        content="The economy is bad with inflation at 50%.",
        provider_id="test",
        model_id="test",
        tokens_in=100,
        tokens_out=50,
        latency_ms=500,
        generated_at=datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC),
    )

    grounded = validate_response(
        llm_resp,
        citations,
        task_type=TaskType.COUNTRY_NARRATIVE,
        template_name="country_narrative",
        country_iso3="NGA",
        run_id="test-run",
    )

    assert grounded.grounding_score < 1.0
    assert len(grounded.citations_used) == 0
    assert len(grounded.ungrounded_claims) >= 1
