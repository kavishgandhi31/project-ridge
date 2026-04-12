"""Tests for the dispatcher -- routing and escalation limits."""

from __future__ import annotations

import datetime

from hornet.alerts.config import AlertConfig
from hornet.alerts.dispatcher import dispatch
from hornet.domain.alerting import AlertTier, TierAssignment

_NOW = datetime.datetime(2026, 4, 12, 6, 0, tzinfo=datetime.UTC)


def _make_assignment(
    iso3: str,
    effective_tier: AlertTier | None,
    composite: float | None = -2.0,
) -> TierAssignment:
    return TierAssignment(
        country_iso3=iso3,
        country_name=iso3,
        region=None,
        run_id="test-run-1",
        evaluated_at=_NOW,
        composite=composite,
        coverage_fraction=1.0,
        raw_tier=effective_tier,
        effective_tier=effective_tier,
    )


def _default_config(**overrides: object) -> AlertConfig:
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


class TestDispatchRouting:
    def test_correct_bucket_assignment(self) -> None:
        assignments = [
            _make_assignment("TUR", AlertTier.ESCALATE, composite=-2.5),
            _make_assignment("ARG", AlertTier.ESCALATE, composite=-2.1),
            _make_assignment("NGA", AlertTier.ALERT, composite=-1.6),
            _make_assignment("ZAF", AlertTier.WATCH, composite=-1.0),
            _make_assignment("POL", None, composite=-0.5),
        ]
        config = _default_config()
        result = dispatch(assignments, config)

        assert len(result.escalate) == 2
        assert len(result.alert) == 1
        assert len(result.watch) == 1
        assert len(result.no_signal) == 1

    def test_severity_sorting(self) -> None:
        """Higher |composite| first within each bucket."""
        assignments = [
            _make_assignment("AAA", AlertTier.ESCALATE, composite=-2.1),
            _make_assignment("BBB", AlertTier.ESCALATE, composite=-2.8),
        ]
        config = _default_config()
        result = dispatch(assignments, config)

        assert result.escalate[0].country_iso3 == "BBB"
        assert result.escalate[1].country_iso3 == "AAA"

    def test_empty_input(self) -> None:
        config = _default_config()
        result = dispatch([], config)
        assert result.total == 0
        assert not result.has_escalations
        assert result.actionable_count == 0


class TestEscalationLimit:
    def test_excess_downgraded_to_alert(self) -> None:
        """When limit=1, only 1 ESCALATE goes through."""
        assignments = [
            _make_assignment("TUR", AlertTier.ESCALATE, composite=-2.5),
            _make_assignment("ARG", AlertTier.ESCALATE, composite=-2.1),
        ]
        config = _default_config(max_daily_escalations=1)
        result = dispatch(assignments, config)

        assert len(result.escalate) == 1
        assert len(result.alert) == 1

    def test_limit_zero(self) -> None:
        """Limit=0 means all ESCALATE get downgraded."""
        assignments = [
            _make_assignment("TUR", AlertTier.ESCALATE, composite=-2.5),
        ]
        config = _default_config(max_daily_escalations=0)
        result = dispatch(assignments, config)

        assert len(result.escalate) == 0
        assert len(result.alert) == 1


class TestDispatchResultProperties:
    def test_has_escalations(self) -> None:
        assignments = [_make_assignment("TUR", AlertTier.ESCALATE)]
        config = _default_config()
        result = dispatch(assignments, config)
        assert result.has_escalations is True

    def test_actionable_count(self) -> None:
        assignments = [
            _make_assignment("TUR", AlertTier.ESCALATE, composite=-2.5),
            _make_assignment("NGA", AlertTier.ALERT, composite=-1.6),
            _make_assignment("ZAF", AlertTier.WATCH, composite=-1.0),
        ]
        config = _default_config()
        result = dispatch(assignments, config)
        assert result.actionable_count == 2

    def test_total(self) -> None:
        assignments = [
            _make_assignment("TUR", AlertTier.ESCALATE, composite=-2.5),
            _make_assignment("POL", None, composite=-0.5),
        ]
        config = _default_config()
        result = dispatch(assignments, config)
        assert result.total == 2
