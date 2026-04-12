"""Tests for Control #2: Series audit."""

from __future__ import annotations

import datetime

from hornet.domain.source import SourceIndicatorSpec
from hornet.quality.config import QualityConfig
from hornet.quality.series_audit import audit_series_coverage

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_RUN_ID = "test-run-1"


def _spec(indicator: str, source: str, countries: list[str]) -> SourceIndicatorSpec:
    return SourceIndicatorSpec(
        source_id=source,
        source_native_code=f"native_{indicator}",
        indicator_code=indicator,
        frequency="annual",
        countries_iso3=frozenset(countries),
        dimension="growth_momentum",
        concept="gdp",
    )


class TestAuditSeriesCoverage:
    def test_full_coverage(self) -> None:
        specs = [_spec("GDP_GROWTH", "worldbank", ["NGA", "TUR"])]
        counts = {
            ("NGA", "GDP_GROWTH", "worldbank"): 10,
            ("TUR", "GDP_GROWTH", "worldbank"): 8,
        }
        issues = audit_series_coverage(specs, counts, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_missing_series(self) -> None:
        specs = [_spec("GDP_GROWTH", "worldbank", ["NGA", "TUR"])]
        counts = {("NGA", "GDP_GROWTH", "worldbank"): 10}  # TUR missing
        issues = audit_series_coverage(specs, counts, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].country_iso3 == "TUR"
        assert "worldbank:GDP_GROWTH" in issues[0].detail["missing"]

    def test_non_scored_series_ignored(self) -> None:
        """Indicators without dimension are not audited."""
        spec = SourceIndicatorSpec(
            source_id="gdelt",
            source_native_code="headline",
            indicator_code="headline",
            frequency="daily",
            countries_iso3=frozenset({"NGA"}),
            dimension=None,  # not scored
        )
        counts: dict[tuple[str, str, str], int] = {}
        issues = audit_series_coverage([spec], counts, QualityConfig(), _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_threshold_filtering(self) -> None:
        specs = [
            _spec("GDP_GROWTH", "worldbank", ["NGA"]),
            _spec("CPI_YOY", "worldbank", ["NGA"]),
        ]
        counts = {("NGA", "GDP_GROWTH", "worldbank"): 10}  # CPI missing = 50% gap
        config = QualityConfig(series_audit_threshold=0.6)  # only flag > 60%
        issues = audit_series_coverage(specs, counts, config, _RUN_ID, _NOW)
        assert len(issues) == 0  # 50% gap is below 60% threshold
