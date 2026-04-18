"""Tests for the canonical domain types.

These tests pin the contract: anything downstream can rely on these
validation behaviors. When you change them, downstream code may break
intentionally — run the full test suite to confirm.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from hornet.domain import (
    FetchRequest,
    IndicatorSpec,
    Observation,
    SourceManifest,
)


def _obs(**overrides: Any) -> Observation:
    """Build an Observation with sensible defaults, overriding select fields."""
    defaults: dict[str, Any] = {
        "country_iso3": "NGA",
        "indicator_code": "CPI_YOY",
        "source_id": "fred",
        "date": date(2026, 3, 1),
        "value": 18.5,
        "frequency": "monthly",
        "vintage": datetime(2026, 4, 1, tzinfo=UTC),
        "ingested_at": datetime(2026, 4, 11, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Observation(**defaults)


class TestObservation:
    def test_valid_observation(self) -> None:
        obs = _obs()
        assert obs.country_iso3 == "NGA"
        assert obs.value == 18.5
        assert obs.quality_flags == ()

    def test_country_iso3_uppercased(self) -> None:
        obs = _obs(country_iso3="nga")
        assert obs.country_iso3 == "NGA"

    def test_country_iso3_must_be_three_chars(self) -> None:
        with pytest.raises(ValidationError):
            _obs(country_iso3="NG")
        with pytest.raises(ValidationError):
            _obs(country_iso3="NIGR")

    def test_observation_is_immutable(self) -> None:
        obs = _obs()
        with pytest.raises(ValidationError):
            obs.value = 99.0  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            Observation(
                country_iso3="NGA",
                indicator_code="CPI_YOY",
                source_id="fred",
                date=date(2026, 1, 1),
                value=1.0,
                frequency="monthly",
                vintage=datetime(2026, 1, 1, tzinfo=UTC),
                ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
                nonsense_field="oops",  # type: ignore[call-arg]
            )

    def test_rejects_invalid_frequency(self) -> None:
        with pytest.raises(ValidationError):
            _obs(frequency="hourly")

    def test_quality_flags_default_empty(self) -> None:
        assert _obs().quality_flags == ()

    def test_quality_flags_accept_tuple(self) -> None:
        obs = _obs(quality_flags=("outlier_4sigma",))
        assert "outlier_4sigma" in obs.quality_flags


class TestSourceManifest:
    def test_manifest_with_indicator(self) -> None:
        manifest = SourceManifest(
            source_id="fred",
            indicators=(
                IndicatorSpec(
                    indicator_code="CPI_YOY",
                    source_native_code="FPCPITOTLZGNGA",
                    frequency="monthly",
                    countries_iso3=frozenset({"NGA"}),
                ),
            ),
            discovered_at=datetime(2026, 4, 11, tzinfo=UTC),
        )
        assert len(manifest.indicators) == 1
        assert manifest.indicators[0].indicator_code == "CPI_YOY"
        assert "NGA" in manifest.indicators[0].countries_iso3

    def test_empty_manifest_is_valid(self) -> None:
        manifest = SourceManifest(
            source_id="stub",
            indicators=(),
            discovered_at=datetime(2026, 4, 11, tzinfo=UTC),
        )
        assert manifest.indicators == ()


class TestFetchRequest:
    def test_empty_filters_mean_all(self) -> None:
        req = FetchRequest(source_id="fred")
        assert req.countries_iso3 == frozenset()
        assert req.indicator_codes == frozenset()
        assert req.start is None
        assert req.end is None

    def test_scoped_request(self) -> None:
        req = FetchRequest(
            source_id="fred",
            countries_iso3=frozenset({"NGA", "BRA"}),
            indicator_codes=frozenset({"CPI_YOY"}),
            start=date(2020, 1, 1),
            end=date(2026, 4, 1),
        )
        assert len(req.countries_iso3) == 2
        assert req.indicator_codes == frozenset({"CPI_YOY"})
