"""Control #2: Series audit -- compares registry vs actual coverage.

Ported from v1 series_audit.py. v1 compared hardcoded expectations
vs DataFrames. v2 compares the source_indicator registry entries
against actual observation counts per (country, indicator, source).
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from ridge.domain.source import SourceIndicatorSpec
from ridge.quality.config import QualityConfig
from ridge.quality.issue import IssueSeverity, QualityIssue


def audit_series_coverage(
    indicator_specs: Sequence[SourceIndicatorSpec],
    observation_counts: dict[tuple[str, str, str], int],
    config: QualityConfig,
    run_id: str,
    detected_at: datetime.datetime,
) -> list[QualityIssue]:
    """Flag countries where actual coverage falls short of the registry.

    Parameters
    ----------
    indicator_specs:
        All enabled SourceIndicatorSpec entries (the registry).
    observation_counts:
        Maps (country_iso3, indicator_code, source_id) -> observation count.
        Produced by a repo query.
    config:
        Quality config with series_audit_threshold.
    """
    # Build expected: for each country in each spec's countries_iso3,
    # expect at least one observation for (country, indicator, source).
    expected: dict[str, list[tuple[str, str]]] = {}  # country -> [(indicator, source), ...]

    for spec in indicator_specs:
        if spec.dimension is None:
            continue  # non-scored series are not audited
        for iso3 in spec.countries_iso3:
            expected.setdefault(iso3, []).append((spec.indicator_code, spec.source_id))

    issues: list[QualityIssue] = []

    for iso3, expected_pairs in sorted(expected.items()):
        total_expected = len(expected_pairs)
        if total_expected == 0:
            continue

        missing: list[str] = []
        for indicator, source in expected_pairs:
            count = observation_counts.get((iso3, indicator, source), 0)
            if count == 0:
                missing.append(f"{source}:{indicator}")

        if not missing:
            continue

        gap_fraction = len(missing) / total_expected
        if gap_fraction <= config.series_audit_threshold:
            continue

        issues.append(
            QualityIssue(
                check_name="series_audit",
                severity=IssueSeverity.WARNING,
                country_iso3=iso3,
                run_id=run_id,
                detected_at=detected_at,
                detail={
                    "expected_count": total_expected,
                    "received_count": total_expected - len(missing),
                    "missing": missing,
                    "gap_fraction": round(gap_fraction, 2),
                    "threshold": config.series_audit_threshold,
                },
                message=(
                    f"{iso3}: {len(missing)}/{total_expected} series missing "
                    f"({gap_fraction:.0%} gap)"
                ),
            )
        )

    return sorted(issues, key=lambda i: i.detail.get("gap_fraction", 0), reverse=True)
