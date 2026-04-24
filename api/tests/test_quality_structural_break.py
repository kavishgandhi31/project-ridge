"""Tests for Control #7: Structural break detection."""

from __future__ import annotations

import datetime

from ridge.domain.observation import Observation
from ridge.quality.config import QualityConfig
from ridge.quality.structural_break import detect_structural_breaks

_NOW = datetime.datetime(2026, 4, 11, tzinfo=datetime.UTC)
_TODAY = _NOW.date()
_RUN_ID = "test-run-1"


def _obs(value: float, days_ago: int) -> Observation:
    return Observation(
        country_iso3="NGA",
        indicator_code="CPI_YOY",
        source_id="worldbank",
        date=_TODAY - datetime.timedelta(days=days_ago),
        value=value,
        frequency="annual",
        vintage=_NOW,
        ingested_at=_NOW,
    )


class TestDetectStructuralBreaks:
    def test_no_break(self) -> None:
        """Stationary series with noise should not trigger."""
        # Alternating around 10.0 with small noise — both windows have same mean
        obs = [_obs(10.0 + (0.1 if i % 2 == 0 else -0.1), 30 - i) for i in range(30)]
        config = QualityConfig(break_window=12, break_sigma=2.0)
        issues = detect_structural_breaks(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_detects_break(self) -> None:
        """Clear regime shift should be detected."""
        # Prior window: values around 10 with noise
        prior = [_obs(10.0 + (0.1 if i % 2 == 0 else -0.1), 30 - i) for i in range(12)]
        # Recent window: values around 20 with noise
        recent = [_obs(20.0 + (0.1 if i % 2 == 0 else -0.1), 18 - i) for i in range(12)]
        config = QualityConfig(break_window=12, break_sigma=2.0)
        issues = detect_structural_breaks(prior + recent, config, _RUN_ID, _NOW)
        assert len(issues) == 1
        assert issues[0].check_name == "structural_break"
        assert issues[0].detail["shift_sigma"] > 2.0

    def test_insufficient_data(self) -> None:
        """Need at least 2 * window observations."""
        obs = [_obs(10.0, 10 - i) for i in range(10)]
        config = QualityConfig(break_window=12, break_sigma=2.0)
        issues = detect_structural_breaks(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_constant_series(self) -> None:
        """Constant series: std=0, no break detected."""
        obs = [_obs(5.0, 30 - i) for i in range(30)]
        config = QualityConfig(break_window=12, break_sigma=2.0)
        issues = detect_structural_breaks(obs, config, _RUN_ID, _NOW)
        assert len(issues) == 0

    def test_custom_threshold(self) -> None:
        """Higher threshold should miss moderate shifts."""
        # Prior: noise around 10 with std ~0.5
        prior = [_obs(10.0 + (i % 3 - 1) * 0.5, 30 - i) for i in range(12)]
        # Recent: slight shift to ~10.5 — within 2 sigma of prior but flaggable
        recent = [_obs(10.5 + (i % 3 - 1) * 0.5, 18 - i) for i in range(12)]
        # With break_sigma=50.0, the small shift should not trigger
        config = QualityConfig(break_window=12, break_sigma=50.0)
        issues = detect_structural_breaks(prior + recent, config, _RUN_ID, _NOW)
        assert len(issues) == 0
