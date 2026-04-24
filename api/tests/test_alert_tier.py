"""Tests for the tier evaluator -- pure function alert tier assignment.

Covers:
    - Raw threshold boundaries (v1 parity: WATCH=1.0, ALERT=1.5, ESCALATE=2.0)
    - Coverage gate (blocks ESCALATE when coverage < min)
    - Streak requirement (blocks ESCALATE without prior ALERT+ runs)
    - Velocity boost (promotes tier for fast movers, deteriorating only)
    - Combined modifier interactions
    - Edge cases: None composite, empty history, positive composites

Test structure mirrors v1's test_escalation_modifiers.py for direct
parity verification.
"""

from __future__ import annotations

import datetime

import pytest

from ridge.alerts.config import AlertConfig
from ridge.alerts.tier import (
    assign_tier,
    compute_velocity,
    count_alert_streak,
)
from ridge.domain.alerting import AlertTier
from ridge.domain.scoring import DimensionScore, ScoreResult

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_NOW = datetime.datetime(2026, 4, 12, 6, 0, tzinfo=datetime.UTC)


def _make_score(
    iso3: str = "TUR",
    composite: float | None = -2.0,
    coverage: float = 1.0,
    run_id: str = "test-run-1",
) -> ScoreResult:
    """Build a minimal ScoreResult for testing."""
    # Build dimension scores that match the requested coverage
    dims: dict[str, DimensionScore] = {}
    dim_names = ["growth_momentum", "external_balance", "monetary_stance", "risk_sentiment"]
    n_present = max(0, int(coverage * 4))
    for i, name in enumerate(dim_names):
        dims[name] = DimensionScore(
            dimension=name,
            value=-1.0 if i < n_present else None,
        )
    return ScoreResult(
        country_iso3=iso3,
        run_id=run_id,
        scored_at=_NOW,
        dimensions=dims,
        composite=composite,
        coverage_fraction=coverage,
    )


def _make_history(entries: list[tuple[float | None, str | None]]) -> list[dict[str, object]]:
    """Build prior records from (composite, effective_tier) tuples.

    Most-recent-first, matching the DB query order.
    """
    return [
        {
            "composite": comp,
            "effective_tier": tier,
            "evaluated_at": datetime.datetime(2026, 4, 12 - i, tzinfo=datetime.UTC),
        }
        for i, (comp, tier) in enumerate(entries)
    ]


def _default_config(**overrides: object) -> AlertConfig:
    """Build an AlertConfig with optional overrides."""
    defaults: dict[str, object] = {
        "watch_threshold": 1.0,
        "alert_threshold": 1.5,
        "escalate_threshold": 2.0,
        "min_coverage_for_escalate": 0.5,
        "streak_required": 2,
        "velocity_threshold": 0.5,
        "max_daily_escalations": 10,
    }
    defaults.update(overrides)
    return AlertConfig(**defaults)


# ------------------------------------------------------------------
# 1. Raw threshold boundaries
# ------------------------------------------------------------------


class TestRawThresholds:
    """Verify tier assignment at exact boundary values.

    v1 parity: WATCH >= 1.0, ALERT >= 1.5, ESCALATE >= 2.0
    """

    @pytest.mark.parametrize(
        ("composite", "expected_raw"),
        [
            (0.99, None),
            (1.00, AlertTier.WATCH),
            (1.49, AlertTier.WATCH),
            (1.50, AlertTier.ALERT),
            (1.99, AlertTier.ALERT),
            (2.00, AlertTier.ESCALATE),
            (3.00, AlertTier.ESCALATE),
            (-1.00, AlertTier.WATCH),
            (-1.50, AlertTier.ALERT),
            (-2.00, AlertTier.ESCALATE),
        ],
    )
    def test_threshold_boundaries(
        self,
        composite: float,
        expected_raw: AlertTier | None,
    ) -> None:
        config = _default_config(streak_required=0)
        score = _make_score(composite=composite)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            evaluated_at=_NOW,
        )
        assert result.raw_tier == expected_raw

    def test_none_composite(self) -> None:
        """None composite should produce no tier."""
        config = _default_config()
        score = _make_score(composite=None)
        result = assign_tier(score, config, country_name="Test", evaluated_at=_NOW)
        assert result.raw_tier is None
        assert result.effective_tier is None
        assert result.modifiers_applied == ()


# ------------------------------------------------------------------
# 2. Coverage gate
# ------------------------------------------------------------------


