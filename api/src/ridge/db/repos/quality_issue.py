"""Read/write accessors for the quality_issue table."""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ridge.db.models.quality_issue import QualityIssueRow
from ridge.quality.issue import QualityIssue


async def insert_quality_issues(
    session: AsyncSession,
    issues: Sequence[QualityIssue],
) -> int:
    """Bulk-insert quality issues. Returns the number of rows inserted."""
    if not issues:
        return 0

    rows = [QualityIssueRow.from_domain(issue) for issue in issues]
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def list_quality_issues(
    session: AsyncSession,
    *,
    run_id: str | None = None,
    check_name: str | None = None,
    country_iso3: str | None = None,
    since: datetime.datetime | None = None,
    limit: int = 500,
) -> list[QualityIssue]:
    """Query quality issues with optional filters."""
    stmt = select(QualityIssueRow).order_by(QualityIssueRow.detected_at.desc()).limit(limit)
    if run_id is not None:
        stmt = stmt.where(QualityIssueRow.run_id == run_id)
    if check_name is not None:
        stmt = stmt.where(QualityIssueRow.check_name == check_name)
    if country_iso3 is not None:
        stmt = stmt.where(QualityIssueRow.country_iso3 == country_iso3)
    if since is not None:
        stmt = stmt.where(QualityIssueRow.detected_at >= since)

    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]
