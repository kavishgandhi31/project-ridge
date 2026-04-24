"""Tests for Control #1: Outlier detection."""

from __future__ import annotations

import datetime

from ridge.domain.observation import Observation
from ridge.quality.config import QualityConfig
from ridge.quality.outlier import detect_outliers

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()
_RUN_ID = "test-run-1"


def _obs(value: float, days_ago: int, *, indicator: str = "CPI_YOY") -> Observation:
    return Observation(
        country_iso3="NGA",
        indicator_code=indicator,
        source_id="worldbank",
        date=_TODAY - datetime.timedelta(days=days_ago),
        value=value,
        frequency="annual",
        vintage=_NOW,
        ingested_at=_NOW,
    )


class TestDetectOutliers:
    def test_no_outlier(self) -> None:
        obs = [_obs(10.0 + i * 0.1, 30 - i) for i in range(25)]
        config = QualityConfig(outlier_sigma=4.0, outlier_min_history=20)
        issues = detect_outliers(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_detects_outlier(self) -> None:
        # 24 normal values with some variance, then a spike
        obs = [_obs(10.0 + i * 0.1, 30 - i) for i in range(24)]
        obs.append(_obs(100.0, 0))  # extreme value
        config = QualityConfig(outlier_sigma=4.0, outlier_min_history=20)
        issues = detect_outliers(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].check_name == "outlier"
        assert issues[0].severity.value == "critical"
        assert issues[0].country_iso3 == "NGA"
        assert issues[0].indicator_code == "CPI_YOY"
        assert issues[0].detail["sigma_distance"] > 4.0

    def test_insufficient_history(self) -> None:
        obs = [_obs(10.0, 5 - i) for i in range(5)]
        config = QualityConfig(outlier_min_history=20)
        issues = detect_outliers(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_constant_series_no_outlier(self) -> None:
        obs = [_obs(5.0, 30 - i) for i in range(25)]
        config = QualityConfig(outlier_sigma=4.0, outlier_min_history=20)
        issues = detect_outliers(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0  # std=0, no outlier

    def test_multiple_series(self) -> None:
        # Normal CPI series + outlier GDP series
        cpi_obs = [_obs(10.0 + i * 0.1, 30 - i, indicator="CPI_YOY") for i in range(25)]
        gdp_obs = [_obs(3.0 + i * 0.05, 30 - i, indicator="GDP_GROWTH") for i in range(24)]
        gdp_obs.append(_obs(50.0, 0, indicator="GDP_GROWTH"))
        config = QualityConfig(outlier_sigma=4.0, outlier_min_history=20)
        issues = detect_outliers(cpi_obs + gdp_obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].indicator_code == "GDP_GROWTH"

    def test_custom_sigma_threshold(self) -> None:
        # With a tight threshold, a moderate deviation becomes an outlier
        obs = [_obs(10.0 + i * 0.05, 30 - i) for i in range(24)]
        obs.append(_obs(15.0, 0))  # moderate deviation
        config = QualityConfig(outlier_sigma=1.0, outlier_min_history=20)
        issues = detect_outliers(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1
