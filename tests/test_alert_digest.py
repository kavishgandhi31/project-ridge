"""Tests for the digest composer and text renderer."""

from __future__ import annotations

import datetime

from hornet.alerts.digest import compose_digest, render_digest_text
from hornet.domain.alerting import AlertTier, DispatchResult, TierAssignment
from hornet.domain.scoring import DimensionScore, ScoreResult
from hornet.quality.issue import IssueSeverity, QualityIssue

_NOW = datetime.datetime(2026, 4, 12, 6, 0, tzinfo=datetime.UTC)
_RUN_ID = "digest-test-run"


def _make_assignment(
    iso3: str,
    name: str,
    effective_tier: AlertTier | None,
    composite: float | None = -2.0,
    coverage: float = 1.0,
) -> TierAssignment:
    return TierAssignment(
        country_iso3=iso3,
        country_name=name,
        region="Test Region",
        run_id=_RUN_ID,
        evaluated_at=_NOW,
        composite=composite,
        coverage_fraction=coverage,
        raw_tier=effective_tier,
        effective_tier=effective_tier,
    )


def _make_score(
    iso3: str = "TUR",
    composite: float | None = -2.0,
) -> ScoreResult:
    dims = {
        "growth_momentum": DimensionScore(dimension="growth_momentum", value=-1.2),
        "external_balance": DimensionScore(dimension="external_balance", value=0.5),
        "monetary_stance": DimensionScore(dimension="monetary_stance", value=None),
        "risk_sentiment": DimensionScore(dimension="risk_sentiment", value=-2.1),
    }
    return ScoreResult(
        country_iso3=iso3,
        run_id=_RUN_ID,
        scored_at=_NOW,
        dimensions=dims,
        composite=composite,
        coverage_fraction=0.75,
    )


def _make_quality_issue(
    check_name: str = "outlier",
    severity: IssueSeverity = IssueSeverity.CRITICAL,
    iso3: str | None = "TUR",
) -> QualityIssue:
    return QualityIssue(
        check_name=check_name,
        severity=severity,
        country_iso3=iso3,
        run_id=_RUN_ID,
        detected_at=_NOW,
        message=f"Test {check_name} issue for {iso3}",
    )


class TestComposeDigest:
    def test_basic_composition(self) -> None:
        dispatch_result = DispatchResult(
            escalate=(_make_assignment("TUR", "Turkey", AlertTier.ESCALATE),),
            alert=(_make_assignment("NGA", "Nigeria", AlertTier.ALERT, composite=-1.6),),
            watch=(_make_assignment("ZAF", "South Africa", AlertTier.WATCH, composite=-1.0),),
        )
        scores = [_make_score("TUR"), _make_score("NGA", -1.6)]
        issues = [_make_quality_issue()]

        digest = compose_digest(dispatch_result, issues, scores, _RUN_ID, generated_at=_NOW)

        assert digest.summary.total_scored == 3
        assert digest.summary.n_escalate == 1
        assert digest.summary.n_alert == 1
        assert digest.summary.n_watch == 1
        assert len(digest.quality_issues) == 1
        assert "TUR" in digest.scores_by_country

    def test_empty_dispatch(self) -> None:
        dispatch_result = DispatchResult()
        digest = compose_digest(dispatch_result, [], [], _RUN_ID, generated_at=_NOW)
        assert digest.summary.total_scored == 0


class TestRenderDigestText:
    def test_header_present(self) -> None:
        dispatch_result = DispatchResult(
            escalate=(_make_assignment("TUR", "Turkey", AlertTier.ESCALATE),),
        )
        scores = [_make_score("TUR")]
        digest = compose_digest(dispatch_result, [], scores, _RUN_ID, generated_at=_NOW)
        text = render_digest_text(digest)

        assert "HORNET DAILY DIGEST" in text
        assert "ESCALATE" in text
        assert "Turkey" in text

    def test_dimension_scores_shown(self) -> None:
        dispatch_result = DispatchResult(
            escalate=(_make_assignment("TUR", "Turkey", AlertTier.ESCALATE),),
        )
        scores = [_make_score("TUR")]
        digest = compose_digest(dispatch_result, [], scores, _RUN_ID, generated_at=_NOW)
        text = render_digest_text(digest)

        assert "Growth: -1.2" in text
        assert "Risk: -2.1" in text
        assert "Monetary: N/A" in text

    def test_quality_section(self) -> None:
        dispatch_result = DispatchResult()
        issues = [
            _make_quality_issue("outlier", IssueSeverity.CRITICAL),
            _make_quality_issue("flatline", IssueSeverity.WARNING),
        ]
        digest = compose_digest(dispatch_result, issues, [], _RUN_ID, generated_at=_NOW)
        text = render_digest_text(digest)

        assert "DATA QUALITY" in text
        assert "CRITICAL" in text
        assert "outlier" in text

    def test_low_coverage_warning(self) -> None:
        dispatch_result = DispatchResult(
            alert=(
                _make_assignment(
                    "PRK", "North Korea", AlertTier.ALERT, composite=-2.5, coverage=0.25
                ),
            ),
        )
        digest = compose_digest(dispatch_result, [], [], _RUN_ID, generated_at=_NOW)
        text = render_digest_text(digest)

        assert "LOW COVERAGE" in text
        assert "North Korea" in text

    def test_watch_brief_format(self) -> None:
        dispatch_result = DispatchResult(
            watch=(_make_assignment("IND", "India", AlertTier.WATCH, composite=1.1),),
        )
        digest = compose_digest(dispatch_result, [], [], _RUN_ID, generated_at=_NOW)
        text = render_digest_text(digest)

        # WATCH section should be brief (no dimension breakdown)
        assert "India (IND): +1.10" in text

    def test_summary_counts(self) -> None:
        dispatch_result = DispatchResult(
            escalate=(_make_assignment("TUR", "Turkey", AlertTier.ESCALATE),),
            alert=(_make_assignment("NGA", "Nigeria", AlertTier.ALERT, composite=-1.6),),
        )
        digest = compose_digest(dispatch_result, [], [], _RUN_ID, generated_at=_NOW)
        text = render_digest_text(digest)

        assert "Countries scored:  2" in text
        assert "ESCALATE:          1" in text
        assert "ALERT:             1" in text
