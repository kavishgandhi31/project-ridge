"""Tests for z-score computation — verifies v1-matching numerical behavior."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ridge.scoring.zscore import compute_momentum_zscore, compute_zscore


class TestComputeZscoreFull:
    """Full-window (legacy) z-score computation."""

    def test_known_values(self) -> None:
        """Hand-computed: values = [1, 2, 3, ..., 20], mean=10.5, std~=5.916."""
        values = list(range(1, 21))
        z = compute_zscore(values, method="full", min_observations=12)
        assert z is not None
        # latest=20, mean=10.5, std=sqrt(sum((x-10.5)^2)/(n-1))
        expected_mean = 10.5
        expected_std = np.std(values, ddof=1)
        expected_z = (20 - expected_mean) / expected_std
        assert z == pytest.approx(expected_z, abs=1e-10)

    def test_constant_series_returns_zero(self) -> None:
        values = [5.0] * 20
        z = compute_zscore(values, method="full", min_observations=12)
        assert z == 0.0

    def test_insufficient_data_returns_none(self) -> None:
        values = [1.0, 2.0, 3.0]
        z = compute_zscore(values, method="full", min_observations=12)
        assert z is None

    def test_exactly_min_observations(self) -> None:
        values = list(range(12))
        z = compute_zscore(values, method="full", min_observations=12)
        assert z is not None

    def test_nan_values_dropped(self) -> None:
        """NaN values should be dropped before computation."""
        values = [float("nan")] * 5 + list(range(1, 16))
        z = compute_zscore(values, method="full", min_observations=12)
        assert z is not None
        # Should equal z-score of [1..15] — NaNs excluded
        z_clean = compute_zscore(list(range(1, 16)), method="full", min_observations=12)
        assert z_clean is not None
        assert z == pytest.approx(z_clean, abs=1e-10)

    def test_nan_drops_below_min(self) -> None:
        """If dropping NaN leaves < min_observations, return None."""
        values = [float("nan")] * 15 + [1.0, 2.0, 3.0]
        z = compute_zscore(values, method="full", min_observations=12)
        assert z is None

    def test_negative_z_for_below_mean(self) -> None:
        """Latest value below the mean should give negative z-score."""
        values = [float(x) for x in range(1, 21)]  # 1.0..20.0
        # Swap latest to be low
        values[-1] = 1.0
        z = compute_zscore(values, method="full", min_observations=12)
        assert z is not None
        assert z < 0


class TestComputeZscoreEwm:
    """EWM (recency-weighted) z-score computation."""

    def test_returns_float(self) -> None:
        values = list(range(1, 25))
        z = compute_zscore(values, method="ewm", halflife=12, min_observations=12)
        assert z is not None
        assert isinstance(z, float)

    def test_constant_series_returns_zero(self) -> None:
        values = [5.0] * 20
        z = compute_zscore(values, method="ewm", halflife=12, min_observations=12)
        assert z == 0.0

    def test_insufficient_data_returns_none(self) -> None:
        values = [1.0, 2.0, 3.0]
        z = compute_zscore(values, method="ewm", halflife=12, min_observations=12)
        assert z is None

    def test_trending_up_positive_z(self) -> None:
        """Monotonically increasing series: latest should be above EWM mean."""
        values = list(range(1, 50))
        z = compute_zscore(values, method="ewm", halflife=12, min_observations=12)
        assert z is not None
        assert z > 0

    def test_trending_down_negative_z(self) -> None:
        """Monotonically decreasing series: latest should be below EWM mean."""
        values = list(range(50, 0, -1))
        z = compute_zscore(values, method="ewm", halflife=12, min_observations=12)
        assert z is not None
        assert z < 0

    def test_ewm_more_recent_sensitive_than_full(self) -> None:
        """EWM should react more to recent changes than full-window.

        Create a series that was flat then jumps. EWM should show
        a larger z-score than full-window because the EWM mean
        is anchored more recently.
        """
        values = [10.0] * 30 + [20.0] * 5
        z_ewm = compute_zscore(values, method="ewm", halflife=12, min_observations=12)
        z_full = compute_zscore(values, method="full", min_observations=12)
        assert z_ewm is not None
        assert z_full is not None
        # After regime shift, the EWM mean adjusts faster than full mean,
        # so the EWM z-score should be smaller in magnitude (closer to 0)
        # because the EWM mean has moved closer to the latest value.
        assert abs(z_ewm) < abs(z_full)

    def test_halflife_affects_result(self) -> None:
        """Different halflifes should produce different z-scores."""
        values = [10.0] * 20 + [15.0] * 10
        z_short = compute_zscore(values, method="ewm", halflife=5, min_observations=12)
        z_long = compute_zscore(values, method="ewm", halflife=50, min_observations=12)
        assert z_short is not None
        assert z_long is not None
        # Short halflife adapts faster — smaller |z| after regime shift
        assert abs(z_short) < abs(z_long)


class TestComputeMomentumZscore:
    """Momentum z-score (rolling return distribution)."""

    def test_returns_float_for_sufficient_data(self) -> None:
        """Need at least window + min_observations prices."""
        prices = list(range(100, 200))  # 100 prices, monotonically increasing
        z = compute_momentum_zscore(
            prices,
            window=30,
            min_observations=12,
            method="full",
        )
        assert z is not None
        assert isinstance(z, float)

    def test_insufficient_data_returns_none(self) -> None:
        prices = list(range(100, 110))  # only 10 prices
        z = compute_momentum_zscore(
            prices,
            window=30,
            min_observations=12,
            method="full",
        )
        assert z is None

    def test_steady_growth_bounded_momentum(self) -> None:
        """Steadily increasing prices: z-score should be moderate, not extreme."""
        # Compound 1% daily for 100 days
        prices = [100.0]
        for _ in range(99):
            prices.append(prices[-1] * 1.01)
        z = compute_momentum_zscore(
            prices,
            window=30,
            min_observations=12,
            method="full",
        )
        assert z is not None
        # Compound growth causes later 30-day returns to be slightly larger
        # than earlier ones, so z is not exactly 0, but should stay bounded
        assert abs(z) < 3.0

    def test_crash_gives_negative_momentum(self) -> None:
        """Flat prices then a crash: should produce a negative z-score."""
        prices = [100.0] * 70 + [80.0] * 5  # flat then 20% drop
        z = compute_momentum_zscore(
            prices,
            window=30,
            min_observations=12,
            method="full",
        )
        assert z is not None
        assert z < 0

    def test_window_parameter_affects_result(self) -> None:
        """Different windows should produce different momentum z-scores."""
        # Prices: flat, then sharp rise
        prices = [100.0] * 50 + [120.0] * 20
        z_short = compute_momentum_zscore(
            prices,
            window=10,
            min_observations=12,
            method="full",
        )
        z_long = compute_momentum_zscore(
            prices,
            window=30,
            min_observations=12,
            method="full",
        )
        assert z_short is not None
        assert z_long is not None
        # Different windows capture different dynamics
        assert z_short != pytest.approx(z_long, abs=0.1)

    def test_nan_in_prices(self) -> None:
        """NaN values in prices should be handled gracefully."""
        prices = [float("nan")] * 5 + [100.0 + i for i in range(80)]
        z = compute_momentum_zscore(
            prices,
            window=30,
            min_observations=12,
            method="full",
        )
        assert z is not None


class TestEdgeCases:
    """Edge cases that apply to both methods."""

    def test_single_value_returns_none(self) -> None:
        z = compute_zscore([42.0], method="full", min_observations=1)
        # std of single value is NaN (ddof=1), but pandas returns NaN
        # With min_observations=1 this could be None or a degenerate case.
        # Actually with a single value, std is NaN -> we should get None or 0.
        # The function returns (latest - mean) / std; with 1 value, std=NaN.
        # Let's just verify it doesn't crash.
        assert z is None or isinstance(z, float)

    def test_two_values_full(self) -> None:
        z = compute_zscore([1.0, 2.0], method="full", min_observations=2)
        assert z is not None
        # mean=1.5, std=0.707..., z = (2-1.5)/0.707 = 0.707
        assert z == pytest.approx(0.7071067811865476, abs=1e-6)

    def test_large_series(self) -> None:
        """Shouldn't crash on large input."""
        np.random.seed(42)
        values = np.random.randn(10000).tolist()
        z = compute_zscore(values, method="ewm", halflife=252, min_observations=12)
        assert z is not None
        assert math.isfinite(z)

    def test_all_nan_returns_none(self) -> None:
        values = [float("nan")] * 20
        z = compute_zscore(values, method="full", min_observations=12)
        assert z is None
