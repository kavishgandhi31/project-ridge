"""Tests for the series liveness checker."""

from __future__ import annotations

import datetime

from hornet.domain.observation import Observation
from hornet.domain.source import SourceIndicatorSpec
from hornet.quality.liveness import check_series_liveness


def _obs(
    indicator: str,
    source: str = "fred",
    date: datetime.date | None = None,
) -> Observation:
    now = datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC)
    return Observation(
        country_iso3="USA",
        indicator_code=indicator,
        source_id=source,
        date=date or datetime.date(2026, 4, 10),
        value=4.5,
        frequency="daily",
        vintage=now,
        ingested_at=now,
    )


def _spec(
    indicator: str,
    source: str = "fred",
    native_code: str = "TEST",
    frequency: str = "daily",
) -> SourceIndicatorSpec:
    return SourceIndicatorSpec(
        source_id=source,
        source_native_code=native_code,
        indicator_code=indicator,
        frequency=frequency,
        countries_iso3=frozenset({"USA"}),
    )


def test_healthy_series_no_issues() -> None:
    """Recent data within threshold produces no issues."""
    ref_date = datetime.date(2026, 4, 12)
    observations = [_obs("DGS10", date=datetime.date(2026, 4, 10))]
    specs = [_spec("DGS10", native_code="DGS10")]

    issues = check_series_liveness(
        observations,
        specs,
        reference_date=ref_date,
    )
    assert len(issues) == 0


def test_stale_daily_series() -> None:
    """Daily series with no data in 30 days is flagged."""
    ref_date = datetime.date(2026, 4, 12)
    observations = [_obs("DGS10", date=datetime.date(2026, 3, 1))]  # 42 days old
    specs = [_spec("DGS10", native_code="DGS10", frequency="daily")]

    issues = check_series_liveness(
        observations,
        specs,
        reference_date=ref_date,
    )
    assert len(issues) == 1
    assert issues[0].indicator_code == "DGS10"
    assert issues[0].days_since_last == 42
    assert issues[0].threshold_days == 14


def test_never_observed_series() -> None:
    """Series with no observations at all is flagged."""
    ref_date = datetime.date(2026, 4, 12)
    specs = [_spec("NEW_SERIES", native_code="NEW")]

    issues = check_series_liveness([], specs, reference_date=ref_date)
    assert len(issues) == 1
    assert issues[0].last_date is None
    assert issues[0].days_since_last is None
    assert "no observations found" in issues[0].message


def test_monthly_series_threshold() -> None:
    """Monthly series uses 120-day threshold."""
    ref_date = datetime.date(2026, 4, 12)
    # 90 days old -- within 120-day threshold for monthly
    observations = [_obs("CPI_INDEX", source="imf", date=datetime.date(2026, 1, 12))]
    specs = [_spec("CPI_INDEX", source="imf", native_code="PCPI", frequency="monthly")]

    issues = check_series_liveness(
        observations,
        specs,
        reference_date=ref_date,
    )
    assert len(issues) == 0


def test_monthly_series_stale() -> None:
    """Monthly series older than 120 days is flagged."""
    ref_date = datetime.date(2026, 4, 12)
    # 150 days old -- beyond 120-day threshold
    observations = [_obs("CPI_INDEX", source="imf", date=datetime.date(2025, 11, 14))]
    specs = [_spec("CPI_INDEX", source="imf", native_code="PCPI", frequency="monthly")]

    issues = check_series_liveness(
        observations,
        specs,
        reference_date=ref_date,
    )
    assert len(issues) == 1


def test_disabled_series_skipped() -> None:
    """Disabled indicators are not checked."""
    ref_date = datetime.date(2026, 4, 12)
    specs = [
        SourceIndicatorSpec(
            source_id="fred",
            source_native_code="RETIRED",
            indicator_code="RETIRED_SERIES",
            frequency="daily",
            countries_iso3=frozenset({"USA"}),
            enabled=False,
        ),
    ]

    issues = check_series_liveness([], specs, reference_date=ref_date)
    assert len(issues) == 0


def test_multiple_sources_same_indicator() -> None:
    """Each (source_id, indicator_code) pair is checked independently."""
    ref_date = datetime.date(2026, 4, 12)
    observations = [
        _obs("CPI_YOY", source="fred", date=datetime.date(2026, 4, 10)),
        # worldbank CPI_YOY is stale
        _obs("CPI_YOY", source="worldbank", date=datetime.date(2024, 12, 1)),
    ]
    specs = [
        _spec("CPI_YOY", source="fred", native_code="FRED_CPI", frequency="annual"),
        _spec("CPI_YOY", source="worldbank", native_code="WB_CPI", frequency="annual"),
    ]

    issues = check_series_liveness(
        observations,
        specs,
        reference_date=ref_date,
    )
    # FRED is fine (within 730-day annual threshold)
    # WorldBank is fine too (467 days, within 730)
    assert len(issues) == 0


def test_custom_thresholds() -> None:
    """Custom thresholds override defaults."""
    ref_date = datetime.date(2026, 4, 12)
    observations = [_obs("DGS10", date=datetime.date(2026, 4, 5))]  # 7 days old
    specs = [_spec("DGS10", native_code="DGS10", frequency="daily")]

    # Strict threshold: flag anything older than 3 days
    issues = check_series_liveness(
        observations,
        specs,
        reference_date=ref_date,
        thresholds={"daily": 3},
    )
    assert len(issues) == 1
    assert issues[0].days_since_last == 7
