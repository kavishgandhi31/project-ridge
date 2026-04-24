"""Tests for Control #8: Date consistency."""

from __future__ import annotations

import datetime

from ridge.domain.observation import Observation
from ridge.quality.config import QualityConfig
from ridge.quality.date_consistency import check_date_consistency

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()
_RUN_ID = "test-run-1"


def _obs(source: str, days_ago: int) -> Observation:
    return Observation(
        country_iso3="NGA",
        indicator_code="CPI_YOY",
        source_id=source,
        date=_TODAY - datetime.timedelta(days=days_ago),
        value=10.0,
        frequency="monthly",
        vintage=_NOW,
        ingested_at=_NOW,
    )


class TestCheckDateConsistency:
    def test_aligned_sources(self) -> None:
        obs = [_obs("fred", 5), _obs("worldbank", 7)]
        config = QualityConfig(max_source_date_lag_days=30)
        issues = check_date_consistency(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_large_lag(self) -> None:
        obs = [_obs("fred", 5), _obs("worldbank", 100)]
        config = QualityConfig(max_source_date_lag_days=30)
        issues = check_date_consistency(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].detail["lag_days"] == 95

    def test_single_source_no_issue(self) -> None:
        obs = [_obs("fred", 5)]
        issues = check_date_consistency(obs, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0
