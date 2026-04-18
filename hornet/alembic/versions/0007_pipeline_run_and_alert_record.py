"""Create pipeline_run and alert_record tables.

pipeline_run replaces v1's JSON/pickle stage snapshots with a
DB-backed audit trail keyed on run_id. Tracks per-stage completion,
timing, and tier counts.

alert_record persists tier assignments per country per run, enabling
streak queries and velocity computation without external history
injection.

Both are regular tables (not hypertables) -- low volume.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- pipeline_run ---
    op.create_table(
        "pipeline_run",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("run_type", sa.Text, nullable=False),
        sa.Column("started_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "stages_completed",
            ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("n_countries_scored", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_escalate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_alert", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_watch", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    op.create_index("pipeline_run_status_idx", "pipeline_run", ["status"])
    op.create_index(
        "pipeline_run_started_idx",
        "pipeline_run",
        [sa.text("started_at DESC")],
    )

    # --- alert_record ---
    op.create_table(
        "alert_record",
        sa.Column("country_iso3", sa.String(3), nullable=False),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("evaluated_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("composite", sa.Double, nullable=True),
        sa.Column("coverage_fraction", sa.Double, nullable=False),
        sa.Column("raw_tier", sa.Text, nullable=True),
        sa.Column("effective_tier", sa.Text, nullable=True),
        sa.Column("streak_length", sa.Integer, nullable=False, server_default="0"),
        sa.Column("velocity", sa.Double, nullable=True),
        sa.Column(
            "modifiers_applied",
            ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.PrimaryKeyConstraint(
            "country_iso3",
            "run_id",
            name="alert_record_pk",
        ),
    )

    op.create_index("alert_record_run_idx", "alert_record", ["run_id"])
    op.create_index(
        "alert_record_country_eval_idx",
        "alert_record",
        ["country_iso3", sa.text("evaluated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("alert_record_country_eval_idx", table_name="alert_record")
    op.drop_index("alert_record_run_idx", table_name="alert_record")
    op.drop_table("alert_record")

    op.drop_index("pipeline_run_started_idx", table_name="pipeline_run")
    op.drop_index("pipeline_run_status_idx", table_name="pipeline_run")
    op.drop_table("pipeline_run")
