"""Tests for Control #6: Flatline detection."""

from __future__ import annotations

import datetime

from hornet.domain.observation import Observation
from hornet.quality.config import QualityConfig
from hornet.quality.flatline import detect_flatlines

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()
_RUN_ID = "test-run-1"


def _obs(value: float, days_ago: int) -> Observation:
    return Observation(
        country_iso3="NGA",
        indicator_code="CPI_YOY",
        source_id="worldbank",
        date=_TODAY - datetime.timedelta(days=days_ago),
        value=value,
        frequency="annual",
        vintage=_NOW,
        ingested_at=_NOW,
    )


class TestDetectFlatlines:
    def test_no_flatline(self) -> None:
        obs = [_obs(10.0 + i * 0.5, 20 - i) for i in range(15)]
        config = QualityConfig(flatline_min_repeats=10)
        issues = detect_flatlines(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_detects_flatline(self) -> None:
        obs = [_obs(5.0 + i * 0.1, 25 - i) for i in range(5)]
        obs += [_obs(10.0, 20 - i) for i in range(12)]  # 12 identical values
        config = QualityConfig(flatline_min_repeats=10)
        issues = detect_flatlines(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].check_name == "flatline"
        assert issues[0].severity.value == "warning"
        assert issues[0].detail["repeat_count"] == 12
        assert issues[0].detail["stuck_value"] == 10.0

    def test_insufficient_data(self) -> None:
        obs = [_obs(5.0, 5 - i) for i in range(5)]
        config = QualityConfig(flatline_min_repeats=10)
        issues = detect_flatlines(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_exactly_at_threshold(self) -> None:
        obs = [_obs(7.0, 15 - i) for i in range(10)]  # exactly 10 identical
        config = QualityConfig(flatline_min_repeats=10)
        issues = detect_flatlines(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1

    def test_below_threshold(self) -> None:
        obs = [_obs(1.0, 10)] + [_obs(7.0, 9 - i) for i in range(9)]
        config = QualityConfig(flatline_min_repeats=10)
        issues = detect_flatlines(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_tolerance(self) -> None:
        """Values within tolerance should count as identical."""
        obs = [_obs(10.0 + i * 1e-10, 15 - i) for i in range(12)]
        config = QualityConfig(flatline_min_repeats=10, flatline_tolerance=1e-8)
        issues = detect_flatlines(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1
