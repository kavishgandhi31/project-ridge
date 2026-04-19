"""Create observations table as a TimescaleDB hypertable.

Revision ID: 0001
Revises:
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable TimescaleDB. IF NOT EXISTS makes reruns safe.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # The observations table. Declared explicitly here (rather than
    # relying on autogenerate) so the migration is self-contained and
    # doesn't drift when the SQLAlchemy model evolves.
    op.create_table(
        "observations",
        sa.Column("country_iso3", sa.String(3), nullable=False),
        sa.Column("indicator_code", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("value", sa.Double, nullable=False),
        sa.Column("frequency", sa.Text, nullable=False),
        sa.Column("vintage", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ingested_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "quality_flags",
            ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.PrimaryKeyConstraint(
            "country_iso3",
            "indicator_code",
            "source_id",
            "date",
            "vintage",
            name="observations_pk",
        ),
    )

    # Secondary index for the "latest value for (country, indicator)"
    # query pattern, which does not filter on vintage.
    op.create_index(
        "observations_country_indicator_date_idx",
        "observations",
        ["country_iso3", "indicator_code", "date"],
    )

    # Convert the plain table into a TimescaleDB hypertable partitioned
    # on `date`. Default chunk interval is 7 days which is fine for now;
    # can be retuned later without a data migration.
    op.execute(
        "SELECT create_hypertable("
        "'observations', 'date', "
        "if_not_exists => TRUE, "
        "migrate_data => TRUE"
        ")"
    )


def downgrade() -> None:
    # Dropping the table removes the hypertable association as well —
    # hypertables in Timescale are regular Postgres tables with extra
    # metadata. We do NOT drop the extension; other migrations may need it.
    op.drop_index(
        "observations_country_indicator_date_idx",
        table_name="observations",
    )
    op.drop_table("observations")
