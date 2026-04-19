"""Spread builder -- computes yield spreads and other pairwise differences.

A spread is the difference between two observation series on matching
dates: spread = long_end - short_end. The default convention follows
bond market standards where a positive spread indicates a normal
(upward-sloping) curve and a negative spread indicates inversion.

The builder produces canonical Observation records with synthetic
indicator codes (e.g. SPREAD_10Y_2Y) that flow through the same
scoring, quality, and LLM pipelines as raw observations.

Pre-configured spreads ship in DEFAULT_SPREADS. Custom spreads
can be defined via SpreadSpec and computed on demand.

Usage:
    from hornet.derived.spreads import compute_spreads, DEFAULT_SPREADS

    # From observations already in the DB
    spread_obs = compute_spreads(
        observations=all_observations,
        spread_specs=DEFAULT_SPREADS,
    )
    # spread_obs are regular Observations, persist them like any other
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

import structlog
from pydantic import BaseModel, ConfigDict, Field

from hornet.domain.observation import Observation

logger = structlog.get_logger(__name__)


class SpreadSpec(BaseModel):
    """Definition of a spread: long_indicator - short_indicator.

    The result is stored as a new Observation with indicator_code
    set to ``result_code`` and source_id set to "derived".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    long_indicator: str = Field(
        ...,
        min_length=1,
        description="Indicator code for the long end (e.g. UST_10Y, DGS10).",
    )
    short_indicator: str = Field(
        ...,
        min_length=1,
        description="Indicator code for the short end (e.g. UST_2Y, DGS2).",
    )
    result_code: str = Field(
        ...,
        min_length=1,
        description="Canonical code for the computed spread (e.g. SPREAD_10Y_2Y).",
    )
    name: str = Field(
        ...,
        min_length=1,
        description="Human-readable name (e.g. '10Y-2Y Treasury Spread').",
    )


# Pre-configured spreads that ship with Hornet.
# Convention: long_end - short_end (positive = normal curve).
DEFAULT_SPREADS: tuple[SpreadSpec, ...] = (
    # Classic 2s10s (most-watched curve signal)
    SpreadSpec(
        long_indicator="DGS10",
        short_indicator="DGS2",
        result_code="SPREAD_10Y_2Y",
        name="10Y-2Y Treasury Spread",
    ),
    # 10Y-3M (Fed's preferred recession indicator)
    SpreadSpec(
        long_indicator="DGS10",
        short_indicator="UST_3M",
        result_code="SPREAD_10Y_3M",
        name="10Y-3M Treasury Spread",
    ),
    # 30Y-10Y (long end steepness)
    SpreadSpec(
        long_indicator="UST_30Y",
        short_indicator="DGS10",
        result_code="SPREAD_30Y_10Y",
        name="30Y-10Y Treasury Spread",
    ),
    # 5Y-2Y (belly of the curve)
    SpreadSpec(
        long_indicator="UST_5Y",
        short_indicator="DGS2",
        result_code="SPREAD_5Y_2Y",
        name="5Y-2Y Treasury Spread",
    ),
    # 10Y real yield (TIPS 10Y, not a spread but same pattern)
    # Already exists as TIPS_10Y, so not duplicated here.
    # 10Y breakeven (nominal - TIPS = inflation expectations)
    # Already computed by FRED as T10YIE / BREAKEVEN_10Y.
)


def _match_by_date(
    long_obs: Sequence[Observation],
    short_obs: Sequence[Observation],
) -> list[tuple[Observation, Observation]]:
    """Match observations from two series by date.

    Returns pairs where both series have a value on the same date.
    If multiple vintages exist for a date, uses the latest vintage.
    """
    # Build date -> latest-vintage observation maps
    long_by_date: dict[datetime.date, Observation] = {}
    for obs in long_obs:
        existing = long_by_date.get(obs.date)
        if existing is None or obs.vintage > existing.vintage:
            long_by_date[obs.date] = obs

    short_by_date: dict[datetime.date, Observation] = {}
    for obs in short_obs:
        existing = short_by_date.get(obs.date)
        if existing is None or obs.vintage > existing.vintage:
            short_by_date[obs.date] = obs

    # Match on common dates
    common_dates = sorted(set(long_by_date) & set(short_by_date))
    return [(long_by_date[d], short_by_date[d]) for d in common_dates]


def compute_spread(
    long_obs: Sequence[Observation],
    short_obs: Sequence[Observation],
    spec: SpreadSpec,
    *,
    now: datetime.datetime | None = None,
) -> list[Observation]:
    """Compute a spread from two observation series.

    For each date where both series have values, produces a new
    Observation with value = long.value - short.value.

    Parameters
    ----------
    long_obs:
        Observations for the long-end indicator.
    short_obs:
        Observations for the short-end indicator.
    spec:
        Spread definition (indicator codes, result code).
    now:
        Timestamp for vintage and ingested_at. Defaults to UTC now.

    Returns
    -------
    list[Observation]
        Derived spread observations, one per matched date.
    """
    timestamp = now if now is not None else datetime.datetime.now(datetime.UTC)
    pairs = _match_by_date(long_obs, short_obs)

    results: list[Observation] = []
    for long, short in pairs:
        spread_value = long.value - short.value
        results.append(
            Observation(
                country_iso3=long.country_iso3,
                indicator_code=spec.result_code,
                source_id="derived",
                date=long.date,
                value=round(spread_value, 6),
                frequency=long.frequency,
                vintage=timestamp,
                ingested_at=timestamp,
            )
        )

    if results:
        logger.info(
            "spreads.computed",
            spread=spec.result_code,
            n_points=len(results),
            latest_date=str(results[-1].date),
        )

    return results


def compute_spreads(
    observations: Sequence[Observation],
    spread_specs: Sequence[SpreadSpec] | None = None,
    *,
    now: datetime.datetime | None = None,
) -> list[Observation]:
    """Compute all configured spreads from a set of observations.

    Groups observations by indicator_code, then computes each spread
    where both legs have data. Spreads with missing legs are skipped
    with a debug log (not an error -- some maturities may not have
    data for all dates).

    Parameters
    ----------
    observations:
        All observations (mixed indicator codes). The function filters
        to the relevant codes for each spread.
    spread_specs:
        Spread definitions to compute. Defaults to DEFAULT_SPREADS.
    now:
        Timestamp for derived observations.

    Returns
    -------
    list[Observation]
        All derived spread observations across all specs.
    """
    specs = spread_specs if spread_specs is not None else DEFAULT_SPREADS

    # Group observations by indicator_code for fast lookup
    by_code: dict[str, list[Observation]] = defaultdict(list)
    for obs in observations:
        by_code[obs.indicator_code].append(obs)

    all_spreads: list[Observation] = []
    for spec in specs:
        long_obs = by_code.get(spec.long_indicator, [])
        short_obs = by_code.get(spec.short_indicator, [])

        if not long_obs or not short_obs:
            logger.debug(
                "spreads.missing_leg",
                spread=spec.result_code,
                long_code=spec.long_indicator,
                long_count=len(long_obs),
                short_code=spec.short_indicator,
                short_count=len(short_obs),
            )
            continue

        spread_obs = compute_spread(long_obs, short_obs, spec, now=now)
        all_spreads.extend(spread_obs)

    logger.info(
        "spreads.all_computed",
        n_specs=len(specs),
        n_spreads=len(all_spreads),
    )

    return all_spreads
