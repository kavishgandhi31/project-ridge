"""Create llm_response table.

Persists every LLM generation with its citations, grounding score,
and provider/template metadata. Regular table (not hypertable) --
volume is low (~183 narratives/day + ~0-10 rationales/day).

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_response",
        sa.Column("response_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("country_iso3", sa.String(3), nullable=False),
        sa.Column("template_name", sa.Text, nullable=False),
        sa.Column("task_type", sa.Text, nullable=False),
        sa.Column("provider_id", sa.Text, nullable=False),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations_used", JSONB, nullable=False),
        sa.Column("citations_available_count", sa.Integer, nullable=False),
        sa.Column("ungrounded_claims", JSONB, nullable=False),
        sa.Column("grounding_score", sa.Double, nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False),
        sa.Column("tokens_out", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("generated_at", TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_index("llm_response_run_idx", "llm_response", ["run_id"])
    op.create_index(
        "llm_response_country_idx",
        "llm_response",
        ["country_iso3", sa.text("generated_at DESC")],
    )
    op.create_index("llm_response_template_idx", "llm_response", ["template_name"])


def downgrade() -> None:
    op.drop_index("llm_response_template_idx", table_name="llm_response")
    op.drop_index("llm_response_country_idx", table_name="llm_response")
    op.drop_index("llm_response_run_idx", table_name="llm_response")
    op.drop_table("llm_response")
