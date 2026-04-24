"""Dimension scoring — the core of the scoring engine.

Ported from v1 scorer.py lines 449-708. The algorithm is:

1. For each dimension, find all indicators mapped to it (via the
   source_indicator registry's dimension/concept tags).

2. Match indicators to observations by (source_id, indicator_code).

3. Group matched observations by (frequency, concept). Within each
   group, compute a z-score for each series, then average the
   z-scores together (concept deduplication).

4. Combine concept-level z-scores across frequency tiers using
   configurable weights, normalized to whichever tiers have data.

5. Clamp the result to [scale_min, scale_max].

risk_sentiment gets special treatment: it combines a standard
fundamental score with yfinance momentum z-scores and GDELT tone,
ported from v1's ``_score_risk_sentiment()`` (lines 606-681).
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Sequence

import structlog

from ridge.domain.event import EventRecord
from ridge.domain.observation import Observation
from ridge.domain.scoring import DimensionScore, ScoringConfig
from ridge.domain.source import SourceIndicatorSpec
from ridge.scoring.zscore import compute_momentum_zscore, compute_zscore

logger = structlog.get_logger(__name__)


class Dimension(ABC):
    """Abstract base for a scoring dimension."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Dimension name (e.g. 'growth_momentum')."""

    @abstractmethod
    def score(
        self,
        iso3: str,
        observations: Sequence[Observation],
        events: Sequence[EventRecord],
        indicator_map: Sequence[SourceIndicatorSpec],
        config: ScoringConfig,
        reference_date: datetime.date,
    ) -> DimensionScore:
        """Compute the score for this dimension.

        Parameters
        ----------
        iso3:
            Country being scored.
        observations:
            All observations for this country (the dimension filters
            to its own indicators internally).
        events:
            All events for this country (used by risk_sentiment).
        indicator_map:
            Full indicator registry (the dimension filters to its own
            dimension tag internally).
        config:
            Scoring configuration.
        reference_date:
            Date to use for staleness gate checks.
        """


def _is_stale(
    latest_date: datetime.date,
    frequency: str,
    reference_date: datetime.date,
    staleness_gates: dict[str, int],
) -> bool:
    """Check whether a series' latest observation is too old for its frequency.

    Ported from v1 ``Scorer._is_stale()`` (scorer.py lines 472-497).
    """
    max_age = staleness_gates.get(frequency)
    if max_age is None:
        return False
    cutoff = reference_date - datetime.timedelta(days=max_age)
    return latest_date < cutoff


def _build_series_map(
    observations: Sequence[Observation],
    indicators: Sequence[SourceIndicatorSpec],
) -> dict[tuple[str, str], list[Observation]]:
    """Group observations by (source_id, indicator_code) for indicators in scope.

    Only includes observations that match an indicator in the provided
    list (by source_id + indicator_code).
    """
    # Build lookup: (source_id, indicator_code) -> SourceIndicatorSpec
    indicator_keys: set[tuple[str, str]] = set()
    for spec in indicators:
        indicator_keys.add((spec.source_id, spec.indicator_code))

    result: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for obs in observations:
        key = (obs.source_id, obs.indicator_code)
        if key in indicator_keys:
            result[key].append(obs)

    # Sort each series by date
    for series in result.values():
        series.sort(key=lambda o: o.date)

    return dict(result)


def _latest_vintage_values(observations: list[Observation]) -> list[float]:
    """Extract value series using latest vintage per date.

    When multiple vintages exist for the same date, only the latest
    vintage's value is used (the corrected reading).
    """
    # Group by date, keep latest vintage
    by_date: dict[datetime.date, Observation] = {}
    for obs in observations:
        existing = by_date.get(obs.date)
        if existing is None or obs.vintage > existing.vintage:
            by_date[obs.date] = obs

    # Return values in date order
    return [by_date[d].value for d in sorted(by_date)]


