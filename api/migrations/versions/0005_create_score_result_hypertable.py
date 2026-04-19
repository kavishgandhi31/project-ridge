"""Create score_result hypertable for scoring output persistence.

Each row represents one country's complete scoring output (all
dimension scores + composite + news heat) for one scoring run.
The run_id groups all countries scored in the same batch.

TimescaleDB hypertable partitioned on scored_at for efficient
time-range queries ("scores for the last 30 days").

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "score_result",
        sa.Column("country_iso3", sa.String(3), nullable=False),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("scored_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("dimensions", JSONB, nullable=False),
        sa.Column("composite", sa.Double, nullable=True),
        sa.Column("news_heat", JSONB, nullable=True),
        sa.Column("coverage_fraction", sa.Double, nullable=False),
        sa.PrimaryKeyConstraint(
            "country_iso3",
            "scored_at",
            name="score_result_pk",
        ),
    )

    op.create_index("score_result_run_idx", "score_result", ["run_id"])
    op.create_index(
        "score_result_country_idx",
        "score_result",
        ["country_iso3", sa.text("scored_at DESC")],
    )

    # Convert to TimescaleDB hypertable
    op.execute(
        "SELECT create_hypertable('score_result', 'scored_at', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )


def downgrade() -> None:
    op.drop_index("score_result_country_idx", table_name="score_result")
    op.drop_index("score_result_run_idx", table_name="score_result")
    op.drop_table("score_result")
