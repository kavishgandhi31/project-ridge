"""Add CHECK constraints to enum-string columns.

Mirrors the StrEnum values in the domain layer so the database
rejects bad inserts even if a future caller bypasses the ORM. The
only column already protected this way is ``source_indicator.frequency``
(migration 0002); this migration extends that pattern to the rest.

AlertTier values are uppercase; every other StrEnum here is lowercase.
The asymmetry mirrors current domain code -- a follow-up to normalize
AlertTier to lowercase is logged in docs/CLEANUP_PLAN.md (Pass 4).

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RUN_STATUS_VALUES = ("running", "completed", "failed")
_RUN_TYPE_VALUES = ("daily", "manual", "backfill")
_ISSUE_SEVERITY_VALUES = ("info", "warning", "critical")
_TASK_TYPE_VALUES = (
    "country_narrative",
    "alert_rationale",
    "interactive_query",
    "classification",
)
_ALERT_TIER_VALUES = ("WATCH", "ALERT", "ESCALATE")


def _in_clause(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_check_constraint(
        "pipeline_run_status_ck",
        "pipeline_run",
        f"status IN ({_in_clause(_RUN_STATUS_VALUES)})",
    )
    op.create_check_constraint(
        "pipeline_run_run_type_ck",
        "pipeline_run",
        f"run_type IN ({_in_clause(_RUN_TYPE_VALUES)})",
    )
    op.create_check_constraint(
        "quality_issue_severity_ck",
        "quality_issue",
        f"severity IN ({_in_clause(_ISSUE_SEVERITY_VALUES)})",
    )
    op.create_check_constraint(
        "llm_response_task_type_ck",
        "llm_response",
        f"task_type IN ({_in_clause(_TASK_TYPE_VALUES)})",
    )
    op.create_check_constraint(
        "alert_record_raw_tier_ck",
        "alert_record",
        f"raw_tier IS NULL OR raw_tier IN ({_in_clause(_ALERT_TIER_VALUES)})",
    )
    op.create_check_constraint(
        "alert_record_effective_tier_ck",
        "alert_record",
        f"effective_tier IS NULL OR effective_tier IN ({_in_clause(_ALERT_TIER_VALUES)})",
    )


def downgrade() -> None:
    op.drop_constraint("alert_record_effective_tier_ck", "alert_record", type_="check")
    op.drop_constraint("alert_record_raw_tier_ck", "alert_record", type_="check")
    op.drop_constraint("llm_response_task_type_ck", "llm_response", type_="check")
    op.drop_constraint("quality_issue_severity_ck", "quality_issue", type_="check")
    op.drop_constraint("pipeline_run_run_type_ck", "pipeline_run", type_="check")
    op.drop_constraint("pipeline_run_status_ck", "pipeline_run", type_="check")