def _score_dimension_standard(
    iso3: str,
    dimension_name: str,
    observations: Sequence[Observation],
    indicator_map: Sequence[SourceIndicatorSpec],
    config: ScoringConfig,
    reference_date: datetime.date,
) -> DimensionScore:
    """Score a dimension using frequency-tiered, concept-deduplicated z-scores.

    Ported from v1 ``Scorer._score_dimension()`` (scorer.py lines 499-604).

    Two-level aggregation:

    1. **Concept dedup within tier:** Series sharing the same concept tag
       within the same frequency tier are averaged into one concept-level
       z-score. This prevents the same underlying signal from getting
       double votes when multiple sources cover it.

    2. **Frequency-tiered weighting:** Concept-level z-scores are grouped
       by frequency, averaged within each tier, and combined across tiers
       using configurable weights normalised to whichever tiers have data.
    """
    # Filter indicators to this dimension
    dim_indicators = [spec for spec in indicator_map if spec.dimension == dimension_name]

    if not dim_indicators:
        return DimensionScore(dimension=dimension_name, value=None)

    # Build (source_id, indicator_code) -> [observations] map
    series_map = _build_series_map(observations, dim_indicators)

    # Build indicator lookup for frequency/concept
    indicator_lookup: dict[tuple[str, str], SourceIndicatorSpec] = {
        (spec.source_id, spec.indicator_code): spec for spec in dim_indicators
    }

    # Step 1: collect raw z-scores grouped by (frequency, concept)
    tier_concept_zscores: dict[tuple[str, str], list[float]] = defaultdict(list)
    stale_count = 0
    series_used = 0

    for (source_id, indicator_code), obs_list in series_map.items():
        if not obs_list:
            continue

        spec = indicator_lookup.get((source_id, indicator_code))
        if spec is None:
            continue

        frequency = spec.frequency
        # Concept tag for deduplication. Untagged series fall back to
        # a unique key so they each get their own vote.
        concept = spec.concept or f"_untagged_{source_id}_{indicator_code}"

        # Extract values using latest vintage per date
        values = _latest_vintage_values(obs_list)
        if not values:
            continue

        # Check staleness
        latest_date = max(o.date for o in obs_list)
        if _is_stale(latest_date, frequency, reference_date, config.staleness_gates):
            stale_count += 1
            continue

        # Compute z-score
        halflife = config.ewm_halflife.get(frequency, config.ewm_halflife.get("monthly", 12))
        z = compute_zscore(
            values,
            method=config.zscore_method,
            halflife=halflife,
            min_observations=config.min_observations,
        )
        if z is not None:
            tier_concept_zscores[(frequency, concept)].append(z)
            series_used += 1

    if stale_count > 0:
        logger.debug(
            "dimension.stale_series",
            iso3=iso3,
            dimension=dimension_name,
            stale_count=stale_count,
        )

    if not tier_concept_zscores:
        return DimensionScore(
            dimension=dimension_name,
            value=None,
            n_series_stale=stale_count,
        )

    # Step 2: collapse same (tier, concept) into one concept-level z-score
    tier_zscores: dict[str, list[float]] = defaultdict(list)
    concept_set: set[str] = set()
    for (freq, concept), z_list in tier_concept_zscores.items():
        concept_avg = sum(z_list) / len(z_list)
        tier_zscores[freq].append(concept_avg)
        concept_set.add(concept)

    # Step 3: weighted combination of tier averages
    weighted_sum = 0.0
    weight_sum = 0.0
    default_weight = 0.5

    for freq, concept_z_list in tier_zscores.items():
        tier_avg = sum(concept_z_list) / len(concept_z_list)
        w = config.frequency_weights.get(freq, default_weight)
        weighted_sum += w * tier_avg
        weight_sum += w

    if weight_sum == 0:
        return DimensionScore(
            dimension=dimension_name,
            value=None,
            n_series_used=series_used,
            n_series_stale=stale_count,
            n_concepts=len(concept_set),
        )

    score = weighted_sum / weight_sum
    clamped = max(config.scale_min, min(config.scale_max, score))

    return DimensionScore(
        dimension=dimension_name,
        value=round(clamped, 6),
        n_series_used=series_used,
        n_series_stale=stale_count,
        n_concepts=len(concept_set),
    )


class StandardDimension(Dimension):
    """Handles growth_momentum, external_balance, monetary_stance.

    All three use the same frequency-tiered, concept-deduplicated
    z-scoring algorithm. They differ only in which indicators are
    tagged to their dimension name.
    """

    def __init__(self, dimension_name: str) -> None:
        self._name = dimension_name

    @property
    def name(self) -> str:
        return self._name

    def score(
        self,
        iso3: str,
        observations: Sequence[Observation],
        events: Sequence[EventRecord],
        indicator_map: Sequence[SourceIndicatorSpec],
        config: ScoringConfig,
        reference_date: datetime.date,
    ) -> DimensionScore:
        return _score_dimension_standard(
            iso3,
            self._name,
            observations,
            indicator_map,
            config,
            reference_date,
        )


