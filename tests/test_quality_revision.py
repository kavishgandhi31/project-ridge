"""Tests for Control #5: Revision detection."""

from __future__ import annotations

import datetime

from hornet.domain.observation import Observation
from hornet.quality.config import QualityConfig
from hornet.quality.revision import detect_revisions

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()
_RUN_ID = "test-run-1"


def _obs(
    value: float,
    days_ago: int,
    vintage_offset_hours: int = 0,
) -> Observation:
    return Observation(
        country_iso3="NGA",
        indicator_code="CPI_YOY",
        source_id="fred",
        date=_TODAY - datetime.timedelta(days=days_ago),
        value=value,
        frequency="annual",
        vintage=_NOW - datetime.timedelta(hours=vintage_offset_hours),
        ingested_at=_NOW,
    )


class TestDetectRevisions:
    def test_no_revisions(self) -> None:
        obs = [_obs(10.0, 5), _obs(11.0, 4), _obs(12.0, 3)]
        issues = detect_revisions(obs, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_detects_revision(self) -> None:
        # Same date, two vintages, different values
        obs = [
            _obs(10.0, 5, vintage_offset_hours=48),  # old vintage
            _obs(10.5, 5, vintage_offset_hours=0),  # new vintage (revised)
            _obs(11.0, 4),
        ]
        issues = detect_revisions(obs, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].check_name == "revision"
        assert issues[0].severity.value == "info"
        assert issues[0].detail["revised_count"] == 1

    def test_same_value_different_vintage_not_flagged(self) -> None:
        obs = [
            _obs(10.0, 5, vintage_offset_hours=48),
            _obs(10.0, 5, vintage_offset_hours=0),  # same value, different vintage
        ]
        issues = detect_revisions(obs, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_lookback_limits_dates(self) -> None:
        # Revision on an old date outside lookback window
        obs = [
            _obs(10.0, 500, vintage_offset_hours=48),
            _obs(10.5, 500, vintage_offset_hours=0),
        ]
        # Add recent dates to make the series longer
        for i in range(15):
            obs.append(_obs(11.0 + i * 0.1, 15 - i))

        config = QualityConfig(revision_lookback=12)
        issues = detect_revisions(obs, config, _RUN_ID, _NOW)
        # The revision on day 500 is outside the last 12 dates
        assert len(issues) == 0
