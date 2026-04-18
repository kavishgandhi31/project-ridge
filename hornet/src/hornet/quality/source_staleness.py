"""Control #10: Source staleness -- flags indicators with outdated data.

Ported from v1 source_health.py (staleness portion). v1 maintained a
separate SQLite table. v2 queries latest observation dates directly
from the observations table.

Also covers v1's global_health.py -- global-signal indicators are
just regular indicators with global_signal=true, so their staleness
is checked the same way.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from hornet.domain.observation import Observation
from hornet.quality.config import QualityConfig
from hornet.quality.issue import IssueSeverity, QualityIssue


def check_source_staleness(
    observations: Sequence[Observation],
    reference_date: datetime.date,
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Flag indicators whose latest observation is too old.

    For each (country, indicator, source), finds the latest observation
    date and compares against the staleness threshold for that
    indicator's frequency tier.
    """
    # Group: (country, indicator, source, frequency) -> latest date
    latest_dates: dict[tuple[str, str, str, str], datetime.date] = {}

    for obs in observations:
        key = (obs.country_iso3, obs.indicator_code, obs.source_id, obs.frequency)
        current = latest_dates.get(key)
        if current is None or obs.date > current:
            latest_dates[key] = obs.date

    issues: list[QualityIssue] = []

    for (iso3, indicator, source, frequency), latest_date in latest_dates.items():
        max_age = config.staleness_days.get(frequency)
        if max_age is None:
            continue

        age_days = (reference_date - latest_date).days
        if age_days > max_age:
            issues.append(
                QualityIssue(
                    check_name="source_staleness",
                    severity=IssueSeverity.WARNING,
                    country_iso3=iso3,
                    indicator_code=indicator,
                    source_id=source,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail={
                        "frequency": frequency,
                        "latest_date": str(latest_date),
                        "age_days": age_days,
                        "threshold_days": max_age,
                    },
                    message=(
                        f"{indicator} ({source}, {frequency}): latest obs {latest_date} "
                        f"is {age_days} days old (threshold {max_age})"
                    ),
                )
            )

    return issues
