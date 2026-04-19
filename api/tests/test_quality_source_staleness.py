"""Tests for Control #10: Source staleness."""

from __future__ import annotations

import datetime

from hornet.domain.observation import Observation
from hornet.quality.config import QualityConfig
from hornet.quality.source_staleness import check_source_staleness

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()
_RUN_ID = "test-run-1"


def _obs(days_ago: int, *, frequency: str = "daily") -> Observation:
    return Observation(
        country_iso3="NGA",
        indicator_code="CPI_YOY",
        source_id="fred",
        date=_TODAY - datetime.timedelta(days=days_ago),
        value=10.0,
        frequency=frequency,
        vintage=_NOW,
        ingested_at=_NOW,
    )


class TestCheckSourceStaleness:
    def test_fresh_data(self) -> None:
        obs = [_obs(2)]
        config = QualityConfig(staleness_days={"daily": 7})
        issues = check_source_staleness(obs, _TODAY, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_stale_data(self) -> None:
        obs = [_obs(30)]
        config = QualityConfig(staleness_days={"daily": 7})
        issues = check_source_staleness(obs, _TODAY, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].detail["age_days"] == 30
        assert issues[0].detail["threshold_days"] == 7

    def test_frequency_specific_threshold(self) -> None:
        obs = [_obs(200, frequency="annual")]
        config = QualityConfig(staleness_days={"annual": 400})
        issues = check_source_staleness(obs, _TODAY, config, _RUN_ID, _NOW)
        assert len(issues) == 0  # 200 days < 400 threshold

    def test_unknown_frequency_not_flagged(self) -> None:
        obs = [_obs(1000, frequency="weekly")]
        config = QualityConfig(staleness_days={"daily": 7})  # no weekly threshold
        issues = check_source_staleness(obs, _TODAY, config, _RUN_ID, _NOW)
        assert len(issues) == 0
