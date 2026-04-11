"""Tests for SQLAlchemy ORM models and their domain conversions.

These tests are in-memory only — they construct ORM instances but
never commit them to a database. That keeps the test suite fast and
hermetic. Integration tests against a real Postgres arrive in a
later phase.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from hornet.db.models import ObservationRow
from hornet.domain import Observation


def _sample_obs(**overrides: object) -> Observation:
    defaults: dict[str, object] = {
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


class TestObservationRow:
    def test_tablename(self) -> None:
        assert ObservationRow.__tablename__ == "observations"

    def test_from_domain_preserves_fields(self) -> None:
        obs = _sample_obs()
        row = ObservationRow.from_domain(obs)
        assert row.country_iso3 == "NGA"
        assert row.indicator_code == "CPI_YOY"
        assert row.source_id == "fred"
        assert row.value == 18.5
        assert row.frequency == "monthly"
        assert row.quality_flags == []

    def test_from_domain_preserves_quality_flags(self) -> None:
        obs = _sample_obs(quality_flags=("outlier_4sigma",))
        row = ObservationRow.from_domain(obs)
        assert row.quality_flags == ["outlier_4sigma"]

    def test_roundtrip_from_domain_and_back(self) -> None:
        obs = _sample_obs()
        row = ObservationRow.from_domain(obs)
        obs_back = row.to_domain()
        assert obs == obs_back

    def test_roundtrip_with_quality_flags(self) -> None:
        obs = _sample_obs(quality_flags=("outlier_4sigma", "flatline"))
        row = ObservationRow.from_domain(obs)
        obs_back = row.to_domain()
        assert obs_back.quality_flags == ("outlier_4sigma", "flatline")
