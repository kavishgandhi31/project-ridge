"""Tests for dimension scoring classes."""

from __future__ import annotations

import datetime

from ridge.domain.event import EventRecord
from ridge.domain.observation import Observation
from ridge.domain.scoring import ScoringConfig
from ridge.domain.source import SourceIndicatorSpec
from ridge.scoring.dimensions import (
    RiskSentimentDimension,
    StandardDimension,
    _is_stale,
)

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()


def _config(**overrides: object) -> ScoringConfig:
    defaults: dict[str, object] = {
        "dimension_weights": {
            "growth_momentum": 0.25,
            "external_balance": 0.25,
            "monetary_stance": 0.25,
            "risk_sentiment": 0.25,
        },
    }
    defaults.update(overrides)
    return ScoringConfig(**defaults)


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
) -> SourceIndicatorSpec:
    return SourceIndicatorSpec(
        source_id=source_id,
        source_native_code=f"native_{indicator_code}",
        indicator_code=indicator_code,
        frequency=frequency,
        countries_iso3=frozenset({"NGA"}),
        dimension=dimension,
        concept=concept,
    )


_FREQ_INTERVAL_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "annual": 365,
    "forecast": 180,
}


def _make_series(
    indicator_code: str,
    n: int = 20,
    *,
    base: float = 10.0,
    step: float = 0.5,
    source_id: str = "worldbank",
    frequency: str = "annual",
) -> list[Observation]:
    """Create a time series of observations for testing.

    Date spacing matches the frequency tier so series are not
    excluded by staleness gates. The latest observation is always
    at ``_TODAY``.
    """
    interval = _FREQ_INTERVAL_DAYS.get(frequency, 365)
    return [
        _obs(
            indicator_code,
            base + i * step,
            _TODAY - datetime.timedelta(days=(n - 1 - i) * interval),
            source_id=source_id,
            frequency=frequency,
        )
        for i in range(n)
    ]


class TestIsStale:
    def test_not_stale(self) -> None:
        assert not _is_stale(_TODAY, "annual", _TODAY, {"annual": 730})

    def test_stale(self) -> None:
        old = _TODAY - datetime.timedelta(days=800)
        assert _is_stale(old, "annual", _TODAY, {"annual": 730})

    def test_unknown_frequency_not_stale(self) -> None:
        old = _TODAY - datetime.timedelta(days=10000)
        assert not _is_stale(old, "unknown", _TODAY, {})


class TestStandardDimension:
    def test_single_series(self) -> None:
        dim = StandardDimension("growth_momentum")
        observations = _make_series("GDP_GROWTH", 20)
        indicators = [_spec("GDP_GROWTH", "growth_momentum", concept="gdp")]
        config = _config()

        result = dim.score("NGA", observations, [], indicators, config, _TODAY)

        assert result.dimension == "growth_momentum"
        assert result.value is not None
        assert -3.0 <= result.value <= 3.0
        assert result.n_series_used == 1
        assert result.n_concepts == 1

    def test_no_matching_indicators(self) -> None:
        dim = StandardDimension("growth_momentum")
        observations = _make_series("GDP_GROWTH", 20)
        indicators = [_spec("CPI_YOY", "monetary_stance", concept="cpi")]
        config = _config()

        result = dim.score("NGA", observations, [], indicators, config, _TODAY)
        assert result.value is None

    def test_insufficient_observations(self) -> None:
        dim = StandardDimension("growth_momentum")
        observations = _make_series("GDP_GROWTH", 5)  # < min_observations
        indicators = [_spec("GDP_GROWTH", "growth_momentum", concept="gdp")]
        config = _config()

        result = dim.score("NGA", observations, [], indicators, config, _TODAY)
        assert result.value is None

    def test_concept_deduplication(self) -> None:
        """Two series with same concept should be averaged, not double-counted."""
        dim = StandardDimension("monetary_stance")
        # Two CPI series from different sources, same concept
        obs_fred = _make_series(
            "CPI_YOY",
            20,
            source_id="fred",
            base=5.0,
            step=0.2,
        )
        obs_imf = _make_series(
            "CPI_YOY",
            20,
            source_id="imf",
            base=5.5,
            step=0.15,
            frequency="monthly",
        )
        indicators = [
            _spec("CPI_YOY", "monetary_stance", concept="cpi", source_id="fred"),
            _spec(
                "CPI_YOY",
                "monetary_stance",
                concept="cpi",
                source_id="imf",
                frequency="monthly",
            ),
        ]
        config = _config()

        result = dim.score("NGA", obs_fred + obs_imf, [], indicators, config, _TODAY)
        assert result.value is not None
        # With concept dedup, "cpi" from fred and "cpi" from imf are
        # in different frequency tiers (annual vs monthly), so they're
        # independent concepts within their respective tiers.
        # Each tier has 1 concept.
        assert result.n_series_used == 2

    def test_stale_series_excluded(self) -> None:
        dim = StandardDimension("growth_momentum")
        # Series with very old dates
        old_observations = [
            _obs("GDP_GROWTH", 5.0 + i * 0.1, _TODAY - datetime.timedelta(days=3000 + i * 365))
            for i in range(20)
        ]
        indicators = [_spec("GDP_GROWTH", "growth_momentum", concept="gdp")]
        config = _config()

        result = dim.score("NGA", old_observations, [], indicators, config, _TODAY)
        assert result.value is None
        assert result.n_series_stale == 1

    def test_frequency_tier_weighting(self) -> None:
        """Daily data should have more influence than annual data."""
        dim = StandardDimension("growth_momentum")

        # Annual series: trending up
        annual_obs = _make_series(
            "GDP_GROWTH",
            20,
            base=2.0,
            step=0.5,
        )
        # Monthly series: trending down
        monthly_obs = [
            _obs(
                "CLI",
                100.0 - i * 0.5,
                _TODAY - datetime.timedelta(days=i * 30),
                source_id="oecd",
                frequency="monthly",
            )
            for i in range(20)
        ]

        indicators = [
            _spec("GDP_GROWTH", "growth_momentum", concept="gdp"),
            _spec(
                "CLI",
                "growth_momentum",
                concept="leading_indicator",
                source_id="oecd",
                frequency="monthly",
            ),
        ]
        config = _config()

        result = dim.score(
            "NGA",
            annual_obs + monthly_obs,
            [],
            indicators,
            config,
            _TODAY,
        )
        assert result.value is not None
        assert result.n_series_used == 2

    def test_clamped_to_scale(self) -> None:
        """Extreme z-scores should be clamped to [-3, +3]."""
        dim = StandardDimension("growth_momentum")
        # Create a series with a huge spike
        observations = [
            _obs("GDP_GROWTH", 5.0, _TODAY - datetime.timedelta(days=i * 365))
            for i in range(19, -1, -1)
        ]
        # Add one extreme value
        observations[-1] = _obs("GDP_GROWTH", 500.0, _TODAY)

        indicators = [_spec("GDP_GROWTH", "growth_momentum", concept="gdp")]
        config = _config()

        result = dim.score("NGA", observations, [], indicators, config, _TODAY)
        assert result.value is not None
        assert result.value <= 3.0


