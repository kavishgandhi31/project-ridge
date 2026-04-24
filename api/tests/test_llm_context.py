"""Tests for the grounded context builder."""

from __future__ import annotations

import datetime

from ridge.domain.observation import Observation
from ridge.domain.scoring import DimensionScore, ScoreResult
from ridge.llm.context import (
    build_grounded_context,
    build_observation_context,
    build_score_summary,
)


def _obs(
    indicator: str,
    value: float,
    date: datetime.date | None = None,
    country: str = "NGA",
    source: str = "worldbank",
) -> Observation:
    """Helper to build a test Observation."""
    return Observation(
        country_iso3=country,
        indicator_code=indicator,
        source_id=source,
        date=date or datetime.date(2026, 3, 1),
        value=value,
        frequency="monthly",
        vintage=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        ingested_at=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
    )


def test_build_observation_context_basic() -> None:
    """Single indicator, single observation."""
    obs = [_obs("CPI_YOY", 33.2)]
    block, citations, included, truncated = build_observation_context(
        obs,
        token_budget=5000,
    )
    assert "[1]" in block
    assert "CPI_YOY" in block
    assert "33.20%" in block
    assert len(citations) == 1
    assert citations[0].ref_number == 1
    assert citations[0].value == 33.2
    assert included == ("CPI_YOY",)
    assert truncated == ()


def test_build_observation_context_multiple_indicators() -> None:
    """Multiple indicators get sequential ref numbers."""
    obs = [
        _obs("CPI_YOY", 33.2),
        _obs("GDP_GROWTH", 3.1),
    ]
    block, citations, _included, _truncated = build_observation_context(
        obs,
        token_budget=5000,
    )
    assert "[1]" in block
    assert "[2]" in block
    assert len(citations) == 2
    ref_numbers = {c.ref_number for c in citations}
    assert ref_numbers == {1, 2}


def test_build_observation_context_max_points() -> None:
    """Respects max_points_per_indicator."""
    obs = [
        _obs("CPI_YOY", 33.2, datetime.date(2026, 3, 1)),
        _obs("CPI_YOY", 30.1, datetime.date(2026, 2, 1)),
        _obs("CPI_YOY", 28.5, datetime.date(2026, 1, 1)),
        _obs("CPI_YOY", 25.0, datetime.date(2025, 12, 1)),
    ]
    _, citations, _, _ = build_observation_context(
        obs,
        token_budget=5000,
        max_points_per_indicator=2,
    )
    # Should only keep 2 most recent
    assert len(citations) == 2
    values = {c.value for c in citations}
    assert values == {33.2, 30.1}


def test_build_observation_context_token_truncation() -> None:
    """Truncates indicators when token budget is exhausted."""
    obs = [
        _obs("AAA_FIRST", 1.0),
        _obs("BBB_SECOND", 2.0),
        _obs("CCC_THIRD", 3.0),
    ]
    # Very tight budget -- should only fit 1-2 indicators
    _, _citations, included, truncated = build_observation_context(
        obs,
        token_budget=40,  # ~2 citation lines worth
    )
    assert len(included) >= 1
    assert len(truncated) >= 1
    assert len(included) + len(truncated) == 3


def test_build_observation_context_empty() -> None:
    """Empty observations produce fallback message."""
    block, citations, _included, _truncated = build_observation_context(
        [],
        token_budget=5000,
    )
    assert "No observation data" in block
    assert len(citations) == 0


def test_build_score_summary() -> None:
    """Score summary formats dimension scores."""
    score = ScoreResult(
        country_iso3="NGA",
        run_id="test-run",
        scored_at=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        dimensions={
            "growth_momentum": DimensionScore(
                dimension="growth_momentum", value=-1.5, n_series_used=3, n_concepts=2
            ),
            "external_balance": DimensionScore(
                dimension="external_balance", value=-0.8, n_series_used=2, n_concepts=2
            ),
        },
        composite=-1.2,
        coverage_fraction=0.5,
    )
    text = build_score_summary(score)
    assert "-1.20" in text
    assert "Growth Momentum" in text
    assert "-1.50" in text
    assert "50%" in text


def test_build_grounded_context_full() -> None:
    """Full context build with score and observations."""
    obs = [_obs("CPI_YOY", 33.2), _obs("GDP_GROWTH", 3.1)]
    score = ScoreResult(
        country_iso3="NGA",
        run_id="test-run",
        scored_at=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
        dimensions={},
        composite=-1.5,
        coverage_fraction=0.75,
    )

    ctx = build_grounded_context(
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        observations=obs,
        score_result=score,
        token_budget=5000,
    )

    assert ctx.country_iso3 == "NGA"
    assert ctx.score_result_included is True
    assert len(ctx.citations) == 2
    assert "CURRENT SCORES" in ctx.context_block
    assert "MACRO DATA" in ctx.context_block
    assert "[1]" in ctx.context_block
    assert ctx.token_estimate > 0
