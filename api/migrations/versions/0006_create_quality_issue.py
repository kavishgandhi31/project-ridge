"""Create quality_issue table for quality layer output.

Stores issues detected by the quality layer's 10 controls.
Regular table (not hypertable) since quality issues are lower
volume than observations and don't need time-series partitioning.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_issue",
        sa.Column(
            "id",
            sa.BigInteger,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("check_name", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("country_iso3", sa.String(3), nullable=True),
        sa.Column("indicator_code", sa.Text, nullable=True),
        sa.Column("source_id", sa.Text, nullable=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("detected_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
    )

    op.create_index("quality_issue_run_idx", "quality_issue", ["run_id"])
    op.create_index(
        "quality_issue_country_idx",
        "quality_issue",
        ["country_iso3", sa.text("detected_at DESC")],
    )
    op.create_index(
        "quality_issue_check_idx",
        "quality_issue",
        ["check_name", sa.text("detected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("quality_issue_check_idx", table_name="quality_issue")
    op.drop_index("quality_issue_country_idx", table_name="quality_issue")
    op.drop_index("quality_issue_run_idx", table_name="quality_issue")
    op.drop_table("quality_issue")
