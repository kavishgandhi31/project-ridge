"""Control #7: Structural break detection -- flags regime shifts.

Ported from v1 structural_break.py.

Algorithm:
    For each series (country, indicator, source):
    1. Sort by date, take latest-vintage value per date
    2. Need at least 2 * window observations
    3. Split into prior window and recent window (each of size N)
    4. Compute shift_sigma = |recent_mean - prior_mean| / prior_std
    5. Flag if shift_sigma > threshold
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

from ridge.domain.observation import Observation
from ridge.quality.config import QualityConfig
from ridge.quality.issue import IssueSeverity, QualityIssue


def detect_structural_breaks(
    observations: Sequence[Observation],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Scan all observation series for regime shifts."""
    series: dict[tuple[str, str, str], list[Observation]] = defaultdict(list)
    for obs in observations:
        key = (obs.country_iso3, obs.indicator_code, obs.source_id)
        series[key].append(obs)

    issues: list[QualityIssue] = []

    for (iso3, indicator, source), obs_list in series.items():
        result = _check_series(obs_list, config)
        if result is not None:
            issues.append(
                QualityIssue(
                    check_name="structural_break",
                    severity=IssueSeverity.WARNING,
                    country_iso3=iso3,
                    indicator_code=indicator,
                    source_id=source,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail=result,
                    message=(
                        f"{indicator} ({source}) regime shift detected: "
                        f"{result['shift_sigma']:.1f} sigma "
                        f"(prior mean {result['prior_mean']:.4f} -> "
                        f"recent mean {result['recent_mean']:.4f})"
                    ),
                )
            )

    return issues


def _check_series(
    obs_list: list[Observation],
    config: QualityConfig,
) -> dict[str, float] | None:
    """Check a single series for structural break.

    Ported from v1 StructuralBreakDetector._check_series().
    """
    # Latest vintage per date
    by_date: dict[datetime.date, Observation] = {}
    for obs in obs_list:
        existing = by_date.get(obs.date)
        if existing is None or obs.vintage > existing.vintage:
            by_date[obs.date] = obs

    values = [by_date[d].value for d in sorted(by_date)]
    window = config.break_window

    if len(values) < 2 * window:
        return None

    # Prior window: values[-2*window : -window]
    # Recent window: values[-window:]
    prior = values[-2 * window : -window]
    recent = values[-window:]

    prior_mean = sum(prior) / len(prior)
    recent_mean = sum(recent) / len(recent)

    n = len(prior)
    prior_variance = sum((v - prior_mean) ** 2 for v in prior) / (n - 1) if n > 1 else 0.0
    prior_std = prior_variance**0.5

    if prior_std == 0:
        return None

    shift_sigma = abs(recent_mean - prior_mean) / prior_std

    if shift_sigma > config.break_sigma:
        return {
            "prior_mean": round(prior_mean, 6),
            "recent_mean": round(recent_mean, 6),
            "prior_std": round(prior_std, 6),
            "shift_sigma": round(shift_sigma, 2),
            "threshold": config.break_sigma,
            "window_size": window,
        }

    return None
