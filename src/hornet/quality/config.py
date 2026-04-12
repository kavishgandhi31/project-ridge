"""QualityConfig -- thresholds for all 10 quality controls.

Loaded from ``quality_config.yaml`` at runner construction time.
Same pattern as ScoringConfig: frozen Pydantic, YAML seed, DB
persistence deferred to a future phase.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QualityConfig(BaseModel):
    """Immutable quality configuration with v1-matching defaults.

    Every threshold from v1's ``monitoring:`` block in setting.yaml
    is represented here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Control #1: Outlier detection
    outlier_sigma: float = Field(
        default=4.0,
        description="Standard deviations before flagging as outlier.",
    )
    outlier_min_history: int = Field(
        default=20,
        description="Minimum observations to compute reliable outlier statistics.",
    )

    # Control #2: Series audit
    series_audit_threshold: float = Field(
        default=0.0,
        description="Gap fraction threshold (0.0 = flag any missing series).",
    )

    # Control #3: Cross-source validation
    cross_source_threshold: float = Field(
        default=0.02,
        description="Maximum allowed divergence fraction between sources (2%).",
    )

    # Control #4: Score stability
    score_jump_threshold: float = Field(
        default=1.0,
        description="Maximum composite score change between runs before flagging.",
    )
    coverage_stability_tolerance: float = Field(
        default=0.10,
        description="Coverage must be within this tolerance to be considered stable.",
    )

    # Control #5: Revision detection
    revision_lookback: int = Field(
        default=12,
        description="How many trailing observations to check for revisions.",
    )

    # Control #6: Flatline detection
    flatline_min_repeats: int = Field(
        default=10,
        description="Minimum consecutive identical values to flag as flatline.",
    )
    flatline_tolerance: float = Field(
        default=1e-8,
        description="Floating-point tolerance for value comparison.",
    )

    # Control #7: Structural break detection
    break_window: int = Field(
        default=12,
        description="Observations per window for split-window comparison.",
    )
    break_sigma: float = Field(
        default=2.0,
        description="Sigma threshold for flagging regime shift.",
    )

    # Control #8: Date consistency
    max_source_date_lag_days: int = Field(
        default=30,
        description="Maximum allowed date lag between sources for same country.",
    )

    # Control #9: Backfill detection
    backfill_threshold: float = Field(
        default=0.25,
        description="Coverage gain fraction threshold (25% = suspicious).",
    )

    # Control #10: Source staleness
    staleness_days: dict[str, int] = Field(
        default_factory=lambda: {
            "daily": 7,
            "weekly": 14,
            "monthly": 90,
            "quarterly": 150,
            "annual": 400,
            "forecast": 200,
        },
        description="Max age in days per frequency before flagging as stale.",
    )
    failure_threshold: int = Field(
        default=3,
        description="Consecutive fetch failures before flagging a source.",
    )
    coverage_drop_threshold: float = Field(
        default=0.25,
        description="Coverage drop fraction threshold (25% = flag).",
    )
