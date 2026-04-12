"""AlertConfig -- thresholds and escalation modifier parameters.

Loaded from ``alert_config.yaml`` at runner construction time.
Same pattern as ScoringConfig and QualityConfig: frozen Pydantic
model with v1-matching defaults, YAML seed, DB persistence deferred
to a future phase.

v1 defaults (from setting.yaml and scorecard.py):
    WATCH >= 1.0, ALERT >= 1.5, ESCALATE >= 2.0
    streak_required = 2
    velocity_threshold = 0.5
    min_coverage_for_escalate = 0.5
    max_daily_escalations = 10
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlertConfig(BaseModel):
    """Immutable alert configuration with v1-matching defaults.

    Thresholds are applied to ``abs(composite)`` -- both positive
    (improving) and negative (deteriorating) composites are evaluated
    the same way for tier assignment. The escalation modifiers then
    refine the raw tier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Tier thresholds (applied to abs(composite))
    watch_threshold: float = Field(
        default=1.0,
        description="Minimum |composite| for WATCH tier.",
    )
    alert_threshold: float = Field(
        default=1.5,
        description="Minimum |composite| for ALERT tier.",
    )
    escalate_threshold: float = Field(
        default=2.0,
        description="Minimum |composite| for ESCALATE tier (before modifiers).",
    )

    # Coverage gate
    min_coverage_for_escalate: float = Field(
        default=0.5,
        description=(
            "Minimum coverage_fraction to allow ESCALATE. Countries below "
            "this cap at ALERT. Prevents spending Claude API calls on thin data."
        ),
    )

    # Streak requirement
    streak_required: int = Field(
        default=2,
        description=(
            "Consecutive prior runs at ALERT or above required before "
            "ESCALATE is allowed. Prevents single-run spikes from triggering "
            "expensive deep analysis."
        ),
    )

    # Velocity boost
    velocity_threshold: float = Field(
        default=0.5,
        description=(
            "Minimum |delta(composite)| between consecutive runs to trigger "
            "a one-level tier promotion. Only applies to deteriorating "
            "(negative composite) countries."
        ),
    )

    # Dispatch limit
    max_daily_escalations: int = Field(
        default=10,
        description=(
            "Maximum countries that can be dispatched at ESCALATE tier per "
            "run. Excess are downgraded to ALERT. Cost control for Claude API."
        ),
    )

    @model_validator(mode="after")
    def _check_threshold_order(self) -> AlertConfig:
        """Enforce watch < alert < escalate ordering."""
        if not (self.watch_threshold < self.alert_threshold < self.escalate_threshold):
            msg = (
                f"Thresholds must be strictly ordered: "
                f"watch ({self.watch_threshold}) < "
                f"alert ({self.alert_threshold}) < "
                f"escalate ({self.escalate_threshold})"
            )
            raise ValueError(msg)
        return self
