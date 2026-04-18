"""Source coverage validation -- prevents 404 storms from uncovered countries.

Each data source covers a subset of countries. Querying a source for
a country it doesn't cover wastes time (timeouts, 404s) and creates
noise in logs. This module provides coverage sets and a validation
function that filters countries to only those a source can serve.

Coverage sets are derived from:
- BIS: 48 countries (hardcoded in v1, based on BIS publication list)
- OECD: 44 countries (38 OECD members + 6 key partners)
- IMF IFS/BOP: ~60 countries (SDMX endpoint, variable availability)
- FRED: global signals only (USA) + per-country series (varies)
- WorldBank: ~190 countries (broadest coverage)
- yfinance: per-country FX/equity from source_indicator registry
- GDELT/GoogleNews: any country with a name (effectively all)
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from hornet.domain.source import SourceIndicatorSpec

logger = structlog.get_logger(__name__)

# BIS covers these ISO3 codes. Querying others returns empty/404.
BIS_COVERED: frozenset[str] = frozenset(
    {
        "ARG",
        "AUS",
        "AUT",
        "BEL",
        "BRA",
        "CAN",
        "CHE",
        "CHL",
        "CHN",
        "COL",
        "CZE",
        "DEU",
        "DNK",
        "ESP",
        "FIN",
        "FRA",
        "GBR",
        "GRC",
        "HKG",
        "HUN",
        "IDN",
        "IND",
        "IRL",
        "ISR",
        "ITA",
        "JPN",
        "KOR",
        "MEX",
        "MYS",
        "NLD",
        "NOR",
        "NZL",
        "PER",
        "PHL",
        "POL",
        "PRT",
        "ROU",
        "RUS",
        "SAU",
        "SGP",
        "SWE",
        "THA",
        "TUR",
        "TWN",
        "USA",
        "ZAF",
    }
)

# OECD covers these ISO3 codes for CLI/BCI/CCI indicators.
OECD_COVERED: frozenset[str] = frozenset(
    {
        "AUS",
        "AUT",
        "BEL",
        "BRA",
        "CAN",
        "CHE",
        "CHL",
        "CHN",
        "COL",
        "CRI",
        "CZE",
        "DEU",
        "DNK",
        "ESP",
        "EST",
        "FIN",
        "FRA",
        "GBR",
        "GRC",
        "HUN",
        "IDN",
        "IND",
        "IRL",
        "ISL",
        "ISR",
        "ITA",
        "JPN",
        "KOR",
        "LTU",
        "LUX",
        "LVA",
        "MEX",
        "NLD",
        "NOR",
        "NZL",
        "POL",
        "PRT",
        "SVK",
        "SVN",
        "SWE",
        "TUR",
        "USA",
        "ZAF",
    }
)

# Sources with limited coverage. Sources not listed here cover all countries.
_SOURCE_COVERAGE: dict[str, frozenset[str]] = {
    "bis": BIS_COVERED,
    "oecd": OECD_COVERED,
}


def filter_countries_for_source(
    source_id: str,
    countries: Sequence[str],
) -> list[str]:
    """Filter a country list to only those covered by the given source.

    Sources not in the coverage map (WorldBank, FRED, yfinance, etc.)
    return the full list unchanged.
    """
    coverage = _SOURCE_COVERAGE.get(source_id)
    if coverage is None:
        return list(countries)

    covered = [c for c in countries if c in coverage]
    skipped = [c for c in countries if c not in coverage]

    if skipped:
        logger.debug(
            "coverage.filtered",
            source=source_id,
            n_covered=len(covered),
            n_skipped=len(skipped),
        )

    return covered


def get_covered_countries(
    indicator_specs: Sequence[SourceIndicatorSpec],
) -> dict[str, frozenset[str]]:
    """Build a map of source_id -> set of covered ISO3 codes.

    Derives coverage dynamically from the source_indicator registry
    rather than hardcoding. This handles yfinance (varies per country)
    and any future source additions.
    """
    coverage: dict[str, set[str]] = {}
    for spec in indicator_specs:
        if not spec.enabled:
            continue
        if spec.source_id not in coverage:
            coverage[spec.source_id] = set()
        coverage[spec.source_id].update(spec.countries_iso3)

    return {k: frozenset(v) for k, v in coverage.items()}