class TestCoverageGate:
    def test_blocks_escalate_low_coverage(self) -> None:
        """<50% coverage should cap ESCALATE at ALERT."""
        config = _default_config(streak_required=0)
        score = _make_score(composite=-2.5, coverage=0.25)
        result = assign_tier(score, config, country_name="Test", evaluated_at=_NOW)
        assert result.raw_tier == AlertTier.ESCALATE
        assert result.effective_tier == AlertTier.ALERT
        assert "coverage_gate" in result.modifiers_applied

    def test_allows_escalate_with_full_coverage(self) -> None:
        config = _default_config(streak_required=0)
        score = _make_score(composite=-2.5, coverage=1.0)
        result = assign_tier(score, config, country_name="Test", evaluated_at=_NOW)
        assert result.effective_tier == AlertTier.ESCALATE

    def test_exact_boundary(self) -> None:
        """Coverage exactly at threshold should allow ESCALATE."""
        config = _default_config(streak_required=0)
        score = _make_score(composite=-2.5, coverage=0.5)
        result = assign_tier(score, config, country_name="Test", evaluated_at=_NOW)
        assert result.effective_tier == AlertTier.ESCALATE

    def test_does_not_affect_alert(self) -> None:
        """Coverage gate only applies to ESCALATE, not ALERT."""
        config = _default_config()
        score = _make_score(composite=-1.6, coverage=0.25)
        result = assign_tier(score, config, country_name="Test", evaluated_at=_NOW)
        assert result.effective_tier == AlertTier.ALERT


# ------------------------------------------------------------------
# 3. Streak requirement
# ------------------------------------------------------------------


class TestStreak:
    def test_blocks_escalate_insufficient_runs(self) -> None:
        """1 prior ALERT run < required 2 -> cap at ALERT."""
        config = _default_config(streak_required=2)
        history = _make_history([(-1.6, "ALERT")])
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ALERT
        assert "streak_hold" in result.modifiers_applied

    def test_allows_escalate_after_enough_runs(self) -> None:
        """2 prior ALERT runs >= required 2 -> allow ESCALATE."""
        config = _default_config(streak_required=2)
        history = _make_history([(-1.8, "ALERT"), (-1.6, "ALERT")])
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ESCALATE

    def test_escalate_counts_as_alert_plus(self) -> None:
        """Prior ESCALATE entries count toward the ALERT+ streak."""
        config = _default_config(streak_required=2)
        history = _make_history([(-2.5, "ESCALATE"), (-2.1, "ESCALATE")])
        score = _make_score(composite=-2.8)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ESCALATE

    def test_broken_by_watch(self) -> None:
        """A WATCH entry breaks the streak."""
        config = _default_config(streak_required=2)
        history = _make_history([(-1.0, "WATCH"), (-1.8, "ALERT")])
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ALERT

    def test_broken_by_no_signal(self) -> None:
        """None tier in history breaks the streak."""
        config = _default_config(streak_required=2)
        history = _make_history([(-0.5, None), (-1.8, "ALERT")])
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ALERT

    def test_empty_history(self) -> None:
        """Empty history -> streak=0, falls back to raw with streak_hold."""
        config = _default_config(streak_required=2)
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=[],
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ALERT
        assert result.streak_length == 0

    def test_none_history_raw_thresholds(self) -> None:
        """None history -> streak check skipped, raw thresholds used."""
        config = _default_config(streak_required=2)
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=None,
            evaluated_at=_NOW,
        )
        # None history means prior_records=[] in assign_tier
        assert result.effective_tier == AlertTier.ALERT


# ------------------------------------------------------------------
# 4. Velocity boost
# ------------------------------------------------------------------


