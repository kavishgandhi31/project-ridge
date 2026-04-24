"""ScoringEngine — orchestrates dimension scoring into ScoreResult.

The engine is a pure-computation object with no DB dependency. It
takes lists of Observations and EventRecords (fetched by the caller)
and produces ScoreResult objects. An async orchestrator in runner.py
wires DB repos to this engine and persists the results.

Usage:
    config = load_scoring_config_from_yaml()
    indicators = await list_source_indicators(session)
    engine = ScoringEngine(config, indicators)

    result = engine.score_country("NGA", observations, events, reference_date)
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping, Sequence

import structlog

from ridge.domain.event import EventRecord
from ridge.domain.observation import Observation
from ridge.domain.scoring import (
    ALL_DIMENSIONS,
    DimensionScore,
    ScoreResult,
    ScoringConfig,
)
from ridge.domain.source import SourceIndicatorSpec
from ridge.scoring.composite import compute_composite
from ridge.scoring.dimensions import (
    Dimension,
    RiskSentimentDimension,
    StandardDimension,
)
from ridge.scoring.news_heat import compute_news_heat

logger = structlog.get_logger(__name__)


class ScoringEngine:
    """Computes macro scores per country per dimension.

    Stateless after construction — all mutable state (observations,
    events) is passed in per call. Safe to reuse across scoring runs.
    """

    def __init__(
        self,
        config: ScoringConfig,
        indicator_map: Sequence[SourceIndicatorSpec],
    ) -> None:
        self._config = config
        self._indicator_map = list(indicator_map)

        self._dimensions: dict[str, Dimension] = {}
        for dim_name in ALL_DIMENSIONS:
            if dim_name == "risk_sentiment":
                self._dimensions[dim_name] = RiskSentimentDimension()
            else:
                self._dimensions[dim_name] = StandardDimension(dim_name)

        # Pre-compute global indicators for efficient lookup
        self._global_indicators = [spec for spec in self._indicator_map if spec.global_signal]

        logger.info(
            "scoring_engine.init",
            n_dimensions=len(self._dimensions),
            n_indicators=len(self._indicator_map),
            n_global_indicators=len(self._global_indicators),
        )

    def score_country(
        self,
        iso3: str,
        observations: Sequence[Observation],
        events: Sequence[EventRecord],
        reference_date: datetime.date,
        *,
        run_id: str | None = None,
        scored_at: datetime.datetime | None = None,
    ) -> ScoreResult:
        """Compute all dimension scores and composite for a single country.

        Parameters
        ----------
        iso3:
            Country ISO3 code.
        observations:
            All observations relevant to this country, including any
            global-signal observations (e.g. USA-origin FRED global
            series). The caller is responsible for including global
            observations alongside country-specific ones.
        events:
            All EventRecords for this country (tone, volume).
        reference_date:
            Date to use for staleness gate checks.
        run_id:
            UUID for this scoring run. Auto-generated if not provided.
        scored_at:
            Timestamp for this scoring run. Defaults to now.
        """
        run_id = run_id or str(uuid.uuid4())
        scored_at = scored_at or datetime.datetime.now(datetime.UTC)

        dimension_scores: dict[str, DimensionScore] = {}
        for dim_name, dimension in self._dimensions.items():
            dim_score = dimension.score(
                iso3,
                observations,
                events,
                self._indicator_map,
                self._config,
                reference_date,
            )
            dimension_scores[dim_name] = dim_score

        composite = compute_composite(dimension_scores, self._config)
        news_heat = compute_news_heat(events, self._config)

        n_present = sum(1 for ds in dimension_scores.values() if ds.value is not None)
        total_dims = len(self._dimensions) or 1
        coverage = n_present / total_dims

        scored = sum(1 for ds in dimension_scores.values() if ds.value is not None)
        logger.debug(
            "scoring_engine.scored_country",
            iso3=iso3,
            scored_dims=scored,
            total_dims=len(self._dimensions),
            composite=composite,
        )

        return ScoreResult(
            country_iso3=iso3,
            run_id=run_id,
            scored_at=scored_at,
            dimensions=dimension_scores,
            composite=composite,
            news_heat=news_heat,
            coverage_fraction=coverage,
        )

    def score_all(
        self,
        countries: Sequence[str],
        observations_by_country: Mapping[str, Sequence[Observation]],
        events_by_country: Mapping[str, Sequence[EventRecord]],
        reference_date: datetime.date,
    ) -> list[ScoreResult]:
        """Score every country in the list.

        Parameters
        ----------
        countries:
            List of ISO3 codes to score.
        observations_by_country:
            Maps iso3 -> observations for that country (including
            any global-signal observations).
        events_by_country:
            Maps iso3 -> EventRecords for that country.
        reference_date:
            Date to use for staleness gate checks.

        Returns
        -------
        list[ScoreResult]
            One ScoreResult per country, sorted by iso3.
        """
        run_id = str(uuid.uuid4())
        scored_at = datetime.datetime.now(datetime.UTC)

        logger.info(
            "scoring_engine.batch_start",
            n_countries=len(countries),
            run_id=run_id,
        )

        results: list[ScoreResult] = []
        for iso3 in sorted(countries):
            obs = observations_by_country.get(iso3, [])
            evts = events_by_country.get(iso3, [])
            result = self.score_country(
                iso3,
                obs,
                evts,
                reference_date,
                run_id=run_id,
                scored_at=scored_at,
            )
            results.append(result)

        scored_count = sum(1 for r in results if r.composite is not None)
        logger.info(
            "scoring_engine.batch_complete",
            n_scored=scored_count,
            n_total=len(results),
            run_id=run_id,
        )

        return results
