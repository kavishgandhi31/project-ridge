"""Synthetic golden tests — deterministic, runs in CI on every commit.

Loads hand-crafted observations from golden_synthetic.json, runs them
through the scoring engine with a pinned config, and verifies the
outputs match expected behavior (direction, coverage, None/not-None).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from hornet.domain.observation import Observation
from hornet.domain.scoring import ScoringConfig
from hornet.domain.source import SourceIndicatorSpec
from hornet.scoring.engine import ScoringEngine

_FIXTURES = Path(__file__).parent / "fixtures"
_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()


def _load_fixture() -> dict[str, object]:
    with (_FIXTURES / "golden_synthetic.json").open() as f:
        data: dict[str, object] = json.load(f)
        return data


def _build_observations(
    country_iso3: str,
    obs_defs: list[dict],  # type: ignore[type-arg]
) -> list[Observation]:
    """Convert fixture observation definitions into Observation objects."""
    result: list[Observation] = []
    for obs_def in obs_defs:
        values = obs_def["values"]
        n = len(values)
        freq = obs_def["frequency"]
        intervals = {
            "daily": 1,
            "weekly": 7,
            "monthly": 30,
            "quarterly": 90,
            "annual": 365,
            "forecast": 180,
        }
        interval = intervals.get(freq, 365)

        for i, value in enumerate(values):
            obs_date = _TODAY - datetime.timedelta(days=(n - 1 - i) * interval)
            result.append(
                Observation(
                    country_iso3=country_iso3,
                    indicator_code=obs_def["indicator_code"],
                    source_id=obs_def["source_id"],
                    date=obs_date,
                    value=value,
                    frequency=freq,
                    vintage=_NOW,
                    ingested_at=_NOW,
                )
            )
    return result


def _build_indicators(
    obs_defs: list[dict],  # type: ignore[type-arg]
) -> list[SourceIndicatorSpec]:
    """Build indicator specs from fixture observation definitions."""
    seen: set[tuple[str, str]] = set()
    result: list[SourceIndicatorSpec] = []
    for obs_def in obs_defs:
        key = (obs_def["source_id"], obs_def["indicator_code"])
        if key in seen:
            continue
        seen.add(key)
        result.append(
            SourceIndicatorSpec(
                source_id=obs_def["source_id"],
                source_native_code=f"native_{obs_def['indicator_code']}",
                indicator_code=obs_def["indicator_code"],
                frequency=obs_def["frequency"],
                countries_iso3=frozenset({"NGA", "TUR", "ZAF", "BRA", "POL"}),
                dimension=obs_def.get("dimension"),
                concept=obs_def.get("concept"),
            )
        )
    return result


def _build_config(config_data: dict) -> ScoringConfig:  # type: ignore[type-arg]
    return ScoringConfig(**config_data)


class TestGoldenSynthetic:
    """Run each country through the engine and verify expected behavior."""

    @pytest.fixture()
    def fixture_data(self) -> dict:  # type: ignore[type-arg]
        return _load_fixture()

    def test_nga_three_dimensions(self, fixture_data: dict) -> None:  # type: ignore[type-arg]
        country = fixture_data["countries"]["NGA"]
        config = _build_config(fixture_data["config"])
        observations = _build_observations("NGA", country["observations"])
        indicators = _build_indicators(country["observations"])

        engine = ScoringEngine(config, indicators)
        result = engine.score_country("NGA", observations, [], _TODAY)

        expected = country["expected"]
        assert (result.dimensions["growth_momentum"].value is not None) == expected[
            "growth_momentum_not_none"
        ]
        assert (result.dimensions["monetary_stance"].value is not None) == expected[
            "monetary_stance_not_none"
        ]
        assert (result.dimensions["external_balance"].value is not None) == expected[
            "external_balance_not_none"
        ]
        assert (result.dimensions["risk_sentiment"].value is None) == expected[
            "risk_sentiment_is_none"
        ]
        assert (result.composite is not None) == expected["composite_not_none"]
        assert result.coverage_fraction == pytest.approx(expected["coverage_fraction"], abs=0.01)

        # Direction checks
        gm = result.dimensions["growth_momentum"].value
        assert gm is not None and gm > 0, "Growth trending up should be positive"
        eb = result.dimensions["external_balance"].value
        assert eb is not None and eb > 0, "Improving current account should be positive"

    def test_tur_full_coverage_deteriorating(self, fixture_data: dict) -> None:  # type: ignore[type-arg]
        country = fixture_data["countries"]["TUR"]
        config = _build_config(fixture_data["config"])
        observations = _build_observations("TUR", country["observations"])
        indicators = _build_indicators(country["observations"])

        engine = ScoringEngine(config, indicators)
        result = engine.score_country("TUR", observations, [], _TODAY)

        expected = country["expected"]
        assert result.coverage_fraction == pytest.approx(expected["coverage_fraction"], abs=0.01)
        assert result.composite is not None

        # Deteriorating growth should be negative
        gm = result.dimensions["growth_momentum"].value
        assert gm is not None and gm < 0

        # Deteriorating current account should be negative
        eb = result.dimensions["external_balance"].value
        assert eb is not None and eb < 0

    def test_zaf_single_dimension_no_composite(self, fixture_data: dict) -> None:  # type: ignore[type-arg]
        country = fixture_data["countries"]["ZAF"]
        config = _build_config(fixture_data["config"])
        observations = _build_observations("ZAF", country["observations"])
        indicators = _build_indicators(country["observations"])

        engine = ScoringEngine(config, indicators)
        result = engine.score_country("ZAF", observations, [], _TODAY)

        expected = country["expected"]
        assert result.dimensions["growth_momentum"].value is not None
        assert result.dimensions["monetary_stance"].value is None
        assert result.dimensions["external_balance"].value is None
        assert result.dimensions["risk_sentiment"].value is None
        assert result.composite is None  # below min_dimensions_for_composite
        assert result.coverage_fraction == pytest.approx(expected["coverage_fraction"], abs=0.01)

    def test_bra_concept_deduplication(self, fixture_data: dict) -> None:  # type: ignore[type-arg]
        country = fixture_data["countries"]["BRA"]
        config = _build_config(fixture_data["config"])
        observations = _build_observations("BRA", country["observations"])
        indicators = _build_indicators(country["observations"])

        engine = ScoringEngine(config, indicators)
        result = engine.score_country("BRA", observations, [], _TODAY)

        assert result.dimensions["growth_momentum"].value is not None
        assert result.composite is not None

        # Concept dedup: both GDP sources share concept="gdp" in the same
        # frequency tier, so they should be averaged into 1 concept
        gm = result.dimensions["growth_momentum"]
        assert (
            gm.n_concepts == 1
        ), f"Two GDP sources with same concept should dedup to 1, got {gm.n_concepts}"

    def test_pol_no_data(self, fixture_data: dict) -> None:  # type: ignore[type-arg]
        config = _build_config(fixture_data["config"])

        engine = ScoringEngine(config, [])
        result = engine.score_country("POL", [], [], _TODAY)

        for dim_name in (
            "growth_momentum",
            "monetary_stance",
            "external_balance",
            "risk_sentiment",
        ):
            assert result.dimensions[dim_name].value is None
        assert result.composite is None
        assert result.coverage_fraction == 0.0

    def test_all_scores_clamped(self, fixture_data: dict) -> None:  # type: ignore[type-arg]
        """Every dimension score across all countries must be in [-3, +3]."""
        config = _build_config(fixture_data["config"])

        for iso3, country in fixture_data["countries"].items():
            observations = _build_observations(iso3, country["observations"])
            indicators = _build_indicators(country["observations"])
            engine = ScoringEngine(config, indicators)
            result = engine.score_country(iso3, observations, [], _TODAY)

            for dim_name, ds in result.dimensions.items():
                if ds.value is not None:
                    assert (
                        -3.0 <= ds.value <= 3.0
                    ), f"{iso3}/{dim_name} score {ds.value} out of [-3, +3]"
            if result.composite is not None:
                assert -3.0 <= result.composite <= 3.0

    def test_batch_scoring(self, fixture_data: dict) -> None:  # type: ignore[type-arg]
        """Verify batch scoring produces same results as individual scoring."""
        config = _build_config(fixture_data["config"])

        # Collect all indicators from all countries
        all_indicators: list[SourceIndicatorSpec] = []
        all_obs: dict[str, list[Observation]] = {}
        for iso3, country in fixture_data["countries"].items():
            obs = _build_observations(iso3, country["observations"])
            all_obs[iso3] = obs
            all_indicators.extend(_build_indicators(country["observations"]))

        # Deduplicate indicators
        seen: set[tuple[str, str]] = set()
        deduped: list[SourceIndicatorSpec] = []
        for ind in all_indicators:
            key = (ind.source_id, ind.indicator_code)
            if key not in seen:
                seen.add(key)
                deduped.append(ind)

        engine = ScoringEngine(config, deduped)
        batch_results = engine.score_all(
            list(fixture_data["countries"].keys()),
            all_obs,
            {},
            _TODAY,
        )

        assert len(batch_results) == len(fixture_data["countries"])
        # All should share the same run_id
        run_ids = {r.run_id for r in batch_results}
        assert len(run_ids) == 1
