"""Control #6: Flatline detection -- flags series stuck at constant values.

Ported from v1 flatline_detection.py.

Algorithm:
    For each series (country, indicator, source):
    1. Sort by date, take latest-vintage value per date
    2. Count consecutive identical values from the tail
    3. Flag if count >= min_repeats threshold
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

from ridge.domain.observation import Observation
from ridge.quality.config import QualityConfig
from ridge.quality.issue import IssueSeverity, QualityIssue


def detect_flatlines(
    observations: Sequence[Observation],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Scan all observation series for stuck values."""
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
                    check_name="flatline",
                    severity=IssueSeverity.WARNING,
                    country_iso3=iso3,
                    indicator_code=indicator,
                    source_id=source,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail=result,
                    message=(
                        f"{indicator} ({source}) stuck at {result['stuck_value']:.4f} "
                        f"for {result['repeat_count']} consecutive observations"
                    ),
                )
            )

    return issues


def _check_series(
    obs_list: list[Observation],
    config: QualityConfig,
) -> dict[str, object] | None:
    """Check a single series for flatline.

    Ported from v1 FlatlineDetector._check_series().
    """
    # Latest vintage per date
    by_date: dict[datetime.date, Observation] = {}
    for obs in obs_list:
        existing = by_date.get(obs.date)
        if existing is None or obs.vintage > existing.vintage:
            by_date[obs.date] = obs

    values = [by_date[d].value for d in sorted(by_date)]

    if len(values) < config.flatline_min_repeats:
        return None

    # Count consecutive identical values from the tail
    latest = values[-1]
    count = 0
    for v in reversed(values):
        if abs(v - latest) <= config.flatline_tolerance:
            count += 1
        else:
            break

    if count >= config.flatline_min_repeats:
        return {
            "stuck_value": latest,
            "repeat_count": count,
            "total_observations": len(values),
        }

    return None
