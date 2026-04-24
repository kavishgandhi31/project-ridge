"""QualityIssue domain type -- one quality problem detected by a check.

Quality checks produce these records instead of mutating observations
(v1 mutated DataFrames in-place). Issues are persisted in the
``quality_issue`` table and displayed in the digest/dashboard.
"""

from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IssueSeverity(StrEnum):
    """Severity levels for quality issues.

    INFO: FYI, no action needed (e.g. revision detected).
    WARNING: investigate when convenient (e.g. flatline, stale series).
    CRITICAL: blocks scoring or requires immediate action (e.g. outlier).
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class QualityIssue(BaseModel):
    """One quality problem detected by a check function.

    Each check function returns a list of these. The runner persists
    them to the ``quality_issue`` table grouped by ``run_id``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_name: str = Field(
        ...,
        description="Which check produced this issue (e.g. 'outlier', 'flatline').",
    )
    severity: IssueSeverity = Field(
        ...,
        description="How urgent this issue is.",
    )
    country_iso3: str | None = Field(
        default=None,
        description="Country this issue applies to. None for global checks.",
    )
    indicator_code: str | None = Field(
        default=None,
        description="Indicator this issue applies to. None for country-level checks.",
    )
    source_id: str | None = Field(
        default=None,
        description="Source this issue applies to. None for cross-source checks.",
    )
    run_id: str = Field(
        ...,
        description="UUID grouping all issues from one quality run.",
    )
    detected_at: datetime.datetime = Field(
        ...,
        description="When the issue was detected.",
    )
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Check-specific payload (sigma distance, values, thresholds, etc.).",
    )
    message: str = Field(
        ...,
        description="Human-readable summary of the issue.",
    )
