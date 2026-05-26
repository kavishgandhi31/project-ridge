"""Smoke test: every enum-string column has a CHECK constraint that
rejects values outside its StrEnum. Closes the acceptance criterion
in docs/CLEANUP_PLAN.md Pass 1 Tier 3 #6.

Each case inserts a row that is valid in every other respect, but
puts a bogus literal in the column under test. The DB must raise
IntegrityError. If a future migration drops a constraint or a future
StrEnum gains a value that isn't reflected in the CHECK, this test
fails.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from ridge.db.models.alert_record import AlertRecordRow
from ridge.db.models.llm_response import LLMResponseRow
from ridge.db.models.pipeline_run import PipelineRunRow
from ridge.db.models.quality_issue import QualityIssueRow
from ridge.db.session import session_scope

_NOW = datetime.datetime(2026, 5, 25, tzinfo=datetime.UTC)


def _pipeline_run_insert(column: str, bad_value: str) -> tuple[str, dict[str, object]]:
    run_id = f"check-test-{uuid.uuid4().hex[:8]}"
    params: dict[str, object] = {
        "run_id": run_id,
        "run_type": "manual",
        "started_at": _NOW,
        "status": "running",
        "stages_completed": [],
        "n_countries_scored": 0,
        "n_escalate": 0,
        "n_alert": 0,
        "n_watch": 0,
    }
    params[column] = bad_value
    sql = """
        INSERT INTO pipeline_run (
            run_id, run_type, started_at, status, stages_completed,
            n_countries_scored, n_escalate, n_alert, n_watch
        ) VALUES (
            :run_id, :run_type, :started_at, :status, :stages_completed,
            :n_countries_scored, :n_escalate, :n_alert, :n_watch
        )
    """
    return sql, params


def _quality_issue_insert(column: str, bad_value: str) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {
        "check_name": "outlier",
        "severity": "info",
        "run_id": f"check-test-{uuid.uuid4().hex[:8]}",
        "detected_at": _NOW,
        "detail": "{}",
        "message": "test",
    }
    params[column] = bad_value
    sql = """
        INSERT INTO quality_issue (
            check_name, severity, run_id, detected_at, detail, message
        ) VALUES (
            :check_name, :severity, :run_id, :detected_at, CAST(:detail AS jsonb), :message
        )
    """
    return sql, params


def _llm_response_insert(column: str, bad_value: str) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {
        "response_id": uuid.uuid4().hex,
        "run_id": f"check-test-{uuid.uuid4().hex[:8]}",
        "country_iso3": "ZZZ",
        "template_name": "test",
        "task_type": "country_narrative",
        "provider_id": "test",
        "model_id": "test",
        "content": "",
        "citations_used": "[]",
        "citations_available_count": 0,
        "ungrounded_claims": "[]",
        "grounding_score": 1.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "generated_at": _NOW,
    }
    params[column] = bad_value
    sql = """
        INSERT INTO llm_response (
            response_id, run_id, country_iso3, template_name, task_type,
            provider_id, model_id, content, citations_used,
            citations_available_count, ungrounded_claims, grounding_score,
            tokens_in, tokens_out, latency_ms, generated_at
        ) VALUES (
            :response_id, :run_id, :country_iso3, :template_name, :task_type,
            :provider_id, :model_id, :content, CAST(:citations_used AS jsonb),
            :citations_available_count, CAST(:ungrounded_claims AS jsonb), :grounding_score,
            :tokens_in, :tokens_out, :latency_ms, :generated_at
        )
    """
    return sql, params


def _alert_record_insert(column: str, bad_value: str) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {
        "country_iso3": "ZZZ",
        "run_id": f"check-test-{uuid.uuid4().hex[:8]}",
        "evaluated_at": _NOW,
        "composite": None,
        "coverage_fraction": 0.0,
        "raw_tier": "WATCH",
        "effective_tier": "WATCH",
        "streak_length": 0,
        "velocity": None,
        "modifiers_applied": [],
    }
    params[column] = bad_value
    sql = """
        INSERT INTO alert_record (
            country_iso3, run_id, evaluated_at, composite, coverage_fraction,
            raw_tier, effective_tier, streak_length, velocity, modifiers_applied
        ) VALUES (
            :country_iso3, :run_id, :evaluated_at, :composite, :coverage_fraction,
            :raw_tier, :effective_tier, :streak_length, :velocity, :modifiers_applied
        )
    """
    return sql, params


_CASES = [
    pytest.param(
        "pipeline_run", "status", "RUNNING", _pipeline_run_insert, id="pipeline_run.status"
    ),
    pytest.param(
        "pipeline_run", "run_type", "weekly", _pipeline_run_insert, id="pipeline_run.run_type"
    ),
    pytest.param(
        "quality_issue", "severity", "INFO", _quality_issue_insert, id="quality_issue.severity"
    ),
    pytest.param(
        "llm_response", "task_type", "bogus", _llm_response_insert, id="llm_response.task_type"
    ),
    pytest.param(
        "alert_record", "raw_tier", "watch", _alert_record_insert, id="alert_record.raw_tier"
    ),
    pytest.param(
        "alert_record",
        "effective_tier",
        "watch",
        _alert_record_insert,
        id="alert_record.effective_tier",
    ),
]


@pytest.fixture(autouse=True)
async def _wipe_check_test_rows() -> None:
    async with session_scope() as session:
        await session.execute(
            delete(PipelineRunRow).where(PipelineRunRow.run_id.like("check-test-%"))
        )
        await session.execute(
            delete(QualityIssueRow).where(QualityIssueRow.run_id.like("check-test-%"))
        )
        await session.execute(
            delete(LLMResponseRow).where(LLMResponseRow.run_id.like("check-test-%"))
        )
        await session.execute(
            delete(AlertRecordRow).where(AlertRecordRow.run_id.like("check-test-%"))
        )


@pytest.mark.parametrize(("table", "column", "bad_value", "builder"), _CASES)
async def test_check_constraint_rejects_bad_value(
    table: str,
    column: str,
    bad_value: str,
    builder: object,
) -> None:
    sql, params = builder(column, bad_value)  # type: ignore[operator]

    with pytest.raises(IntegrityError) as excinfo:
        async with session_scope() as session:
            await session.execute(text(sql), params)

    msg = str(excinfo.value).lower()
    assert "check" in msg or "violates" in msg, (
        f"Expected CHECK violation for {table}.{column}={bad_value!r}, got: {excinfo.value}"
    )
