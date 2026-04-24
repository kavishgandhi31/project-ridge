"""Control #3: Cross-source validation -- flags divergence between sources.

Ported from v1 cross_source.py. v1 compared FRED vs yfinance FX rates.
v2 generalizes: for any indicator_code reported by multiple sources on
the same date, check if the latest values diverge beyond the threshold.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

from ridge.domain.observation import Observation
from ridge.quality.config import QualityConfig
from ridge.quality.issue import IssueSeverity, QualityIssue


def validate_cross_source(
    observations: Sequence[Observation],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Flag divergence where multiple sources report the same indicator.

    Groups observations by (country, indicator, date). Where two or
    more sources report on the same date, compares latest values and
    flags if divergence exceeds the threshold.
    """
    # Group by (country, indicator, date) -> {source: value}
    groups: dict[
        tuple[str, str, datetime.date],
        dict[str, float],
    ] = defaultdict(dict)

    for obs in observations:
        key = (obs.country_iso3, obs.indicator_code, obs.date)
        # Keep latest vintage per source
        existing = groups[key].get(obs.source_id)
        if existing is None:
            groups[key][obs.source_id] = obs.value
        # If there's already a value from this source for this date,
        # we'd need vintage comparison — but the caller should have
        # already filtered to latest vintage. Just overwrite.

    issues: list[QualityIssue] = []

    for (iso3, indicator, date), source_values in groups.items():
        if len(source_values) < 2:
            continue

        sources = sorted(source_values.keys())
        # Compare each pair
        for i in range(len(sources)):
            for j in range(i + 1, len(sources)):
                s1, s2 = sources[i], sources[j]
                v1, v2 = source_values[s1], source_values[s2]

                if v1 == 0 and v2 == 0:
                    continue
                reference = abs(v1) if v1 != 0 else abs(v2)
                divergence = abs(v1 - v2) / reference

                if divergence > config.cross_source_threshold:
                    issues.append(
                        QualityIssue(
                            check_name="cross_source",
                            severity=IssueSeverity.WARNING,
                            country_iso3=iso3,
                            indicator_code=indicator,
                            run_id=run_id,
                            detected_at=detected_at,
                            detail={
                                "source_a": s1,
                                "source_b": s2,
                                "value_a": round(v1, 6),
                                "value_b": round(v2, 6),
                                "divergence_pct": round(divergence * 100, 2),
                                "threshold_pct": round(config.cross_source_threshold * 100, 2),
                                "date": str(date),
                            },
                            message=(
                                f"{indicator} on {date}: {s1}={v1:.4f} vs {s2}={v2:.4f} "
                                f"({divergence * 100:.1f}% divergence, "
                                f"threshold {config.cross_source_threshold * 100:.0f}%)"
                            ),
                        )
                    )

    return issues
