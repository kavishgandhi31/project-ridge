"""Shared adapter dispatch helpers.

Used by every numeric and event adapter to validate the seed-supplied
``SourceIndicatorSpec`` list and pre-compute the
``country_iso3 -> specs`` lookup map. Lifted out of each adapter to
remove the character-for-character duplication that was sitting in
FRED, WorldBank, OECD, BIS, IMF, yfinance, GDELT, and GoogleNews.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

import structlog

from ridge.domain import SourceIndicatorSpec

logger = structlog.get_logger(__name__)


def validate_indicators(
    source_id: str,
    indicators: Iterable[SourceIndicatorSpec],
) -> list[SourceIndicatorSpec]:
    """Drop any rows whose ``source_id`` does not match ``source_id``.

    Defensive: the ingest runner should only ever pass matching rows,
    but the adapter must not trust its caller. Mismatched rows are
    skipped and logged with the structlog event
    ``"{source_id}.indicator.wrong_source"``.
    """
    event = f"{source_id}.indicator.wrong_source"
    kept: list[SourceIndicatorSpec] = []
    for spec in indicators:
        if spec.source_id != source_id:
            logger.warning(
                event,
                source_id=spec.source_id,
                native_code=spec.source_native_code,
            )
            continue
        kept.append(spec)
    return kept


def group_by_country(
    indicators: Sequence[SourceIndicatorSpec],
) -> dict[str, tuple[SourceIndicatorSpec, ...]]:
    """Build a ``country_iso3 -> specs`` map for fast fetch() dispatch.

    A spec listing multiple countries (e.g. a WorldBank-style row with
    one native_code covering many ISO3s) is expanded so each country
    gets its own tuple entry; ``fetch()`` can then iterate the
    requested countries without re-scanning the full spec list.
    """
    by_country: dict[str, list[SourceIndicatorSpec]] = defaultdict(list)
    for spec in indicators:
        for iso3 in spec.countries_iso3:
            by_country[iso3].append(spec)
    return {iso3: tuple(specs) for iso3, specs in by_country.items()}
