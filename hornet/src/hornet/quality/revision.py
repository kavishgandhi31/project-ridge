"""Control #5: Revision detection -- finds observations with multiple vintages.

Dramatically simplified from v1 revision_detection.py. v1 snapshotted
before ingest and compared after. v2 has vintage tracking built into
the observations table, so a revision = multiple vintages for the same
(country, indicator, source, date). Just group and compare.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

from hornet.domain.observation import Observation
from hornet.quality.config import QualityConfig
from hornet.quality.issue import IssueSeverity, QualityIssue


def detect_revisions(
    observations: Sequence[Observation],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Find observations that have been revised (multiple vintages per date).

    Groups observations by (country, indicator, source, date). Where
    multiple vintages exist, reports the earliest and latest values
    as a revision.

    Only checks the last ``revision_lookback`` dates per series.
    """
    # Group by series key -> date -> list of (vintage, value)
    series_dates: dict[
        tuple[str, str, str],
        dict[datetime.date, list[tuple[datetime.datetime, float]]],
    ] = defaultdict(lambda: defaultdict(list))

    for obs in observations:
        key = (obs.country_iso3, obs.indicator_code, obs.source_id)
        series_dates[key][obs.date].append((obs.vintage, obs.value))

    issues: list[QualityIssue] = []

    for (iso3, indicator, source), date_vintages in series_dates.items():
        # Only check the last N dates
        sorted_dates = sorted(date_vintages.keys())
        lookback_dates = sorted_dates[-config.revision_lookback :]

        revisions: list[dict[str, object]] = []
        for date in lookback_dates:
            vintages = date_vintages[date]
            if len(vintages) < 2:
                continue

            # Sort by vintage timestamp
            vintages.sort(key=lambda x: x[0])
            earliest_vintage, earliest_value = vintages[0]
            latest_vintage, latest_value = vintages[-1]

            if abs(latest_value - earliest_value) > 1e-6:
                revisions.append(
                    {
                        "date": str(date),
                        "old_value": round(earliest_value, 6),
                        "new_value": round(latest_value, 6),
                        "old_vintage": str(earliest_vintage),
                        "new_vintage": str(latest_vintage),
                    }
                )

        if revisions:
            issues.append(
                QualityIssue(
                    check_name="revision",
                    severity=IssueSeverity.INFO,
                    country_iso3=iso3,
                    indicator_code=indicator,
                    source_id=source,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail={
                        "revised_count": len(revisions),
                        "revisions": revisions,
                    },
                    message=(
                        f"{indicator} ({source}): {len(revisions)} revised observation(s) "
                        f"in last {config.revision_lookback} dates"
                    ),
                )
            )

    return issues
