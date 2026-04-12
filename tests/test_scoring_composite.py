"""Tests for composite score computation."""

from __future__ import annotations

import pytest

from hornet.domain.scoring import DimensionScore, ScoringConfig
from hornet.scoring.composite import compute_composite


def _config(**overrides: object) -> ScoringConfig:
    defaults: dict[str, object] = {
        "dimension_weights": {
            "growth_momentum": 0.25,
            "external_balance": 0.25,
            "monetary_stance": 0.25,
            "risk_sentiment": 0.25,
        },
    }
    defaults.update(overrides)
    return ScoringConfig(**defaults)


def _ds(dimension: str, value: float | None) -> DimensionScore:
    return DimensionScore(
        dimension=dimension,
        value=value,
        n_series_used=5 if value is not None else 0,
        n_series_stale=0,
        n_concepts=3 if value is not None else 0,
    )


class TestCompositeRenormalize:
    """Default renormalize strategy."""

    def test_all_four_dimensions(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", -1.0),
            "external_balance": _ds("external_balance", 0.5),
            "monetary_stance": _ds("monetary_stance", 1.0),
            "risk_sentiment": _ds("risk_sentiment", -0.5),
        }
        config = _config()
        composite = compute_composite(scores, config)

        assert composite is not None
        # With equal weights: renormalised = (-1.0 + 0.5 + 1.0 + -0.5) / 4 = 0.0
        # coverage = 4/4 = 1.0, sqrt(1.0) = 1.0
        # composite = 0.0 * 1.0 = 0.0
        assert composite == 0.0

    def test_two_dimensions_present(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", -2.0),
            "external_balance": _ds("external_balance", None),
            "monetary_stance": _ds("monetary_stance", None),
            "risk_sentiment": _ds("risk_sentiment", 1.0),
        }
        config = _config()
        composite = compute_composite(scores, config)

        assert composite is not None
        # renormalised = (-2.0 * 0.25 + 1.0 * 0.25) / (0.25 + 0.25) = -0.5
        # coverage = 2/4 = 0.5, sqrt(0.5) = 0.707
        # composite = -0.5 * 0.707 = -0.354
        assert composite == pytest.approx(-0.35, abs=0.01)

    def test_below_min_dimensions_returns_none(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", -2.0),
            "external_balance": _ds("external_balance", None),
            "monetary_stance": _ds("monetary_stance", None),
            "risk_sentiment": _ds("risk_sentiment", None),
        }
        config = _config()
        composite = compute_composite(scores, config)
        assert composite is None

    def test_all_none_returns_none(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", None),
            "external_balance": _ds("external_balance", None),
            "monetary_stance": _ds("monetary_stance", None),
            "risk_sentiment": _ds("risk_sentiment", None),
        }
        config = _config()
        composite = compute_composite(scores, config)
        assert composite is None

    def test_clamped_to_scale(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", 3.0),
            "external_balance": _ds("external_balance", 3.0),
            "monetary_stance": _ds("monetary_stance", 3.0),
            "risk_sentiment": _ds("risk_sentiment", 3.0),
        }
        config = _config()
        composite = compute_composite(scores, config)
        assert composite is not None
        assert composite <= 3.0

    def test_coverage_confidence_linear(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", -2.0),
            "external_balance": _ds("external_balance", None),
            "monetary_stance": _ds("monetary_stance", None),
            "risk_sentiment": _ds("risk_sentiment", 1.0),
        }
        config = _config(coverage_confidence="linear")
        composite = compute_composite(scores, config)

        assert composite is not None
        # renormalised = -0.5, coverage=0.5, linear -> confidence=0.5
        # composite = -0.5 * 0.5 = -0.25
        assert composite == pytest.approx(-0.25, abs=0.01)

    def test_coverage_confidence_none(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", -2.0),
            "external_balance": _ds("external_balance", None),
            "monetary_stance": _ds("monetary_stance", None),
            "risk_sentiment": _ds("risk_sentiment", 1.0),
        }
        config = _config(coverage_confidence="none")
        composite = compute_composite(scores, config)

        assert composite is not None
        # renormalised = -0.5, confidence=1.0
        # composite = -0.5
        assert composite == pytest.approx(-0.50, abs=0.01)

    def test_unequal_weights(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", 2.0),
            "external_balance": _ds("external_balance", -1.0),
            "monetary_stance": _ds("monetary_stance", 0.0),
            "risk_sentiment": _ds("risk_sentiment", 0.0),
        }
        config = _config(
            dimension_weights={
                "growth_momentum": 0.4,
                "external_balance": 0.2,
                "monetary_stance": 0.2,
                "risk_sentiment": 0.2,
            }
        )
        composite = compute_composite(scores, config)

        assert composite is not None
        # weighted = (2.0*0.4 + -1.0*0.2 + 0*0.2 + 0*0.2) / 1.0 = 0.6
        # coverage=1.0, sqrt(1.0)=1.0 -> composite=0.6
        assert composite == pytest.approx(0.6, abs=0.01)


class TestCompositeZeroPad:
    """Legacy zero_pad strategy."""

    def test_missing_dims_treated_as_zero(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", -1.4),
            "external_balance": _ds("external_balance", None),
            "monetary_stance": _ds("monetary_stance", None),
            "risk_sentiment": _ds("risk_sentiment", None),
        }
        config = _config(composite_strategy="zero_pad")
        composite = compute_composite(scores, config)

        assert composite is not None
        # weighted_sum = -1.4 * 0.25 + 0 + 0 + 0 = -0.35
        # total_weight = 1.0
        # composite = -0.35
        assert composite == pytest.approx(-0.35, abs=0.01)

    def test_all_present(self) -> None:
        scores = {
            "growth_momentum": _ds("growth_momentum", 1.0),
            "external_balance": _ds("external_balance", 1.0),
            "monetary_stance": _ds("monetary_stance", 1.0),
            "risk_sentiment": _ds("risk_sentiment", 1.0),
        }
        config = _config(composite_strategy="zero_pad")
        composite = compute_composite(scores, config)

        assert composite is not None
        assert composite == pytest.approx(1.0, abs=0.01)
