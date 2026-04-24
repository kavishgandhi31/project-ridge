"""Series liveness checker -- detects discontinued or stale data sources.

Different from the scoring-time staleness gate (which skips stale
observations when computing z-scores). This runs at discover/ingest
time and checks whether a data series is still being published at
its expected frequency.

A series is "potentially discontinued" if its most recent observation
is older than a configurable multiple of its expected update interval.
For example, a daily FRED series with no data in the last 14 business
days is flagged. A monthly WorldBank series with no data in 4 months
is flagged.

This catches:
- FRED series that were retired or replaced with a new code
- yfinance tickers that were delisted or renamed
- WorldBank series with publication delays beyond normal lag
- API key issues that silently stop returning data

Usage:
    from ridge.quality.liveness import check_series_liveness

    issues = check_series_liveness(
        observations=recent_observations,
        indicator_specs=source_indicators,
        reference_date=today,
    )
    for issue in issues:
        print(f"{issue.indicator_code}: last seen {issue.last_date}, "
              f"expected every {issue.expected_frequency}")
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

import structlog
from pydantic import BaseModel, ConfigDict, Field

from ridge.domain.observation import Observation
from ridge.domain.source import SourceIndicatorSpec

logger = structlog.get_logger(__name__)


# Maximum age (in days) before a series is flagged as potentially stale.
# These are generous -- meant to catch discontinued series, not normal
# publication delays. For example, FRED daily series sometimes skip
# holidays and weekends, so 14 days allows for 2+ weeks of non-trading.
_LIVENESS_THRESHOLDS: dict[str, int] = {
    "daily": 14,
    "weekly": 30,
    "monthly": 120,
    "quarterly": 270,
    "annual": 1000,  # WorldBank/FRED annual series publish with ~2yr lag
    "forecast": 730,
}


class LivenessIssue(BaseModel):
    """A series that may be discontinued or experiencing data delivery issues."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(..., description="Which source adapter.")
    source_native_code: str = Field(..., description="The source's own series ID.")
    indicator_code: str = Field(..., description="Canonical Ridge indicator code.")
    expected_frequency: str = Field(..., description="How often this series should update.")
    last_date: datetime.date | None = Field(
        ...,
        description="Most recent observation date, or None if no observations exist.",
    )
    days_since_last: int | None = Field(
        ...,
        description="Calendar days since last observation, or None if never observed.",
    )
    threshold_days: int = Field(
        ...,
        description="The liveness threshold that was exceeded.",
    )
    message: str = Field(..., description="Human-readable summary.")


def check_series_liveness(
    observations: Sequence[Observation],
    indicator_specs: Sequence[SourceIndicatorSpec],
    *,
    reference_date: datetime.date | None = None,
    thresholds: dict[str, int] | None = None,
) -> list[LivenessIssue]:
    """Check all registered indicators for potential staleness.

    Compares the most recent observation date for each
    (source_id, indicator_code) pair against the expected update
    frequency. Series that haven't updated within the threshold
    are returned as LivenessIssue records.

    Parameters
    ----------
    observations:
        Recent observations to check. Should include at least the
        latest observation per indicator (the caller can pre-filter).
    indicator_specs:
        The full source_indicator registry (from YAML seed).
    reference_date:
        "Today" for age calculation. Defaults to UTC date.
    thresholds:
        Override liveness thresholds per frequency tier.
        Defaults to _LIVENESS_THRESHOLDS.

    Returns
    -------
    list[LivenessIssue]
        Issues for series that exceed their liveness threshold.
    """
    ref_date = reference_date or datetime.datetime.now(datetime.UTC).date()
    thresh = thresholds or _LIVENESS_THRESHOLDS

    # Build latest-date map: (source_id, indicator_code) -> max(date)
    latest_dates: dict[tuple[str, str], datetime.date] = {}
    for obs in observations:
        key = (obs.source_id, obs.indicator_code)
        existing = latest_dates.get(key)
        if existing is None or obs.date > existing:
            latest_dates[key] = obs.date

    issues: list[LivenessIssue] = []

    for spec in indicator_specs:
        if not spec.enabled:
            continue

        key = (spec.source_id, spec.indicator_code)
        threshold = thresh.get(spec.frequency, 365)
        last_date = latest_dates.get(key)

        if last_date is None:
            # Never observed -- flag it
            issues.append(
                LivenessIssue(
                    source_id=spec.source_id,
                    source_native_code=spec.source_native_code,
                    indicator_code=spec.indicator_code,
                    expected_frequency=spec.frequency,
                    last_date=None,
                    days_since_last=None,
                    threshold_days=threshold,
                    message=(
                        f"{spec.source_id}/{spec.indicator_code}: "
                        f"no observations found (expected {spec.frequency})"
                    ),
                )
            )
            continue

        days_since = (ref_date - last_date).days
        if days_since > threshold:
            issues.append(
                LivenessIssue(
                    source_id=spec.source_id,
                    source_native_code=spec.source_native_code,
                    indicator_code=spec.indicator_code,
                    expected_frequency=spec.frequency,
                    last_date=last_date,
                    days_since_last=days_since,
                    threshold_days=threshold,
                    message=(
                        f"{spec.source_id}/{spec.indicator_code}: "
                        f"last data {last_date.isoformat()} "
                        f"({days_since}d ago, threshold {threshold}d "
                        f"for {spec.frequency})"
                    ),
                )
            )

    if issues:
        logger.warning(
            "liveness.stale_series",
            n_issues=len(issues),
            series=[i.indicator_code for i in issues],
        )
    else:
        logger.info("liveness.all_healthy", n_checked=len(indicator_specs))

    return issues