class RiskSentimentDimension(Dimension):
    """risk_sentiment = fundamentals + yfinance momentum + GDELT tone.

    Ported from v1 ``Scorer._score_risk_sentiment()`` (scorer.py lines 606-681).

    Combines:
    - Fundamental z-scores from indicators tagged as risk_sentiment
      (FRED treasury yields, VIX, EM spreads, BIS property prices, etc.)
    - FX momentum from yfinance FX_USD observations (currency weakening = negative)
    - Equity momentum from yfinance EQUITY_INDEX observations (index falling = negative)
    - GDELT news tone from EventRecords (negative tone = negative)

    The fundamental component is the standard frequency-weighted blend.
    yfinance and GDELT are daily-frequency signals. All components are
    combined using tier-weighted logic where the fundamental blend gets
    a dedicated '_fundamental' tier at weight 1.0.
    """

    @property
    def name(self) -> str:
        return "risk_sentiment"

    def score(
        self,
        iso3: str,
        observations: Sequence[Observation],
        events: Sequence[EventRecord],
        indicator_map: Sequence[SourceIndicatorSpec],
        config: ScoringConfig,
        reference_date: datetime.date,
    ) -> DimensionScore:
        tier_zscores: dict[str, list[float]] = defaultdict(list)
        total_series = 0
        total_stale = 0
        concepts: set[str] = set()

        # Multi-source fundamental component
        fundamental = _score_dimension_standard(
            iso3,
            "risk_sentiment",
            observations,
            indicator_map,
            config,
            reference_date,
        )
        if fundamental.value is not None:
            tier_zscores["_fundamental"].append(fundamental.value)
            total_series += fundamental.n_series_used
            total_stale += fundamental.n_series_stale
            concepts.add("_fundamental")

        # yfinance FX momentum (daily)
        fx_prices = self._extract_price_series(observations, "FX_USD")
        if fx_prices:
            halflife = config.ewm_halflife.get("daily", 252)
            fx_z = compute_momentum_zscore(
                fx_prices,
                window=config.momentum_window,
                method=config.zscore_method,
                halflife=halflife,
                min_observations=config.min_observations,
            )
            if fx_z is not None:
                tier_zscores["daily"].append(fx_z)
                total_series += 1
                concepts.add("fx_momentum")

        # yfinance equity momentum (daily)
        eq_prices = self._extract_price_series(observations, "EQUITY_INDEX")
        if eq_prices:
            halflife = config.ewm_halflife.get("daily", 252)
            eq_z = compute_momentum_zscore(
                eq_prices,
                window=config.momentum_window,
                method=config.zscore_method,
                halflife=halflife,
                min_observations=config.min_observations,
            )
            if eq_z is not None:
                tier_zscores["daily"].append(eq_z)
                total_series += 1
                concepts.add("equity_momentum")

        # GDELT tone (daily) — from EventRecords, not Observations
        tone_values = self._extract_tone_series(events)
        if tone_values:
            halflife = config.ewm_halflife.get("daily", 252)
            tone_z = compute_zscore(
                tone_values,
                method=config.zscore_method,
                halflife=halflife,
                min_observations=config.min_observations,
            )
            if tone_z is not None:
                tier_zscores["daily"].append(tone_z)
                total_series += 1
                concepts.add("news_tone")

        if not tier_zscores:
            return DimensionScore(
                dimension="risk_sentiment",
                value=None,
                n_series_stale=total_stale,
            )

        # Tier-weighted combination
        # "_fundamental" gets weight 1.0 so fundamentals and market
        # signals are balanced (v1 scorer.py lines 666-676).
        weighted_sum = 0.0
        weight_sum = 0.0
        for freq, z_list in tier_zscores.items():
            tier_avg = sum(z_list) / len(z_list)
            w = 1.0 if freq == "_fundamental" else config.frequency_weights.get(freq, 0.5)
            weighted_sum += w * tier_avg
            weight_sum += w

        if weight_sum == 0:
            return DimensionScore(
                dimension="risk_sentiment",
                value=None,
                n_series_used=total_series,
                n_series_stale=total_stale,
                n_concepts=len(concepts),
            )

        score = weighted_sum / weight_sum
        clamped = max(config.scale_min, min(config.scale_max, score))

        return DimensionScore(
            dimension="risk_sentiment",
            value=round(clamped, 6),
            n_series_used=total_series,
            n_series_stale=total_stale,
            n_concepts=len(concepts),
        )

    @staticmethod
    def _extract_price_series(
        observations: Sequence[Observation],
        indicator_code: str,
    ) -> list[float]:
        """Extract a date-ordered price series for a given indicator.

        Used for FX_USD and EQUITY_INDEX momentum z-scores.
        Uses latest vintage per date.
        """
        relevant = [o for o in observations if o.indicator_code == indicator_code]
        if not relevant:
            return []

        # Latest vintage per date
        by_date: dict[datetime.date, Observation] = {}
        for obs in relevant:
            existing = by_date.get(obs.date)
            if existing is None or obs.vintage > existing.vintage:
                by_date[obs.date] = obs

        return [by_date[d].value for d in sorted(by_date)]

    @staticmethod
    def _extract_tone_series(events: Sequence[EventRecord]) -> list[float]:
        """Extract date-ordered GDELT tone values from EventRecords."""
        tone_events = [e for e in events if e.event_type == "tone" and e.value is not None]
        if not tone_events:
            return []

        # One tone value per date (GDELT produces daily aggregates)
        by_date: dict[datetime.date, float] = {}
        for event in tone_events:
            assert event.value is not None  # filtered above
            by_date[event.date] = event.value

        return [by_date[d] for d in sorted(by_date)]
