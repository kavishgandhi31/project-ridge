"""Add observations_latest_vintage_idx; drop now-redundant country/indicator/date index.

The new index supports the DISTINCT ON pattern that
list_observations_for_scoring and list_all_observations_for_quality
use to pick the latest vintage per (country, indicator, source, date)
without pulling all vintages into Python.

The old (country_iso3, indicator_code, date) index is dropped because
every query that previously used it is either covered by the new
index's leading prefix or co-filters on source_id (where the new
index is strictly better).

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "observations_latest_vintage_idx",
        "observations",
        [
            "country_iso3",
            "indicator_code",
            "source_id",
            "date",
            sa.text("vintage DESC"),
        ],
    )
    op.drop_index(
        "observations_country_indicator_date_idx",
        table_name="observations",
    )


def downgrade() -> None:
    op.create_index(
        "observations_country_indicator_date_idx",
        "observations",
        ["country_iso3", "indicator_code", "date"],
    )
    op.drop_index(
        "observations_latest_vintage_idx",
        table_name="observations",
    )
