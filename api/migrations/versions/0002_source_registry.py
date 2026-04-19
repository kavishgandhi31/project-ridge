"""Create source_indicator and country registry tables.

Retires the hardcoded ``_PILOT_SERIES`` / ``_INDICATORS`` dicts that
shipped with the Phase 1 FRED and WorldBank adapters. After this
migration the registry lives in Postgres; the seed loader populates
it from YAML files under ``src/hornet/seeds/data/``.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP

# Valid frequency tiers. Matches domain.observation.Frequency Literal.
# Enforced via CHECK constraint so manual SQL inserts cannot corrupt
# the frequency column.
_VALID_FREQUENCIES = ("daily", "weekly", "monthly", "quarterly", "annual", "forecast")

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # country: authoritative registry of every country Hornet tracks.
    # iso3 is the canonical identity used everywhere else; iso2 is kept
    # as a unique secondary column so the WorldBank adapter can resolve
    # its native ISO2 responses without a hardcoded map.
    op.create_table(
        "country",
        sa.Column("iso3", sa.String(3), nullable=False),
        sa.Column("iso2", sa.String(2), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("region", sa.Text, nullable=True),
        sa.Column("income_group", sa.Text, nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("iso3", name="country_pk"),
        sa.UniqueConstraint("iso2", name="country_iso2_key"),
    )

    # source_indicator: registry of every (source_id, source_native_code)
    # -> canonical indicator_code mapping. Composite PK because a native
    # code is unique within a source but not across sources.
    op.create_table(
        "source_indicator",
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("source_native_code", sa.Text, nullable=False),
        sa.Column("indicator_code", sa.Text, nullable=False),
        sa.Column("frequency", sa.Text, nullable=False),
        sa.Column("countries_iso3", ARRAY(sa.Text), nullable=False),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("unit", sa.Text, nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "source_id",
            "source_native_code",
            name="source_indicator_pk",
        ),
        sa.CheckConstraint(
            sa.column("frequency").in_(_VALID_FREQUENCIES),
            name="source_indicator_frequency_check",
        ),
    )

    # Partial indexes on enabled rows. Two query patterns dominate:
    # (1) "all live series for source X" at adapter startup,
    # (2) "all sources mapped to canonical indicator X" for
    # Phase 4 cross-source validation. Both filter on enabled=true,
    # so partial indexes are cheaper than full ones on the whole table.
    op.create_index(
        "source_indicator_source_enabled_idx",
        "source_indicator",
        ["source_id"],
        postgresql_where=sa.text("enabled"),
    )
    op.create_index(
        "source_indicator_indicator_enabled_idx",
        "source_indicator",
        ["indicator_code"],
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.drop_index(
        "source_indicator_indicator_enabled_idx",
        table_name="source_indicator",
    )
    op.drop_index(
        "source_indicator_source_enabled_idx",
        table_name="source_indicator",
    )
    op.drop_table("source_indicator")
    op.drop_table("country")
