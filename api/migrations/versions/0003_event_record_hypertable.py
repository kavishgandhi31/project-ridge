"""Create event_record table as a TimescaleDB hypertable.

Parallel storage to the observations hypertable, for news/sentiment
data from GDELT and GoogleNews that does not fit the numeric
Observation model.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_record",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("dedup_key", sa.Text, nullable=False),
        sa.Column("country_iso3", sa.String(3), nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("value", sa.Double, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ingested_at", TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("date", "dedup_key", name="event_record_pk"),
    )

    op.create_index(
        "event_record_country_type_date_idx",
        "event_record",
        ["country_iso3", "event_type", "date"],
    )
    op.create_index(
        "event_record_source_date_idx",
        "event_record",
        ["source_id", "date"],
    )

    op.execute(
        "SELECT create_hypertable("
        "'event_record', 'date', "
        "if_not_exists => TRUE, "
        "migrate_data => TRUE"
        ")"
    )


def downgrade() -> None:
    op.drop_index("event_record_source_date_idx", table_name="event_record")
    op.drop_index("event_record_country_type_date_idx", table_name="event_record")
    op.drop_table("event_record")
