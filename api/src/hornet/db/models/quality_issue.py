"""QualityIssueRow -- SQLAlchemy storage mirror of QualityIssue.

The ``quality_issue`` table stores issues detected by the quality
layer's 10 controls. Regular table (not hypertable) since quality
issues are lower volume than observations.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from hornet.db.base import Base
from hornet.quality.issue import IssueSeverity, QualityIssue


class QualityIssueRow(Base):
    """SQLAlchemy ORM row for the ``quality_issue`` table."""

    __tablename__ = "quality_issue"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    check_name: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    country_iso3: Mapped[str | None] = mapped_column(String(3), nullable=True)
    indicator_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("quality_issue_run_idx", "run_id"),
        Index("quality_issue_country_idx", "country_iso3", detected_at.desc()),
        Index("quality_issue_check_idx", "check_name", detected_at.desc()),
    )

    @classmethod
    def from_domain(cls, issue: QualityIssue) -> QualityIssueRow:
        """Construct a storage row from a QualityIssue domain object."""
        return cls(
            check_name=issue.check_name,
            severity=issue.severity.value,
            country_iso3=issue.country_iso3,
            indicator_code=issue.indicator_code,
            source_id=issue.source_id,
            run_id=issue.run_id,
            detected_at=issue.detected_at,
            detail=issue.detail,
            message=issue.message,
        )

    def to_domain(self) -> QualityIssue:
        """Convert this row back to a QualityIssue domain object."""
        return QualityIssue(
            check_name=self.check_name,
            severity=IssueSeverity(self.severity),
            country_iso3=self.country_iso3,
            indicator_code=self.indicator_code,
            source_id=self.source_id,
            run_id=self.run_id,
            detected_at=self.detected_at,
            detail=self.detail,
            message=self.message,
        )
