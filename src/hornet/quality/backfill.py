"""Control #9: Backfill detection -- flags sudden coverage gains.

Ported from v1 backfill_detection.py. Compares coverage_fraction
between current and prior scoring runs. A sudden gain (e.g. 25%+)
is suspicious — it may indicate bulk data loading or test data
leaking into production.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from hornet.domain.scoring import ScoreResult
from hornet.quality.config import QualityConfig
from hornet.quality.issue import IssueSeverity, QualityIssue


def detect_backfills(
    current_results: Sequence[ScoreResult],
    prior_results: Sequence[ScoreResult],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Flag countries whose coverage jumped suspiciously between runs."""
    prior_by_country = {r.country_iso3: r for r in prior_results}

    issues: list[QualityIssue] = []

    for current in current_results:
        prior = prior_by_country.get(current.country_iso3)
        if prior is None:
            continue

        gain = current.coverage_fraction - prior.coverage_fraction
        if gain > config.backfill_threshold:
            issues.append(
                QualityIssue(
                    check_name="backfill",
                    severity=IssueSeverity.WARNING,
                    country_iso3=current.country_iso3,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail={
                        "prior_coverage": prior.coverage_fraction,
                        "current_coverage": current.coverage_fraction,
                        "gain": round(gain, 4),
                        "threshold": config.backfill_threshold,
                    },
                    message=(
                        f"{current.country_iso3}: coverage jumped "
                        f"{prior.coverage_fraction:.0%} -> {current.coverage_fraction:.0%} "
                        f"(gain {gain:.0%}, threshold {config.backfill_threshold:.0%})"
                    ),
                )
            )

    return sorted(issues, key=lambda i: i.detail.get("gain", 0), reverse=True)
