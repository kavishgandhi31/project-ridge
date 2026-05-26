"""Lowercase alert_record.raw_tier / effective_tier values.

Aligns AlertTier with the four other StrEnums (RunStatus, RunType,
TaskType, IssueSeverity) which all use lowercase string values. The
uppercase outlier was inconsistent with the rest of the codebase and
with the JSON/REST convention used at the API boundary.

Steps:
1. Drop the two CHECK constraints added in 0010 (they pin the old
   uppercase values).
2. UPDATE existing rows to lowercase.
3. Recreate the CHECK constraints with the new lowercase values.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TIER_VALUES = ("watch", "alert", "escalate")
_OLD_TIER_VALUES = ("WATCH", "ALERT", "ESCALATE")


def _in_clause(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint("alert_record_raw_tier_ck", "alert_record", type_="check")
    op.drop_constraint("alert_record_effective_tier_ck", "alert_record", type_="check")

    op.execute(
        "UPDATE alert_record SET raw_tier = lower(raw_tier) WHERE raw_tier IS NOT NULL"
    )
    op.execute(
        "UPDATE alert_record SET effective_tier = lower(effective_tier) "
        "WHERE effective_tier IS NOT NULL"
    )

    op.create_check_constraint(
        "alert_record_raw_tier_ck",
        "alert_record",
        f"raw_tier IS NULL OR raw_tier IN ({_in_clause(_NEW_TIER_VALUES)})",
    )
    op.create_check_constraint(
        "alert_record_effective_tier_ck",
        "alert_record",
        f"effective_tier IS NULL OR effective_tier IN ({_in_clause(_NEW_TIER_VALUES)})",
    )


def downgrade() -> None:
    op.drop_constraint("alert_record_effective_tier_ck", "alert_record", type_="check")
    op.drop_constraint("alert_record_raw_tier_ck", "alert_record", type_="check")

    op.execute(
        "UPDATE alert_record SET raw_tier = upper(raw_tier) WHERE raw_tier IS NOT NULL"
    )
    op.execute(
        "UPDATE alert_record SET effective_tier = upper(effective_tier) "
        "WHERE effective_tier IS NOT NULL"
    )

    op.create_check_constraint(
        "alert_record_raw_tier_ck",
        "alert_record",
        f"raw_tier IS NULL OR raw_tier IN ({_in_clause(_OLD_TIER_VALUES)})",
    )
    op.create_check_constraint(
        "alert_record_effective_tier_ck",
        "alert_record",
        f"effective_tier IS NULL OR effective_tier IN ({_in_clause(_OLD_TIER_VALUES)})",
    )
