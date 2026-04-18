"""Tests for the spread builder."""

from __future__ import annotations

import datetime

from hornet.derived.spreads import (
    DEFAULT_SPREADS,
    SpreadSpec,
    compute_spread,
    compute_spreads,
)
from hornet.domain.observation import Observation


def _obs(
    indicator: str,
    value: float,
    date: datetime.date | None = None,
) -> Observation:
    now = datetime.datetime(2026, 4, 12, tzinfo=datetime.UTC)
    return Observation(
        country_iso3="USA",
        indicator_code=indicator,
        source_id="fred",
        date=date or datetime.date(2026, 4, 1),
        value=value,
        frequency="daily",
        vintage=now,
        ingested_at=now,
    )


SPEC_10Y_2Y = SpreadSpec(
    long_indicator="DGS10",
    short_indicator="DGS2",
    result_code="SPREAD_10Y_2Y",
    name="10Y-2Y Treasury Spread",
)


def test_compute_spread_basic() -> None:
    """Spread = long - short on matching dates."""
    long = [_obs("DGS10", 4.50, datetime.date(2026, 4, 1))]
    short = [_obs("DGS2", 4.20, datetime.date(2026, 4, 1))]

    result = compute_spread(long, short, SPEC_10Y_2Y)
    assert len(result) == 1
    assert result[0].indicator_code == "SPREAD_10Y_2Y"
    assert result[0].source_id == "derived"
    assert abs(result[0].value - 0.30) < 1e-6
    assert result[0].country_iso3 == "USA"


def test_compute_spread_negative() -> None:
    """Negative spread = curve inversion."""
    long = [_obs("DGS10", 3.80, datetime.date(2026, 4, 1))]
    short = [_obs("DGS2", 4.50, datetime.date(2026, 4, 1))]

    result = compute_spread(long, short, SPEC_10Y_2Y)
    assert len(result) == 1
    assert result[0].value < 0
    assert abs(result[0].value - (-0.70)) < 1e-6


def test_compute_spread_multiple_dates() -> None:
    """Spread computed for each matching date."""
    dates = [datetime.date(2026, 4, i) for i in range(1, 4)]
    long = [_obs("DGS10", 4.5 + i * 0.1, d) for i, d in enumerate(dates)]
    short = [_obs("DGS2", 4.2 + i * 0.05, d) for i, d in enumerate(dates)]

    result = compute_spread(long, short, SPEC_10Y_2Y)
    assert len(result) == 3
    # Verify dates are sorted
    result_dates = [o.date for o in result]
    assert result_dates == sorted(result_dates)


def test_compute_spread_unmatched_dates_skipped() -> None:
    """Dates present in only one leg are excluded."""
    long = [
        _obs("DGS10", 4.5, datetime.date(2026, 4, 1)),
        _obs("DGS10", 4.6, datetime.date(2026, 4, 2)),
    ]
    short = [
        _obs("DGS2", 4.2, datetime.date(2026, 4, 1)),
        # No data for April 2
    ]

    result = compute_spread(long, short, SPEC_10Y_2Y)
    assert len(result) == 1
    assert result[0].date == datetime.date(2026, 4, 1)


def test_compute_spread_empty_legs() -> None:
    """Empty input produces empty output."""
    result = compute_spread([], [], SPEC_10Y_2Y)
    assert result == []


def test_compute_spread_latest_vintage_used() -> None:
    """When multiple vintages exist for a date, the latest is used."""
    old = datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC)
    new = datetime.datetime(2026, 4, 2, tzinfo=datetime.UTC)

    long = [
        Observation(
            country_iso3="USA",
            indicator_code="DGS10",
            source_id="fred",
            date=datetime.date(2026, 4, 1),
            value=4.50,
            frequency="daily",
            vintage=old,
            ingested_at=old,
        ),
        Observation(
            country_iso3="USA",
            indicator_code="DGS10",
            source_id="fred",
            date=datetime.date(2026, 4, 1),
            value=4.55,
            frequency="daily",
            vintage=new,
            ingested_at=new,
        ),
    ]
    short = [_obs("DGS2", 4.20, datetime.date(2026, 4, 1))]

    result = compute_spread(long, short, SPEC_10Y_2Y)
    assert len(result) == 1
    # Should use the revised value (4.55)
    assert abs(result[0].value - 0.35) < 1e-6


def test_compute_spreads_batch() -> None:
    """compute_spreads processes multiple specs from mixed observations."""
    d = datetime.date(2026, 4, 1)
    observations = [
        _obs("DGS10", 4.50, d),
        _obs("DGS2", 4.20, d),
        _obs("UST_3M", 5.10, d),
        _obs("UST_30Y", 4.80, d),
        _obs("UST_5Y", 4.35, d),
    ]

    result = compute_spreads(observations, DEFAULT_SPREADS)
    codes = {o.indicator_code for o in result}
    # Should produce spreads where both legs exist
    assert "SPREAD_10Y_2Y" in codes
    assert "SPREAD_10Y_3M" in codes
    assert "SPREAD_30Y_10Y" in codes
    assert "SPREAD_5Y_2Y" in codes


def test_compute_spreads_missing_leg_skipped() -> None:
    """Spreads with a missing leg are skipped without error."""
    observations = [
        _obs("DGS10", 4.50, datetime.date(2026, 4, 1)),
        # No DGS2, no UST_3M, etc.
    ]

    result = compute_spreads(observations, DEFAULT_SPREADS)
    # Only spreads with DGS10 as the long leg and missing short leg
    # should be skipped -- none should compute
    assert len(result) == 0


def test_spread_spec_frozen() -> None:
    import pytest

    spec = SPEC_10Y_2Y
    with pytest.raises((TypeError, ValueError)):
        spec.result_code = "other"  # type: ignore[misc]


def test_default_spreads_all_valid() -> None:
    """DEFAULT_SPREADS entries have distinct result codes."""
    codes = [s.result_code for s in DEFAULT_SPREADS]
    assert len(codes) == len(set(codes))
    for s in DEFAULT_SPREADS:
        assert s.long_indicator != s.short_indicator
