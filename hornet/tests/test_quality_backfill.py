"""Tests for Control #9: Backfill detection."""

from __future__ import annotations

import datetime

from hornet.domain.scoring import DimensionScore, ScoreResult
from hornet.quality.backfill import detect_backfills
from hornet.quality.config import QualityConfig

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_RUN_ID = "test-run-1"


def _result(iso3: str, coverage: float) -> ScoreResult:
    return ScoreResult(
        country_iso3=iso3,
        run_id="run-1",
        scored_at=_NOW,
        dimensions={
            "growth_momentum": DimensionScore(dimension="growth_momentum", value=1.0),
        },
        composite=1.0,
        coverage_fraction=coverage,
    )


class TestDetectBackfills:
    def test_stable_coverage(self) -> None:
        current = [_result("NGA", 0.75)]
        prior = [_result("NGA", 0.75)]
        issues = detect_backfills(current, prior, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_large_gain(self) -> None:
        current = [_result("NGA", 1.0)]
        prior = [_result("NGA", 0.5)]
        config = QualityConfig(backfill_threshold=0.25)
        issues = detect_backfills(current, prior, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].detail["gain"] == 0.5

    def test_coverage_drop_not_flagged(self) -> None:
        current = [_result("NGA", 0.25)]
        prior = [_result("NGA", 0.75)]
        issues = detect_backfills(current, prior, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0  # drops are not backfills

    def test_new_country_ignored(self) -> None:
        current = [_result("NGA", 1.0)]
        prior: list[ScoreResult] = []
        issues = detect_backfills(current, prior, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0
