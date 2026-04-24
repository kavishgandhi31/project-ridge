"""Scoring domain types -- configuration, dimension scores, and results.

These are the canonical shapes the scoring engine reads and produces.
All are frozen Pydantic models with zero I/O, following the same
pattern as Observation and EventRecord.

ScoringConfig is loaded from a YAML seed file (scoring_config.yaml)
in Phase 3. A future phase will persist it in a DB table so it can
be modified at runtime via the API.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DimensionName = Literal[
    "growth_momentum",
    "external_balance",
    "monetary_stance",
    "risk_sentiment",
]
"""The four macro scoring dimensions.

Each country gets a score on each dimension (or None if data is
insufficient). The composite is a weighted average across present
dimensions.
"""

ALL_DIMENSIONS: tuple[DimensionName, ...] = (
    "growth_momentum",
    "external_balance",
    "monetary_stance",
    "risk_sentiment",
)


class ScoringConfig(BaseModel):
    """Immutable scoring configuration.

    Loaded from ``scoring_config.yaml`` at engine construction time.
    Every tunable knob from v1's ``setting.yaml`` scoring block is
    represented here as a typed field with a v1-matching default.

    Dimension weights must sum to 1.0 (enforced by validator).
    Frequency weights, staleness gates, and EWM halflifes are keyed
    by the same frequency tier names used in ``Observation.frequency``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension_weights: dict[str, float] = Field(
        ...,
        description=(
            "Weight per dimension for composite scoring. Keys must be "
            "DimensionName values. Must sum to 1.0."
        ),
    )
    scale_min: float = Field(
        default=-3.0,
        description="Lower bound for clamped dimension scores.",
    )
    scale_max: float = Field(
        default=3.0,
        description="Upper bound for clamped dimension scores.",
    )
    frequency_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "daily": 1.0,
            "weekly": 1.0,
            "monthly": 0.8,
            "quarterly": 0.5,
            "annual": 0.3,
            "forecast": 0.4,
        },
        description="Per-frequency-tier weight for tier-weighted scoring.",
    )
    staleness_gates: dict[str, int] = Field(
        default_factory=lambda: {
            "daily": 14,
            "weekly": 30,
            "monthly": 120,
            "quarterly": 270,
            "annual": 730,
            "forecast": 365,
        },
        description="Max age in days per frequency tier before exclusion.",
    )
    zscore_method: Literal["ewm", "full"] = Field(
        default="ewm",
        description="Z-score computation method: 'ewm' (recency-weighted) or 'full' (whole history).",
    )
    ewm_halflife: dict[str, int] = Field(
        default_factory=lambda: {
            "daily": 252,
            "weekly": 52,
            "monthly": 12,
            "quarterly": 8,
            "annual": 5,
            "forecast": 4,
        },
        description="EWM halflife in observations per frequency tier.",
    )
    composite_strategy: Literal["renormalize", "zero_pad"] = Field(
        default="renormalize",
        description="How missing dimensions are handled in composite scoring.",
    )
    coverage_confidence: Literal["none", "linear", "sqrt"] = Field(
        default="sqrt",
        description="Coverage-confidence multiplier for renormalize strategy.",
    )
    min_dimensions_for_composite: int = Field(
        default=2,
        description="Minimum present dimensions to produce a composite score.",
    )
    news_heat_sigma: float = Field(
        default=2.0,
        description="GDELT volume sigma threshold for news heat indicator.",
    )
    min_observations: int = Field(
        default=12,
        description="Minimum observations needed for a meaningful z-score.",
    )
    momentum_window: int = Field(
        default=30,
        description="Rolling window (in observations) for price momentum z-score.",
    )

    @model_validator(mode="after")
    def _check_weights_sum(self) -> ScoringConfig:
        total = sum(self.dimension_weights.values())
        if abs(total - 1.0) > 1e-6:
            msg = f"dimension_weights must sum to 1.0, got {total:.6f}"
            raise ValueError(msg)
        return self


class DimensionScore(BaseModel):
    """Score for a single dimension of a single country.

    Carries metadata about the data coverage that produced the score,
    which is useful for diagnostics and for the coverage-confidence
    multiplier in composite scoring.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str = Field(
        ...,
        description="Dimension name (e.g. 'growth_momentum').",
    )
    value: float | None = Field(
        ...,
        description="Clamped score in [scale_min, scale_max], or None if insufficient data.",
    )
    n_series_used: int = Field(
        default=0,
        description="Number of series that contributed z-scores.",
    )
    n_series_stale: int = Field(
        default=0,
        description="Number of series excluded by the staleness gate.",
    )
    n_concepts: int = Field(
        default=0,
        description="Number of distinct concepts after deduplication.",
    )


class NewsHeat(BaseModel):
    """Standalone news heat indicator from GDELT volume data.

    Not folded into risk_sentiment scoring -- this is a separate
    signal displayed in the digest for situational awareness.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sigma: float = Field(
        ...,
        description="Number of standard deviations above mean volume.",
    )
    volume_ratio: float = Field(
        ...,
        description="Latest volume divided by mean volume.",
    )


class ScoreResult(BaseModel):
    """Complete scoring output for one country in one scoring run.

    This is the domain type that the scoring engine produces and that
    gets persisted to the ``score_result`` hypertable. The API and
    digest layers consume these.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 3166-1 alpha-3 country code.",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="UUID string grouping all countries from one batch scoring run.",
    )
    scored_at: datetime.datetime = Field(
        ...,
        description="Timestamp of the scoring run.",
    )
    dimensions: dict[str, DimensionScore] = Field(
        ...,
        description="Score per dimension. Keys are DimensionName values.",
    )
    composite: float | None = Field(
        ...,
        description="Weighted composite score, or None if coverage is insufficient.",
    )
    news_heat: NewsHeat | None = Field(
        default=None,
        description="News heat indicator, or None if GDELT volume is normal.",
    )
    coverage_fraction: float = Field(
        ...,
        description="Fraction of dimensions with non-None scores (0.0 to 1.0).",
    )
