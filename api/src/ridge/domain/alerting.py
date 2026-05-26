"""Alerting domain types -- tier assignments, dispatch results, digest.

These are the canonical shapes the alert layer produces and that the
digest, API, and LLM layers consume. Pure Pydantic models with zero
I/O, following the same pattern as Observation and ScoreResult.

AlertTier uses StrEnum (matching IssueSeverity) so tier values are
type-safe in comparisons and serialize cleanly to DB/JSON.
"""

from __future__ import annotations

import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ridge.domain.scoring import ScoreResult
from ridge.quality.issue import QualityIssue


class AlertTier(StrEnum):
    """Three-level alert severity.

    WATCH:    logged silently, no action needed.
    ALERT:    included in daily digest for human review.
    ESCALATE: digest + queued for Claude API deep analysis.
    """

    WATCH = "watch"
    ALERT = "alert"
    ESCALATE = "escalate"


# Ordered weakest-to-strongest for promotion/comparison logic.
_TIER_ORDER: dict[AlertTier, int] = {
    AlertTier.WATCH: 1,
    AlertTier.ALERT: 2,
    AlertTier.ESCALATE: 3,
}


def tier_rank(tier: AlertTier) -> int:
    """Numeric rank for tier comparison (higher = more severe)."""
    return _TIER_ORDER[tier]


class TierAssignment(BaseModel):
    """Result of evaluating one country's composite against alert rules.

    Captures both the raw threshold-based tier and the effective tier
    after modifiers (coverage gate, streak, velocity) have been applied.
    The modifiers_applied tuple records which modifiers fired, enabling
    audit and digest rendering.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 3166-1 alpha-3 country code.",
    )
    country_name: str = Field(
        ...,
        description="Human-readable country name (for digest rendering).",
    )
    region: str | None = Field(
        default=None,
        description="World Bank region (for digest grouping).",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="UUID of the pipeline run that produced this assignment.",
    )
    evaluated_at: datetime.datetime = Field(
        ...,
        description="Timestamp of tier evaluation.",
    )
    composite: float | None = Field(
        ...,
        description="Composite score from ScoreResult.",
    )
    coverage_fraction: float = Field(
        ...,
        description="Fraction of dimensions with scores (0.0 to 1.0).",
    )
    raw_tier: AlertTier | None = Field(
        ...,
        description="Tier from threshold comparison alone (before modifiers).",
    )
    effective_tier: AlertTier | None = Field(
        ...,
        description="Tier after all modifiers applied.",
    )
    streak_length: int = Field(
        default=0,
        description="Consecutive prior runs at ALERT or above.",
    )
    velocity: float | None = Field(
        default=None,
        description="Absolute composite change from most recent prior run.",
    )
    modifiers_applied: tuple[str, ...] = Field(
        default=(),
        description=(
            "Which modifiers fired, e.g. 'coverage_gate', 'streak_hold', "
            "'velocity_boost'. Empty if raw tier was used as-is."
        ),
    )


class DispatchResult(BaseModel):
    """Tier assignments grouped by effective tier, sorted by severity.

    Produced by the dispatcher after routing all countries and
    enforcing the daily escalation limit. Consumed by the digest
    composer, API layer, and LLM alert-rationale generator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    escalate: tuple[TierAssignment, ...] = Field(
        default=(),
        description="Countries at ESCALATE tier (Claude API deep analysis).",
    )
    alert: tuple[TierAssignment, ...] = Field(
        default=(),
        description="Countries at ALERT tier (human review).",
    )
    watch: tuple[TierAssignment, ...] = Field(
        default=(),
        description="Countries at WATCH tier (logged silently).",
    )
    no_signal: tuple[TierAssignment, ...] = Field(
        default=(),
        description="Countries below WATCH threshold or with no composite.",
    )

    @property
    def has_escalations(self) -> bool:
        """True if any country hit the ESCALATE tier."""
        return len(self.escalate) > 0

    @property
    def actionable_count(self) -> int:
        """Number of countries needing attention (ALERT + ESCALATE)."""
        return len(self.escalate) + len(self.alert)

    @property
    def total(self) -> int:
        """Total number of countries evaluated."""
        return len(self.escalate) + len(self.alert) + len(self.watch) + len(self.no_signal)


class DigestSummary(BaseModel):
    """Header block for the structured digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Pipeline run that produced this digest.")
    generated_at: datetime.datetime = Field(
        ...,
        description="UTC timestamp of digest generation.",
    )
    total_scored: int = Field(..., description="Total countries evaluated.")
    n_escalate: int = Field(..., description="Countries at ESCALATE.")
    n_alert: int = Field(..., description="Countries at ALERT.")
    n_watch: int = Field(..., description="Countries at WATCH.")
    n_no_signal: int = Field(..., description="Countries below all thresholds.")


class Digest(BaseModel):
    """Structured daily digest -- the intermediate representation.

    This is the structured output of the digest composer. Downstream
    consumers (text renderer, API serializer, LLM rationale generator,
    Next.js frontend) each format it for their channel. Keeping this
    as a typed Pydantic model means every consumer gets the same data
    without re-querying the DB.

    The text renderer (``render_digest_text``) is the Phase 5 consumer.
    Phase 6 (LLM), Phase 7 (Streamlit), and Phase 8 (Next.js) will
    add their own renderers against this same type.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: DigestSummary = Field(
        ...,
        description="Header with counts and timestamps.",
    )
    dispatch: DispatchResult = Field(
        ...,
        description="Tier assignments grouped by effective tier.",
    )
    quality_issues: tuple[QualityIssue, ...] = Field(
        default=(),
        description="Quality issues from the current run.",
    )
    scores_by_country: dict[str, ScoreResult] = Field(
        default_factory=dict,
        description=(
            "ScoreResult keyed by iso3 for dimension detail in "
            "tier sections. The renderer joins on country_iso3."
        ),
    )
