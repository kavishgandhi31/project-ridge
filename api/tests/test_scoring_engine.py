"""Tests for the ScoringEngine — full integration of all scoring components."""

from __future__ import annotations

import datetime

from hornet.domain.event import EventRecord
from hornet.domain.observation import Observation
from hornet.domain.scoring import ScoringConfig
from hornet.domain.source import SourceIndicatorSpec
from hornet.scoring.engine import ScoringEngine

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()


def _config() -> ScoringConfig:
    return ScoringConfig(
        dimension_weights={
            "growth_momentum": 0.25,
            "external_balance": 0.25,
            "monetary_stance": 0.25,
            "risk_sentiment": 0.25,
        },
    )


def _obs(
    indicator_code: str,
    value: float,
    date: datetime.date,
    *,
    source_id: str = "worldbank",
    frequency: str = "annual",
    country_iso3: str = "NGA",
) -> Observation:
    return Observation(
        country_iso3=country_iso3,
        indicator_code=indicator_code,
        source_id=source_id,
        date=date,
        value=value,
        frequency=frequency,
        vintage=_NOW,
        ingested_at=_NOW,
    )


def _spec(
    indicator_code: str,
    dimension: str,
    *,
    concept: str | None = None,
    source_id: str = "worldbank",
    frequency: str = "annual",
    global_signal: bool = False,
) -> SourceIndicatorSpec:
    return SourceIndicatorSpec(
        source_id=source_id,
        source_native_code=f"native_{indicator_code}",
        indicator_code=indicator_code,
        frequency=frequency,
        countries_iso3=frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"}),
        dimension=dimension,
        concept=concept,
        global_signal=global_signal,
    )


def _make_series(
    indicator_code: str,
    n: int,
    *,
    base: float = 10.0,
    step: float = 0.5,
    source_id: str = "worldbank",
    frequency: str = "annual",
    country_iso3: str = "NGA",
) -> list[Observation]:
    freq_intervals = {
        "daily": 1,
        "weekly": 7,
        "monthly": 30,
        "quarterly": 90,
        "annual": 365,
        "forecast": 180,
    }
    interval = freq_intervals.get(frequency, 365)
    return [
        _obs(
            indicator_code,
            base + i * step,
            _TODAY - datetime.timedelta(days=(n - 1 - i) * interval),
            source_id=source_id,
            frequency=frequency,
            country_iso3=country_iso3,
        )
        for i in range(n)
    ]


