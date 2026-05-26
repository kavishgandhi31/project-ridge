"""Tests for ScoreResultRow -- JSONB schema contract + round-trip.

The load-bearing test is ``test_to_domain_reads_historic_row_shape``.
It pins a literal JSONB dict matching the shape rows had at one point
in time. If a future rename of ``DimensionScore`` (or ``NewsHeat``)
breaks the read, this test fails -- forcing the migrate-historic-rows
or add-alias decision instead of silently 500-ing API responses on
historic data.

The round-trip test catches symmetry breakage between domain and
storage but cannot catch this drift class, since round-trip always
uses the *current* shape on both ends.
"""

from __future__ import annotations

import datetime

from ridge.db.models.score_result import ScoreResultRow
from ridge.domain.scoring import DimensionScore, NewsHeat, ScoreResult

_NOW = datetime.datetime(2026, 4, 12, 6, 0, tzinfo=datetime.UTC)


def _make_score(*, with_news_heat: bool = False) -> ScoreResult:
    return ScoreResult(
        country_iso3="NGA",
        run_id="test-run-1",
        scored_at=_NOW,
        dimensions={
            "growth_momentum": DimensionScore(
                dimension="growth_momentum",
                value=-1.5,
                n_series_used=4,
                n_series_stale=1,
                n_concepts=3,
            ),
            "external_balance": DimensionScore(
                dimension="external_balance",
                value=None,
                n_series_used=0,
                n_series_stale=2,
                n_concepts=0,
            ),
        },
        composite=-0.75,
        news_heat=NewsHeat(sigma=2.1, volume_ratio=1.8) if with_news_heat else None,
        coverage_fraction=0.5,
    )


class TestScoreResultRow:
    def test_round_trip_preserves_all_fields(self) -> None:
        score = _make_score(with_news_heat=True)
        row = ScoreResultRow.from_domain(score)
        restored = row.to_domain()

        assert restored == score

    def test_to_domain_reads_historic_row_shape(self) -> None:
        """Lock the JSONB shape that rows had as of 2026-05-25.

        If a future rename on DimensionScore or NewsHeat breaks this
        read, the test fails loudly -- the fixer has to decide:
        migrate historic rows, add a Pydantic field alias, or accept
        the lossy read. Without this test, the breakage would only
        surface when someone tried to fetch a historic-date dashboard.
        """
        historic_dimensions = {
            "growth_momentum": {
                "dimension": "growth_momentum",
                "value": -1.5,
                "n_series_used": 4,
                "n_series_stale": 1,
                "n_concepts": 3,
            },
            "external_balance": {
                "dimension": "external_balance",
                "value": None,
                "n_series_used": 0,
                "n_series_stale": 2,
                "n_concepts": 0,
            },
        }
        historic_news_heat = {"sigma": 2.1, "volume_ratio": 1.8}

        row = ScoreResultRow(
            country_iso3="NGA",
            run_id="snap-2026-05-25",
            scored_at=_NOW,
            dimensions=historic_dimensions,
            composite=-0.75,
            news_heat=historic_news_heat,
            coverage_fraction=0.5,
        )
        score = row.to_domain()

        assert score.dimensions["growth_momentum"].value == -1.5
        assert score.dimensions["growth_momentum"].n_series_used == 4
        assert score.dimensions["external_balance"].value is None
        assert score.news_heat is not None
        assert score.news_heat.sigma == 2.1
        assert score.news_heat.volume_ratio == 1.8