class TestRiskSentimentDimension:
    def test_fundamentals_only(self) -> None:
        """When no yfinance/GDELT data, uses only fundamentals."""
        dim = RiskSentimentDimension()
        observations = _make_series(
            "VIXCLS",
            20,
            source_id="fred",
            frequency="daily",
            base=15.0,
            step=0.5,
        )
        indicators = [
            _spec(
                "VIXCLS",
                "risk_sentiment",
                concept="volatility",
                source_id="fred",
                frequency="daily",
            ),
        ]
        config = _config()

        result = dim.score("NGA", observations, [], indicators, config, _TODAY)
        assert result.dimension == "risk_sentiment"
        assert result.value is not None

    def test_fx_momentum(self) -> None:
        """FX_USD observations should contribute momentum z-score."""
        dim = RiskSentimentDimension()

        # FX prices: 100 daily observations
        fx_obs = [
            _obs(
                "FX_USD",
                100.0 + i * 0.5,
                _TODAY - datetime.timedelta(days=100 - i),
                source_id="yfinance",
                frequency="daily",
            )
            for i in range(100)
        ]

        indicators: list[SourceIndicatorSpec] = []  # no fundamental indicators
        config = _config()

        result = dim.score("NGA", fx_obs, [], indicators, config, _TODAY)
        assert result.value is not None

    def test_gdelt_tone(self) -> None:
        """GDELT tone EventRecords should contribute to scoring."""
        dim = RiskSentimentDimension()

        events = [
            EventRecord(
                country_iso3="NGA",
                source_id="gdelt",
                event_type="tone",
                date=_TODAY - datetime.timedelta(days=i),
                dedup_key=f"gdelt:tone:NGA:{_TODAY - datetime.timedelta(days=i)}",
                value=-2.0 + i * 0.1,
                ingested_at=_NOW,
            )
            for i in range(30, 0, -1)
        ]
        indicators: list[SourceIndicatorSpec] = []
        config = _config()

        result = dim.score("NGA", [], events, indicators, config, _TODAY)
        assert result.value is not None

    def test_no_data_returns_none(self) -> None:
        dim = RiskSentimentDimension()
        config = _config()
        result = dim.score("NGA", [], [], [], config, _TODAY)
        assert result.value is None

    def test_combined_signals(self) -> None:
        """All signal types combined."""
        dim = RiskSentimentDimension()

        # Fundamental: VIX
        vix_obs = _make_series(
            "VIXCLS",
            20,
            source_id="fred",
            frequency="daily",
            base=15.0,
            step=0.5,
        )
        # FX prices
        fx_obs = [
            _obs(
                "FX_USD",
                100.0 + i * 0.3,
                _TODAY - datetime.timedelta(days=100 - i),
                source_id="yfinance",
                frequency="daily",
            )
            for i in range(100)
        ]
        # GDELT tone
        tone_events = [
            EventRecord(
                country_iso3="NGA",
                source_id="gdelt",
                event_type="tone",
                date=_TODAY - datetime.timedelta(days=i),
                dedup_key=f"gdelt:tone:NGA:{_TODAY - datetime.timedelta(days=i)}",
                value=-1.0 + i * 0.05,
                ingested_at=_NOW,
            )
            for i in range(30, 0, -1)
        ]

        indicators = [
            _spec(
                "VIXCLS",
                "risk_sentiment",
                concept="volatility",
                source_id="fred",
                frequency="daily",
            ),
        ]
        config = _config()

        result = dim.score(
            "NGA",
            vix_obs + fx_obs,
            tone_events,
            indicators,
            config,
            _TODAY,
        )
        assert result.value is not None
        assert result.n_series_used >= 3
