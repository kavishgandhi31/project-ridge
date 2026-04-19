"""Tests for Control #3: Cross-source validation."""

from __future__ import annotations

import datetime

from hornet.domain.observation import Observation
from hornet.quality.config import QualityConfig
from hornet.quality.cross_source import validate_cross_source

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()
_RUN_ID = "test-run-1"


def _obs(
    value: float,
    *,
    source: str = "fred",
    indicator: str = "FX_USD",
    date: datetime.date | None = None,
) -> Observation:
    return Observation(
        country_iso3="NGA",
        indicator_code=indicator,
        source_id=source,
        date=date or _TODAY,
        value=value,
        frequency="daily",
        vintage=_NOW,
        ingested_at=_NOW,
    )


class TestValidateCrossSource:
    def test_no_overlap(self) -> None:
        obs = [_obs(100.0, source="fred"), _obs(50.0, source="fred", indicator="CPI")]
        issues = validate_cross_source(obs, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_matching_values(self) -> None:
        obs = [_obs(100.0, source="fred"), _obs(100.0, source="yfinance")]
        issues = validate_cross_source(obs, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_divergent_values(self) -> None:
        obs = [_obs(100.0, source="fred"), _obs(110.0, source="yfinance")]
        config = QualityConfig(cross_source_threshold=0.02)
        issues = validate_cross_source(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].check_name == "cross_source"
        assert issues[0].detail["divergence_pct"] > 2.0

    def test_within_threshold(self) -> None:
        obs = [_obs(100.0, source="fred"), _obs(101.0, source="yfinance")]
        config = QualityConfig(cross_source_threshold=0.02)
        issues = validate_cross_source(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0