class TestVelocityBoost:
    def test_promotes_watch_to_alert(self) -> None:
        """Fast-moving WATCH -> ALERT."""
        config = _default_config(velocity_threshold=0.5, streak_required=0)
        history = _make_history([(-0.5, None)])
        score = _make_score(composite=-1.2)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ALERT
        assert "velocity_boost" in result.modifiers_applied

    def test_promotes_alert_to_escalate(self) -> None:
        """Fast-moving ALERT -> ESCALATE (streak disabled)."""
        config = _default_config(velocity_threshold=0.5, streak_required=0)
        history = _make_history([(-1.0, "WATCH")])
        score = _make_score(composite=-1.7)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ESCALATE

    def test_no_effect_below_threshold(self) -> None:
        """Small move should not trigger velocity boost."""
        config = _default_config(velocity_threshold=0.5)
        history = _make_history([(-1.0, "WATCH")])
        score = _make_score(composite=-1.2)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.WATCH

    def test_does_not_exceed_escalate(self) -> None:
        """ESCALATE is the ceiling."""
        config = _default_config(velocity_threshold=0.5, streak_required=0)
        history = _make_history([(-1.5, "ALERT")])
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ESCALATE

    def test_blocked_by_coverage_gate(self) -> None:
        """Velocity boost to ESCALATE blocked by coverage gate."""
        config = _default_config(
            velocity_threshold=0.5,
            streak_required=0,
            min_coverage_for_escalate=0.5,
        )
        history = _make_history([(-1.0, "WATCH")])
        score = _make_score(composite=-1.7, coverage=0.25)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ALERT
        assert "coverage_gate_post_velocity" in result.modifiers_applied

    def test_skips_positive_direction(self) -> None:
        """Velocity boost does NOT apply to improving (positive) composites."""
        config = _default_config(velocity_threshold=0.5, streak_required=0)
        history = _make_history([(0.5, None)])
        score = _make_score(composite=1.2)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.WATCH

    def test_does_not_re_promote_demoted_escalate(self) -> None:
        """Raw ESCALATE demoted by coverage/streak should not be re-promoted."""
        config = _default_config(
            velocity_threshold=0.5,
            streak_required=2,
            min_coverage_for_escalate=0.5,
        )
        # Large velocity but raw tier is ESCALATE (demoted by streak)
        history = _make_history([(-1.5, "ALERT")])  # streak=1 < required=2
        score = _make_score(composite=-2.5)  # raw ESCALATE
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        # Should stay ALERT, not be re-promoted by velocity
        assert result.effective_tier == AlertTier.ALERT


# ------------------------------------------------------------------
# 5. Combined modifiers
# ------------------------------------------------------------------


class TestCombinedModifiers:
    def test_all_gates_pass(self) -> None:
        """High coverage, good streak, fast move -> ESCALATE."""
        config = _default_config(
            streak_required=2,
            velocity_threshold=0.5,
            min_coverage_for_escalate=0.5,
        )
        history = _make_history([(-1.9, "ALERT"), (-1.6, "ALERT")])
        score = _make_score(composite=-2.5, coverage=0.75)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ESCALATE

    def test_blocked_by_streak_despite_others(self) -> None:
        """Passes coverage and velocity, fails streak -> ALERT."""
        config = _default_config(
            streak_required=3,
            velocity_threshold=0.5,
            min_coverage_for_escalate=0.5,
        )
        history = _make_history([(-1.9, "ALERT"), (-1.6, "ALERT")])
        score = _make_score(composite=-2.5, coverage=0.75)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.effective_tier == AlertTier.ALERT


# ------------------------------------------------------------------
# 6. Helper function unit tests
# ------------------------------------------------------------------


class TestHelpers:
    def test_count_alert_streak_empty(self) -> None:
        assert count_alert_streak([]) == 0

    def test_count_alert_streak_mixed(self) -> None:
        history = _make_history([(-2.0, "ESCALATE"), (-1.8, "ALERT"), (-1.0, "WATCH")])
        assert count_alert_streak(history) == 2

    def test_count_alert_streak_broken_at_start(self) -> None:
        history = _make_history([(-1.0, "WATCH"), (-1.8, "ALERT")])
        assert count_alert_streak(history) == 0

    def test_compute_velocity_basic(self) -> None:
        history = _make_history([(-1.5, "ALERT")])
        assert compute_velocity(-2.0, history) == pytest.approx(0.5)

    def test_compute_velocity_skips_none(self) -> None:
        history: list[dict[str, object]] = [
            {"composite": None, "effective_tier": None},
            {"composite": -1.0, "effective_tier": "WATCH"},
        ]
        assert compute_velocity(-2.0, history) == pytest.approx(1.0)

    def test_compute_velocity_empty(self) -> None:
        assert compute_velocity(-2.0, []) is None


# ------------------------------------------------------------------
# 7. TierAssignment fields
# ------------------------------------------------------------------


class TestTierAssignmentFields:
    def test_carries_country_metadata(self) -> None:
        config = _default_config(streak_required=0)
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Turkey",
            region="Europe & Central Asia",
            evaluated_at=_NOW,
        )
        assert result.country_name == "Turkey"
        assert result.region == "Europe & Central Asia"
        assert result.run_id == "test-run-1"

    def test_streak_length_recorded(self) -> None:
        config = _default_config(streak_required=2)
        history = _make_history([(-1.8, "ALERT"), (-1.6, "ALERT"), (-1.5, "ALERT")])
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.streak_length == 3

    def test_velocity_recorded(self) -> None:
        config = _default_config(streak_required=0)
        history = _make_history([(-1.0, "WATCH")])
        score = _make_score(composite=-2.5)
        result = assign_tier(
            score,
            config,
            country_name="Test",
            prior_records=history,
            evaluated_at=_NOW,
        )
        assert result.velocity == pytest.approx(1.5)
