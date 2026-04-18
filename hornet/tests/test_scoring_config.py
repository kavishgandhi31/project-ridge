"""Tests for scoring configuration domain types and YAML loading."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hornet.domain.scoring import (
    ALL_DIMENSIONS,
    DimensionScore,
    NewsHeat,
    ScoreResult,
    ScoringConfig,
)
from hornet.seeds.loader import load_scoring_config_from_yaml


class TestScoringConfig:
    """ScoringConfig domain type validation."""

    def test_valid_config(self) -> None:
        config = ScoringConfig(
            dimension_weights={
                "growth_momentum": 0.25,
                "external_balance": 0.25,
                "monetary_stance": 0.25,
                "risk_sentiment": 0.25,
            },
        )
        assert config.scale_min == -3.0
        assert config.scale_max == 3.0
        assert config.zscore_method == "ewm"
        assert config.composite_strategy == "renormalize"
        assert config.coverage_confidence == "sqrt"
        assert config.min_dimensions_for_composite == 2
        assert config.min_observations == 12
        assert config.momentum_window == 30
        assert config.news_heat_sigma == 2.0

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match=r"must sum to 1\.0"):
            ScoringConfig(
                dimension_weights={
                    "growth_momentum": 0.5,
                    "external_balance": 0.5,
                    "monetary_stance": 0.5,
                    "risk_sentiment": 0.5,
                },
            )

    def test_weights_sum_validation_tolerance(self) -> None:
        """Floating point rounding should not cause false rejections."""
        config = ScoringConfig(
            dimension_weights={
                "growth_momentum": 0.1,
                "external_balance": 0.2,
                "monetary_stance": 0.3,
                "risk_sentiment": 0.4,
            },
        )
        assert abs(sum(config.dimension_weights.values()) - 1.0) < 1e-6

    def test_frozen(self) -> None:
        config = ScoringConfig(
            dimension_weights={
                "growth_momentum": 0.25,
                "external_balance": 0.25,
                "monetary_stance": 0.25,
                "risk_sentiment": 0.25,
            },
        )
        with pytest.raises(ValidationError):
            config.scale_min = -5.0  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            ScoringConfig(
                dimension_weights={
                    "growth_momentum": 0.25,
                    "external_balance": 0.25,
                    "monetary_stance": 0.25,
                    "risk_sentiment": 0.25,
                },
                bogus_field=42,  # type: ignore[call-arg]
            )

    def test_default_frequency_weights(self) -> None:
        config = ScoringConfig(
            dimension_weights={
                "growth_momentum": 0.25,
                "external_balance": 0.25,
                "monetary_stance": 0.25,
                "risk_sentiment": 0.25,
            },
        )
        assert config.frequency_weights["daily"] == 1.0
        assert config.frequency_weights["annual"] == 0.3
        assert config.frequency_weights["forecast"] == 0.4

    def test_default_ewm_halflife(self) -> None:
        config = ScoringConfig(
            dimension_weights={
                "growth_momentum": 0.25,
                "external_balance": 0.25,
                "monetary_stance": 0.25,
                "risk_sentiment": 0.25,
            },
        )
        assert config.ewm_halflife["daily"] == 252
        assert config.ewm_halflife["monthly"] == 12
        assert config.ewm_halflife["annual"] == 5

    def test_default_staleness_gates(self) -> None:
        config = ScoringConfig(
            dimension_weights={
                "growth_momentum": 0.25,
                "external_balance": 0.25,
                "monetary_stance": 0.25,
                "risk_sentiment": 0.25,
            },
        )
        assert config.staleness_gates["daily"] == 14
        assert config.staleness_gates["monthly"] == 120
        assert config.staleness_gates["annual"] == 730


class TestDimensionScore:
    """DimensionScore domain type."""

    def test_valid(self) -> None:
        ds = DimensionScore(
            dimension="growth_momentum",
            value=-1.2,
            n_series_used=5,
            n_series_stale=1,
            n_concepts=3,
        )
        assert ds.value == -1.2
        assert ds.n_series_used == 5

    def test_none_value(self) -> None:
        ds = DimensionScore(
            dimension="external_balance",
            value=None,
        )
        assert ds.value is None
        assert ds.n_series_used == 0

    def test_frozen(self) -> None:
        ds = DimensionScore(dimension="growth_momentum", value=1.0)
        with pytest.raises(ValidationError):
            ds.value = 2.0  # type: ignore[misc]


class TestNewsHeat:
    """NewsHeat domain type."""

    def test_valid(self) -> None:
        nh = NewsHeat(sigma=2.5, volume_ratio=3.1)
        assert nh.sigma == 2.5
        assert nh.volume_ratio == 3.1


class TestScoreResult:
    """ScoreResult domain type."""

    def test_valid(self) -> None:
        import datetime

        result = ScoreResult(
            country_iso3="NGA",
            run_id="abc-123",
            scored_at=datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC),
            dimensions={
                "growth_momentum": DimensionScore(
                    dimension="growth_momentum",
                    value=-1.2,
                    n_series_used=5,
                    n_series_stale=0,
                    n_concepts=3,
                ),
            },
            composite=-0.8,
            coverage_fraction=0.25,
        )
        assert result.country_iso3 == "NGA"
        assert result.composite == -0.8
        assert result.news_heat is None

    def test_iso3_length_validation(self) -> None:
        import datetime

        with pytest.raises(ValidationError):
            ScoreResult(
                country_iso3="NG",
                run_id="abc",
                scored_at=datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC),
                dimensions={},
                composite=None,
                coverage_fraction=0.0,
            )


class TestAllDimensions:
    """ALL_DIMENSIONS tuple."""

    def test_four_dimensions(self) -> None:
        assert len(ALL_DIMENSIONS) == 4

    def test_contents(self) -> None:
        assert "growth_momentum" in ALL_DIMENSIONS
        assert "external_balance" in ALL_DIMENSIONS
        assert "monetary_stance" in ALL_DIMENSIONS
        assert "risk_sentiment" in ALL_DIMENSIONS


class TestLoadScoringConfigFromYaml:
    """YAML seed loader for ScoringConfig."""

    def test_load_packaged_default(self) -> None:
        config = load_scoring_config_from_yaml()
        assert config.dimension_weights["growth_momentum"] == 0.25
        assert config.dimension_weights["risk_sentiment"] == 0.25
        assert config.zscore_method == "ewm"
        assert config.ewm_halflife["daily"] == 252
        assert config.staleness_gates["daily"] == 14
        assert config.composite_strategy == "renormalize"
        assert config.coverage_confidence == "sqrt"
        assert config.min_dimensions_for_composite == 2
        assert config.news_heat_sigma == 2.0
        assert config.min_observations == 12
        assert config.momentum_window == 30

    def test_custom_yaml(self) -> None:
        yaml_text = """
scoring_config:
  dimension_weights:
    growth_momentum: 0.4
    external_balance: 0.2
    monetary_stance: 0.2
    risk_sentiment: 0.2
  scale_min: -5.0
  scale_max: 5.0
"""
        config = load_scoring_config_from_yaml(yaml_text)
        assert config.dimension_weights["growth_momentum"] == 0.4
        assert config.scale_min == -5.0
        assert config.scale_max == 5.0

    def test_invalid_yaml_missing_key(self) -> None:
        with pytest.raises(ValueError, match="scoring_config"):
            load_scoring_config_from_yaml("not_scoring_config: {}")

    def test_invalid_yaml_not_mapping(self) -> None:
        with pytest.raises(ValueError, match="mapping"):
            load_scoring_config_from_yaml("- list_item")

    def test_weights_dont_sum_to_one(self) -> None:
        yaml_text = """
scoring_config:
  dimension_weights:
    growth_momentum: 0.5
    external_balance: 0.5
    monetary_stance: 0.5
    risk_sentiment: 0.5
"""
        with pytest.raises(ValueError, match=r"must sum to 1\.0"):
            load_scoring_config_from_yaml(yaml_text)
