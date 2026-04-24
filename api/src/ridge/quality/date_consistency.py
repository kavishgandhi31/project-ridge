"""Control #8: Date consistency -- flags cross-source date lag.

Ported from v1 date_consistency.py. For each country, finds the
latest observation date per source and flags if the lag between
the freshest and stalest source exceeds the threshold.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

from ridge.domain.observation import Observation
from ridge.quality.config import QualityConfig
from ridge.quality.issue import IssueSeverity, QualityIssue


def check_date_consistency(
    observations: Sequence[Observation],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Flag countries where sources have large date misalignment.

    For each country, finds the latest observation date per source.
    Flags if the gap between the freshest and stalest source exceeds
    the configured threshold.
    """
    # Group: country -> source -> latest date
    country_source_dates: dict[str, dict[str, datetime.date]] = defaultdict(dict)

    for obs in observations:
        iso3 = obs.country_iso3
        source = obs.source_id
        current = country_source_dates[iso3].get(source)
        if current is None or obs.date > current:
            country_source_dates[iso3][source] = obs.date

    issues: list[QualityIssue] = []
    max_lag = config.max_source_date_lag_days

    for iso3, source_dates in country_source_dates.items():
        if len(source_dates) < 2:
            continue

        dates = sorted(source_dates.values())
        freshest = dates[-1]
        stalest = dates[0]
        lag_days = (freshest - stalest).days

        if lag_days > max_lag:
            freshest_source = next(s for s, d in source_dates.items() if d == freshest)
            stalest_source = next(s for s, d in source_dates.items() if d == stalest)
            issues.append(
                QualityIssue(
                    check_name="date_consistency",
                    severity=IssueSeverity.WARNING,
                    country_iso3=iso3,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail={
                        "freshest_source": freshest_source,
                        "freshest_date": str(freshest),
                        "stalest_source": stalest_source,
                        "stalest_date": str(stalest),
                        "lag_days": lag_days,
                        "threshold_days": max_lag,
                    },
                    message=(
                        f"{iso3}: {stalest_source} latest={stalest} vs "
                        f"{freshest_source} latest={freshest} "
                        f"({lag_days} day lag, threshold {max_lag})"
                    ),
                )
            )

    return issues
