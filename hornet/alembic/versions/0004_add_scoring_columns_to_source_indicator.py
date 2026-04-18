"""Add dimension, concept, and global_signal columns to source_indicator.

These columns support the Phase 3 scoring engine:
- ``dimension`` maps an indicator to one of the four scoring dimensions
  (growth_momentum, external_balance, monetary_stance, risk_sentiment).
  Nullable because some indicators (e.g. GDELT headlines) do not
  participate in scoring.
- ``concept`` groups indicators measuring the same economic concept
  (e.g. 'cpi', 'gdp') for deduplication within a frequency tier.
  Nullable for the same reason as dimension.
- ``global_signal`` marks indicators that apply to ALL countries
  regardless of their countries_iso3 (e.g. US Treasury yields, VIX).
  Observations are stored with their actual origin country (USA);
  the scoring engine includes them when scoring any country.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_indicator",
        sa.Column("dimension", sa.Text, nullable=True),
    )
    op.add_column(
        "source_indicator",
        sa.Column("concept", sa.Text, nullable=True),
    )
    op.add_column(
        "source_indicator",
        sa.Column(
            "global_signal",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Partial index for scoring queries: "all scored indicators for
    # dimension X" filtered to enabled rows with a non-null dimension.
    op.create_index(
        "source_indicator_dimension_idx",
        "source_indicator",
        ["dimension"],
        postgresql_where=sa.text("dimension IS NOT NULL AND enabled"),
    )


def downgrade() -> None:
    op.drop_index(
        "source_indicator_dimension_idx",
        table_name="source_indicator",
    )
    op.drop_column("source_indicator", "global_signal")
    op.drop_column("source_indicator", "concept")
    op.drop_column("source_indicator", "dimension")
