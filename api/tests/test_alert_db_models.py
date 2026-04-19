"""Tests for alert-layer DB models -- PipelineRunRow and AlertRecordRow.

Unit tests for from_domain / to_domain round-tripping. No DB needed.
"""

from __future__ import annotations

import datetime

from hornet.db.models.alert_record import AlertRecordRow
from hornet.db.models.pipeline_run import PipelineRunRow
from hornet.domain.alerting import AlertTier, TierAssignment
from hornet.domain.pipeline import PipelineRun, RunStatus, RunType

_NOW = datetime.datetime(2026, 4, 12, 6, 0, tzinfo=datetime.UTC)


class TestPipelineRunRow:
    def test_from_domain(self) -> None:
        run = PipelineRun(
            run_id="test-run-1",
            run_type=RunType.DAILY,
            started_at=_NOW,
            completed_at=None,
            status=RunStatus.RUNNING,
            stages_completed=("ingest", "quality"),
            n_countries_scored=183,
            n_escalate=3,
            n_alert=12,
            n_watch=45,
        )
        row = PipelineRunRow.from_domain(run)

        assert row.run_id == "test-run-1"
        assert row.run_type == "daily"
        assert row.status == "running"
        assert row.stages_completed == ["ingest", "quality"]
        assert row.n_countries_scored == 183

    def test_to_domain(self) -> None:
        row = PipelineRunRow(
            run_id="test-run-2",
            run_type="manual",
            started_at=_NOW,
            completed_at=_NOW,
            status="completed",
            stages_completed=["ingest", "quality", "score", "alert"],
            n_countries_scored=5,
            n_escalate=1,
            n_alert=2,
            n_watch=2,
            error_message=None,
        )
        run = row.to_domain()

        assert run.run_id == "test-run-2"
        assert run.run_type == RunType.MANUAL
        assert run.status == RunStatus.COMPLETED
        assert run.stages_completed == ("ingest", "quality", "score", "alert")

    def test_round_trip(self) -> None:
        original = PipelineRun(
            run_id="rt-1",
            run_type=RunType.BACKFILL,
            started_at=_NOW,
            completed_at=None,
            status=RunStatus.FAILED,
            stages_completed=("ingest",),
            error_message="Connection refused",
        )
        row = PipelineRunRow.from_domain(original)
        restored = row.to_domain()

        assert restored.run_id == original.run_id
        assert restored.run_type == original.run_type
        assert restored.status == original.status
        assert restored.stages_completed == original.stages_completed
        assert restored.error_message == original.error_message


class TestAlertRecordRow:
    def test_from_domain(self) -> None:
        assignment = TierAssignment(
            country_iso3="TUR",
            country_name="Turkey",
            region="Europe & Central Asia",
            run_id="test-run-1",
            evaluated_at=_NOW,
            composite=-2.5,
            coverage_fraction=0.75,
            raw_tier=AlertTier.ESCALATE,
            effective_tier=AlertTier.ALERT,
            streak_length=1,
            velocity=0.8,
            modifiers_applied=("streak_hold",),
        )
        row = AlertRecordRow.from_domain(assignment)

        assert row.country_iso3 == "TUR"
        assert row.raw_tier == "ESCALATE"
        assert row.effective_tier == "ALERT"
        assert row.streak_length == 1
        assert row.velocity == 0.8
        assert row.modifiers_applied == ["streak_hold"]

    def test_to_domain_dict(self) -> None:
        row = AlertRecordRow(
            country_iso3="NGA",
            run_id="test-run-2",
            evaluated_at=_NOW,
            composite=-1.6,
            coverage_fraction=1.0,
            raw_tier="ALERT",
            effective_tier="ALERT",
            streak_length=3,
            velocity=0.2,
            modifiers_applied=[],
        )
        d = row.to_domain_dict()

        assert d["country_iso3"] == "NGA"
        assert d["effective_tier"] == "ALERT"
        assert d["composite"] == -1.6
        assert d["streak_length"] == 3

    def test_none_tiers(self) -> None:
        """Countries with no tier should store None."""
        assignment = TierAssignment(
            country_iso3="POL",
            country_name="Poland",
            run_id="test-run-1",
            evaluated_at=_NOW,
            composite=-0.5,
            coverage_fraction=1.0,
            raw_tier=None,
            effective_tier=None,
        )
        row = AlertRecordRow.from_domain(assignment)
        assert row.raw_tier is None
        assert row.effective_tier is None

        d = row.to_domain_dict()
        assert d["effective_tier"] is None
