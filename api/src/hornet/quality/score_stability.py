"""Control #4: Score stability -- flags suspicious composite jumps.

Ported from v1 score_stability.py. Compares current scoring run
composites against the prior run. Only flags when coverage is stable
(didn't change significantly) -- a jump with stable coverage means
the data itself moved, which is suspicious.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from hornet.domain.scoring import ScoreResult
from hornet.quality.config import QualityConfig
from hornet.quality.issue import IssueSeverity, QualityIssue


def check_score_stability(
    current_results: Sequence[ScoreResult],
    prior_results: Sequence[ScoreResult],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Flag countries with large composite score jumps between runs.

    Only flags when coverage is stable (within tolerance). A jump
    with changing coverage is expected (new data arrived); a jump
    with stable coverage is suspicious (data quality issue).
    """
    prior_by_country = {r.country_iso3: r for r in prior_results}

    issues: list[QualityIssue] = []

    for current in current_results:
        prior = prior_by_country.get(current.country_iso3)
        if prior is None:
            continue

        if current.composite is None or prior.composite is None:
            continue

        # Check if coverage is stable
        coverage_change = abs(current.coverage_fraction - prior.coverage_fraction)
        if coverage_change > config.coverage_stability_tolerance:
            continue  # coverage changed — jump is expected

        delta = abs(current.composite - prior.composite)
        if delta > config.score_jump_threshold:
            issues.append(
                QualityIssue(
                    check_name="score_stability",
                    severity=IssueSeverity.WARNING,
                    country_iso3=current.country_iso3,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail={
                        "prior_composite": prior.composite,
                        "current_composite": current.composite,
                        "delta": round(delta, 4),
                        "prior_coverage": prior.coverage_fraction,
                        "current_coverage": current.coverage_fraction,
                        "threshold": config.score_jump_threshold,
                    },
                    message=(
                        f"{current.country_iso3}: composite jumped "
                        f"{prior.composite:.2f} -> {current.composite:.2f} "
                        f"(delta {delta:.2f}, threshold {config.score_jump_threshold:.1f})"
                    ),
                )
            )

    return sorted(issues, key=lambda i: i.detail.get("delta", 0), reverse=True)
