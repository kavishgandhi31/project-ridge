"""Read-side accessors over the ``source_indicator`` registry table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ridge.db.models.source_indicator import SourceIndicatorRow
from ridge.domain.source import SourceIndicatorSpec


async def list_source_indicators(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    indicator_code: str | None = None,
    enabled_only: bool = True,
) -> list[SourceIndicatorSpec]:
    """Return registered source-indicator mappings as domain objects.

    Filters compose:

    * ``source_id`` — only this source (matches the indexed query path
      "list all live series for source X" that adapters use at startup)
    * ``indicator_code`` — only this canonical indicator (matches the
      "which sources cover this concept" query that Phase 4 cross-source
      validation will need)
    * ``enabled_only`` — filter out soft-disabled rows. Defaults to True
      because every normal code path wants live series only.
    """
    stmt = select(SourceIndicatorRow).order_by(
        SourceIndicatorRow.source_id,
        SourceIndicatorRow.source_native_code,
    )
    if source_id is not None:
        stmt = stmt.where(SourceIndicatorRow.source_id == source_id)
    if indicator_code is not None:
        stmt = stmt.where(SourceIndicatorRow.indicator_code == indicator_code)
    if enabled_only:
        stmt = stmt.where(SourceIndicatorRow.enabled.is_(True))
    result = await session.execute(stmt)
    return [row.to_domain() for row in result.scalars().all()]
