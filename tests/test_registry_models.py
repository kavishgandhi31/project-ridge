"""Tests for the CountryRow and SourceIndicatorRow ORM models.

Unit tests — no database required. Exercises the domain/ORM boundary:
``from_domain()`` and ``to_domain()`` roundtrip without losing data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hornet.db.models.country import CountryRow
from hornet.db.models.source_indicator import SourceIndicatorRow
from hornet.domain.source import CountrySpec, SourceIndicatorSpec

_NOW = datetime(2026, 4, 11, tzinfo=UTC)


class TestCountryRow:
    def test_from_domain_preserves_fields(self) -> None:
        spec = CountrySpec(
            iso3="NGA",
            iso2="NG",
            name="Nigeria",
            region="Sub-Saharan Africa",
            income_group="Lower middle income",
            notes="Phase 1 pilot",
        )
        row = CountryRow.from_domain(spec, created_at=_NOW, updated_at=_NOW)

        assert row.iso3 == "NGA"
        assert row.iso2 == "NG"
        assert row.name == "Nigeria"
        assert row.region == "Sub-Saharan Africa"
        assert row.income_group == "Lower middle income"
        assert row.enabled is True
        assert row.notes == "Phase 1 pilot"
        assert row.created_at == _NOW
        assert row.updated_at == _NOW

    def test_roundtrip(self) -> None:
        spec = CountrySpec(
            iso3="TUR",
            iso2="TR",
            name="Turkey",
            region="Europe & Central Asia",
        )
        row = CountryRow.from_domain(spec, created_at=_NOW, updated_at=_NOW)
        roundtripped = row.to_domain()

        assert roundtripped == spec

    def test_iso_codes_uppercased(self) -> None:
        spec = CountrySpec(iso3="bra", iso2="br", name="Brazil")
        assert spec.iso3 == "BRA"
        assert spec.iso2 == "BR"

    def test_optional_fields_default_none(self) -> None:
        spec = CountrySpec(iso3="POL", iso2="PL", name="Poland")
        assert spec.region is None
        assert spec.income_group is None
        assert spec.notes is None
        assert spec.enabled is True


class TestSourceIndicatorRow:
    def test_from_domain_preserves_fields(self) -> None:
        spec = SourceIndicatorSpec(
            source_id="fred",
            source_native_code="FPCPITOTLZGNGA",
            indicator_code="CPI_YOY",
            frequency="annual",
            countries_iso3=frozenset({"NGA"}),
            name="Nigeria CPI",
            unit="percent",
            notes="test note",
        )
        row = SourceIndicatorRow.from_domain(spec, created_at=_NOW, updated_at=_NOW)

        assert row.source_id == "fred"
        assert row.source_native_code == "FPCPITOTLZGNGA"
        assert row.indicator_code == "CPI_YOY"
        assert row.frequency == "annual"
        assert row.countries_iso3 == ["NGA"]
        assert row.name == "Nigeria CPI"
        assert row.unit == "percent"
        assert row.enabled is True
        assert row.notes == "test note"
        assert row.created_at == _NOW
        assert row.updated_at == _NOW

    def test_roundtrip(self) -> None:
        spec = SourceIndicatorSpec(
            source_id="worldbank",
            source_native_code="NY.GDP.MKTP.KD.ZG",
            indicator_code="GDP_GROWTH",
            frequency="annual",
            countries_iso3=frozenset({"NGA", "TUR", "ZAF"}),
        )
        row = SourceIndicatorRow.from_domain(spec, created_at=_NOW, updated_at=_NOW)
        roundtripped = row.to_domain()

        assert roundtripped.source_id == spec.source_id
        assert roundtripped.source_native_code == spec.source_native_code
        assert roundtripped.indicator_code == spec.indicator_code
        assert roundtripped.frequency == spec.frequency
        assert roundtripped.countries_iso3 == spec.countries_iso3
        assert roundtripped.enabled == spec.enabled

    def test_countries_iso3_sorted_in_row(self) -> None:
        """The ORM row stores countries as a sorted list, not a set."""
        spec = SourceIndicatorSpec(
            source_id="fred",
            source_native_code="TEST",
            indicator_code="TEST",
            frequency="annual",
            countries_iso3=frozenset({"ZAF", "BRA", "NGA"}),
        )
        row = SourceIndicatorRow.from_domain(spec, created_at=_NOW, updated_at=_NOW)
        assert row.countries_iso3 == ["BRA", "NGA", "ZAF"]

    def test_to_manifest_spec(self) -> None:
        """SourceIndicatorSpec can be converted to the lighter IndicatorSpec."""
        spec = SourceIndicatorSpec(
            source_id="fred",
            source_native_code="FPCPITOTLZGNGA",
            indicator_code="CPI_YOY",
            frequency="annual",
            countries_iso3=frozenset({"NGA"}),
            name="Nigeria CPI",
            unit="percent",
        )
        manifest_spec = spec.to_manifest_spec()

        assert manifest_spec.indicator_code == "CPI_YOY"
        assert manifest_spec.source_native_code == "FPCPITOTLZGNGA"
        assert manifest_spec.frequency == "annual"
        assert manifest_spec.countries_iso3 == frozenset({"NGA"})
        assert manifest_spec.name == "Nigeria CPI"
        assert manifest_spec.unit == "percent"
