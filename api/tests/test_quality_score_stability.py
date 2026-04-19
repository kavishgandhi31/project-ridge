"""Tests for Control #4: Score stability."""

from __future__ import annotations

import datetime

from hornet.domain.scoring import DimensionScore, ScoreResult
from hornet.quality.config import QualityConfig
from hornet.quality.score_stability import check_score_stability

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_RUN_ID = "test-run-1"


def _result(iso3: str, composite: float | None, coverage: float) -> ScoreResult:
    return ScoreResult(
        country_iso3=iso3,
        run_id="run-1",
        scored_at=_NOW,
        dimensions={
            "growth_momentum": DimensionScore(dimension="growth_momentum", value=composite),
        },
        composite=composite,
        coverage_fraction=coverage,
    )


class TestCheckScoreStability:
    def test_stable_scores(self) -> None:
        current = [_result("NGA", 1.0, 0.75)]
        prior = [_result("NGA", 0.9, 0.75)]
        config = QualityConfig(score_jump_threshold=1.0)
        issues = check_score_stability(current, prior, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_large_jump(self) -> None:
        current = [_result("NGA", 2.5, 0.75)]
        prior = [_result("NGA", 0.5, 0.75)]
        config = QualityConfig(score_jump_threshold=1.0)
        issues = check_score_stability(current, prior, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].detail["delta"] == 2.0

    def test_coverage_changed_not_flagged(self) -> None:
        current = [_result("NGA", 2.5, 1.0)]
        prior = [_result("NGA", 0.5, 0.5)]  # coverage changed significantly
        config = QualityConfig(score_jump_threshold=1.0)
        issues = check_score_stability(current, prior, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_none_composite_ignored(self) -> None:
        current = [_result("NGA", None, 0.0)]
        prior = [_result("NGA", 2.0, 0.75)]
        issues = check_score_stability(current, prior, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_new_country_ignored(self) -> None:
        current = [_result("NGA", 2.0, 0.75)]
        prior: list[ScoreResult] = []
        issues = check_score_stability(current, prior, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0
