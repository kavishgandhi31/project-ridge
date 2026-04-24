"""Tests for quality configuration domain types and YAML loading."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ridge.quality.config import QualityConfig
from ridge.quality.issue import IssueSeverity, QualityIssue
from ridge.seeds.loader import load_quality_config_from_yaml


class TestQualityConfig:
    def test_defaults(self) -> None:
        config = QualityConfig()
        assert config.outlier_sigma == 4.0
        assert config.outlier_min_history == 20
        assert config.flatline_min_repeats == 10
        assert config.break_window == 12
        assert config.break_sigma == 2.0
        assert config.cross_source_threshold == 0.02
        assert config.score_jump_threshold == 1.0
        assert config.max_source_date_lag_days == 30
        assert config.backfill_threshold == 0.25
        assert config.failure_threshold == 3

    def test_frozen(self) -> None:
        config = QualityConfig()
        with pytest.raises(ValidationError):
            config.outlier_sigma = 5.0  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            QualityConfig(bogus_field=42)  # type: ignore[call-arg]

    def test_custom_values(self) -> None:
        config = QualityConfig(
            outlier_sigma=3.0,
            flatline_min_repeats=5,
            break_sigma=3.0,
        )
        assert config.outlier_sigma == 3.0
        assert config.flatline_min_repeats == 5
        assert config.break_sigma == 3.0

    def test_staleness_days_defaults(self) -> None:
        config = QualityConfig()
        assert config.staleness_days["daily"] == 7
        assert config.staleness_days["monthly"] == 90
        assert config.staleness_days["annual"] == 400


class TestIssueSeverity:
    def test_values(self) -> None:
        assert IssueSeverity.INFO.value == "info"
        assert IssueSeverity.WARNING.value == "warning"
        assert IssueSeverity.CRITICAL.value == "critical"


class TestQualityIssue:
    def test_valid(self) -> None:
        import datetime

        issue = QualityIssue(
            check_name="outlier",
            severity=IssueSeverity.CRITICAL,
            country_iso3="NGA",
            indicator_code="CPI_YOY",
            source_id="fred",
            run_id="abc-123",
            detected_at=datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC),
            detail={"sigma_distance": 5.2, "threshold": 4.0},
            message="CPI_YOY latest value is 5.2 sigma from trailing mean",
        )
        assert issue.check_name == "outlier"
        assert issue.severity == IssueSeverity.CRITICAL
        assert issue.country_iso3 == "NGA"

    def test_nullable_fields(self) -> None:
        import datetime

        issue = QualityIssue(
            check_name="date_consistency",
            severity=IssueSeverity.WARNING,
            run_id="abc-123",
            detected_at=datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC),
            message="Global check with no country or indicator",
        )
        assert issue.country_iso3 is None
        assert issue.indicator_code is None
        assert issue.source_id is None

    def test_frozen(self) -> None:
        import datetime

        issue = QualityIssue(
            check_name="flatline",
            severity=IssueSeverity.WARNING,
            run_id="abc",
            detected_at=datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC),
            message="test",
        )
        with pytest.raises(ValidationError):
            issue.check_name = "other"  # type: ignore[misc]


class TestLoadQualityConfigFromYaml:
    def test_load_packaged_default(self) -> None:
        config = load_quality_config_from_yaml()
        assert config.outlier_sigma == 4.0
        assert config.outlier_min_history == 20
        assert config.flatline_min_repeats == 10
        assert config.break_window == 12
        assert config.break_sigma == 2.0
        assert config.cross_source_threshold == 0.02
        assert config.score_jump_threshold == 1.0
        assert config.max_source_date_lag_days == 30
        assert config.backfill_threshold == 0.25
        assert config.staleness_days["daily"] == 7

    def test_custom_yaml(self) -> None:
        yaml_text = """
quality_config:
  outlier_sigma: 3.0
  break_sigma: 3.0
"""
        config = load_quality_config_from_yaml(yaml_text)
        assert config.outlier_sigma == 3.0
        assert config.break_sigma == 3.0
        # Defaults still apply for unspecified fields
        assert config.flatline_min_repeats == 10

    def test_invalid_yaml_missing_key(self) -> None:
        with pytest.raises(ValueError, match="quality_config"):
            load_quality_config_from_yaml("not_quality: {}")

    def test_invalid_yaml_not_mapping(self) -> None:
        with pytest.raises(ValueError, match="mapping"):
            load_quality_config_from_yaml("- list_item")