class TestScoringEngine:
    def test_score_country_all_dimensions(self) -> None:
        """Full scoring with indicators across all 4 dimensions."""
        indicators = [
            _spec("GDP_GROWTH", "growth_momentum", concept="gdp"),
            _spec(
                "CLI",
                "growth_momentum",
                concept="leading_indicator",
                source_id="oecd",
                frequency="monthly",
            ),
            _spec("CURRENT_ACCOUNT_GDP", "external_balance", concept="current_account"),
            _spec("RESERVES_MONTHS_IMPORTS", "external_balance", concept="fx_reserves"),
            _spec("CPI_YOY", "monetary_stance", concept="cpi"),
            _spec(
                "POLICY_RATE",
                "monetary_stance",
                concept="policy_rate",
                source_id="imf",
                frequency="monthly",
            ),
            _spec(
                "VIXCLS",
                "risk_sentiment",
                concept="volatility",
                source_id="fred",
                frequency="daily",
            ),
        ]

        observations = (
            _make_series("GDP_GROWTH", 20, base=3.0, step=0.2)
            + _make_series("CLI", 20, base=100.0, step=0.1, source_id="oecd", frequency="monthly")
            + _make_series("CURRENT_ACCOUNT_GDP", 20, base=-2.0, step=0.1)
            + _make_series("RESERVES_MONTHS_IMPORTS", 20, base=5.0, step=0.1)
            + _make_series("CPI_YOY", 20, base=8.0, step=-0.1)
            + _make_series(
                "POLICY_RATE", 20, base=12.0, step=-0.2, source_id="imf", frequency="monthly"
            )
            + _make_series("VIXCLS", 20, base=15.0, step=0.3, source_id="fred", frequency="daily")
        )

        engine = ScoringEngine(_config(), indicators)
        result = engine.score_country("NGA", observations, [], _TODAY)

        assert result.country_iso3 == "NGA"
        assert result.run_id  # non-empty
        assert len(result.dimensions) == 4

        # All dimensions should have scores
        for dim_name in (
            "growth_momentum",
            "external_balance",
            "monetary_stance",
            "risk_sentiment",
        ):
            ds = result.dimensions[dim_name]
            assert ds.value is not None, f"{dim_name} should have a score"
            assert -3.0 <= ds.value <= 3.0

        assert result.composite is not None
        assert -3.0 <= result.composite <= 3.0
        assert result.coverage_fraction == 1.0

    def test_score_country_partial_coverage(self) -> None:
        """Only one dimension has data — composite should still work if >= min_dims."""
        indicators = [
            _spec("GDP_GROWTH", "growth_momentum", concept="gdp"),
            _spec("CPI_YOY", "monetary_stance", concept="cpi"),
        ]
        observations = _make_series("GDP_GROWTH", 20, base=3.0, step=0.2) + _make_series(
            "CPI_YOY", 20, base=8.0, step=0.1
        )

        engine = ScoringEngine(_config(), indicators)
        result = engine.score_country("NGA", observations, [], _TODAY)

        assert result.dimensions["growth_momentum"].value is not None
        assert result.dimensions["monetary_stance"].value is not None
        assert result.dimensions["external_balance"].value is None
        assert result.dimensions["risk_sentiment"].value is None
        assert result.composite is not None  # 2 dims >= min_dimensions_for_composite
        assert result.coverage_fraction == 0.5

    def test_score_country_no_data(self) -> None:
        """No observations at all — all dimensions should be None."""
        indicators = [_spec("GDP_GROWTH", "growth_momentum", concept="gdp")]
        engine = ScoringEngine(_config(), indicators)
        result = engine.score_country("NGA", [], [], _TODAY)

        for ds in result.dimensions.values():
            assert ds.value is None
        assert result.composite is None
        assert result.coverage_fraction == 0.0

    def test_score_country_with_events(self) -> None:
        """GDELT tone and volume events should be processed."""
        indicators = [
            _spec(
                "VIXCLS",
                "risk_sentiment",
                concept="volatility",
                source_id="fred",
                frequency="daily",
            ),
        ]
        observations = _make_series(
            "VIXCLS",
            20,
            source_id="fred",
            frequency="daily",
            base=15.0,
            step=0.5,
        )

        # GDELT tone events
        tone_events = [
            EventRecord(
                country_iso3="NGA",
                source_id="gdelt",
                event_type="tone",
                date=_TODAY - datetime.timedelta(days=i),
                dedup_key=f"gdelt:tone:NGA:{_TODAY - datetime.timedelta(days=i)}",
                value=-1.5 + i * 0.05,
                ingested_at=_NOW,
            )
            for i in range(30, 0, -1)
        ]
        # GDELT volume events (normal volume, no heat)
        volume_events = [
            EventRecord(
                country_iso3="NGA",
                source_id="gdelt",
                event_type="volume",
                date=_TODAY - datetime.timedelta(days=i),
                dedup_key=f"gdelt:volume:NGA:{_TODAY - datetime.timedelta(days=i)}",
                value=100.0 + i * 0.5,
                ingested_at=_NOW,
            )
            for i in range(30, 0, -1)
        ]

        engine = ScoringEngine(_config(), indicators)
        result = engine.score_country(
            "NGA",
            observations,
            tone_events + volume_events,
            _TODAY,
        )

        assert result.dimensions["risk_sentiment"].value is not None
        # Volume is normal, so no news heat
        assert result.news_heat is None

    def test_score_all_batch(self) -> None:
        """Batch scoring across multiple countries."""
        indicators = [
            _spec("GDP_GROWTH", "growth_momentum", concept="gdp"),
            _spec("CPI_YOY", "monetary_stance", concept="cpi"),
        ]

        observations_by_country = {
            "NGA": (
                _make_series("GDP_GROWTH", 20, base=3.0, step=0.2, country_iso3="NGA")
                + _make_series("CPI_YOY", 20, base=8.0, step=0.1, country_iso3="NGA")
            ),
            "TUR": (
                _make_series("GDP_GROWTH", 20, base=5.0, step=0.3, country_iso3="TUR")
                + _make_series("CPI_YOY", 20, base=60.0, step=1.0, country_iso3="TUR")
            ),
        }

        engine = ScoringEngine(_config(), indicators)
        results = engine.score_all(
            ["NGA", "TUR"],
            observations_by_country,
            {},
            _TODAY,
        )

        assert len(results) == 2
        assert results[0].country_iso3 == "NGA"
        assert results[1].country_iso3 == "TUR"
        # All results share the same run_id
        assert results[0].run_id == results[1].run_id
        # Both should have scores
        assert results[0].composite is not None
        assert results[1].composite is not None

    def test_news_heat_triggered(self) -> None:
        """Volume spike should trigger news heat."""
        indicators: list[SourceIndicatorSpec] = []

        # Normal volume for 29 days, then a huge spike
        volume_events = [
            EventRecord(
                country_iso3="NGA",
                source_id="gdelt",
                event_type="volume",
                date=_TODAY - datetime.timedelta(days=i),
                dedup_key=f"gdelt:volume:NGA:{_TODAY - datetime.timedelta(days=i)}",
                value=100.0,
                ingested_at=_NOW,
            )
            for i in range(29, 0, -1)
        ] + [
            EventRecord(
                country_iso3="NGA",
                source_id="gdelt",
                event_type="volume",
                date=_TODAY,
                dedup_key=f"gdelt:volume:NGA:{_TODAY}",
                value=500.0,  # 5x normal
                ingested_at=_NOW,
            ),
        ]

        engine = ScoringEngine(_config(), indicators)
        result = engine.score_country("NGA", [], volume_events, _TODAY)

        assert result.news_heat is not None
        assert result.news_heat.sigma >= 2.0
        assert result.news_heat.volume_ratio > 1.0
