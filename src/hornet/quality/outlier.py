"""Control #1: Outlier detection -- flags observations deviating > N sigma.

Ported from v1 outlier_detection.py. v1 mutated DataFrames in-place
(removing outlier rows). v2 produces QualityIssue records instead;
the scoring runner can exclude flagged observations.

Algorithm:
    For each series (country, indicator, source):
    1. Sort by date, take the latest-vintage value per date
    2. Split into trailing history (all but last) and latest value
    3. Compute trailing mean and std
    4. Flag if |latest - mean| / std > sigma threshold
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

from hornet.domain.observation import Observation
from hornet.quality.config import QualityConfig
from hornet.quality.issue import IssueSeverity, QualityIssue


def detect_outliers(
    observations: Sequence[Observation],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Screen all observation series for statistical outliers.

    Groups observations by (country, indicator, source). For each
    series, computes trailing statistics and flags the latest value
    if it exceeds the sigma threshold.
    """
    # Group observations by series key
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
                    check_name="outlier",
                    severity=IssueSeverity.CRITICAL,
                    country_iso3=iso3,
                    indicator_code=indicator,
                    source_id=source,
                    run_id=run_id,
                    detected_at=detected_at,
                    detail=result,
                    message=(
                        f"{indicator} ({source}) latest value {result['latest_value']:.4f} "
                        f"is {result['sigma_distance']:.1f} sigma from trailing mean "
                        f"(threshold: {result['threshold']:.1f})"
                    ),
                )
            )

    return issues


def _check_series(
    obs_list: list[Observation],
    config: QualityConfig,
) -> dict[str, float] | None:
    """Check a single series for outliers.

    Ported from v1 OutlierGate._check_series().
    """
    # Latest vintage per date
    by_date: dict[datetime.date, Observation] = {}
    for obs in obs_list:
        existing = by_date.get(obs.date)
        if existing is None or obs.vintage > existing.vintage:
            by_date[obs.date] = obs

    values = [by_date[d].value for d in sorted(by_date)]

    if len(values) < config.outlier_min_history:
        return None

    # Split: trailing = all but last, latest = last
    trailing = values[:-1]
    latest = values[-1]

    n = len(trailing)
    mean = sum(trailing) / n
    variance = sum((v - mean) ** 2 for v in trailing) / (n - 1) if n > 1 else 0.0
    std = variance**0.5

    if std == 0:
        return None

    sigma_distance = abs(latest - mean) / std

    if sigma_distance > config.outlier_sigma:
        return {
            "latest_value": round(latest, 6),
            "trailing_mean": round(mean, 6),
            "trailing_std": round(std, 6),
            "sigma_distance": round(sigma_distance, 2),
            "threshold": config.outlier_sigma,
        }

    return None
