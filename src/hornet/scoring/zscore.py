"""Z-score computation — ported verbatim from v1 scorer.py lines 350-440.

Two methods supported:

``full`` (legacy)
    Mean and std over the entire series. Every historical observation
    contributes equally.

``ewm`` (default)
    Exponentially-weighted mean and std with a per-frequency halflife
    (in observations). Recent observations dominate; older ones fade
    smoothly. No abrupt cutoff.

These functions are pure: no DB, no state, no pandas in the public
API. Internally they use pandas for EWM computation (the canonical
implementation that v1 uses — reimplementing in raw numpy would risk
subtle numerical differences).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def compute_zscore(
    values: Sequence[float],
    *,
    method: str = "ewm",
    halflife: int = 12,
    min_observations: int = 12,
) -> float | None:
    """Compute the z-score of the most recent value in a series.

    Ported from v1 ``Scorer._zscore()`` (scorer.py lines 350-439).

    Parameters
    ----------
    values:
        Time-ordered numeric values. Only position matters for EWM.
    method:
        ``"ewm"`` (recency-weighted) or ``"full"`` (whole-history).
    halflife:
        EWM halflife in observations. Ignored when method is ``"full"``.
    min_observations:
        Minimum length of ``values`` after dropping NaN. Below this
        the standard deviation is unreliable and None is returned.

    Returns
    -------
    float or None
        Z-score of the latest observation, or None if data is
        insufficient or std is undefined.
    """
    series = pd.Series(values, dtype=np.float64)
    clean = series.dropna()

    if len(clean) < min_observations:
        return None

    latest = float(clean.iloc[-1])

    # --- Legacy full-window path ---
    if method == "full":
        mean = float(clean.mean())
        std = float(clean.std())
        if std == 0:
            return 0.0
        return (latest - mean) / std

    # --- EWM path ---
    # adjust=False matches the recursive form: today = (1-alpha)*today
    # + alpha*yesterday, which is what we want for a "current state"
    # estimator. adjust=True applies bias correction across the whole
    # series, which inflates the std for short series.
    ewm = clean.ewm(halflife=halflife, adjust=False)
    mean = float(ewm.mean().iloc[-1])
    std_series = ewm.std()
    std_val = std_series.iloc[-1]

    if pd.isna(std_val) or std_val == 0:
        return 0.0

    return (latest - mean) / float(std_val)


def compute_momentum_zscore(
    prices: Sequence[float],
    *,
    window: int = 30,
    method: str = "ewm",
    halflife: int = 252,
    min_observations: int = 12,
) -> float | None:
    """Compute z-score of recent price momentum.

    Ported from v1 ``Scorer._momentum_zscore()`` (scorer.py lines 683-708).

    Calculates rolling ``window``-period returns, then takes the
    z-score of the latest return vs the historical distribution of
    returns. A large negative z-score means the recent move is
    unusually bad compared to history.

    Parameters
    ----------
    prices:
        Time-ordered price series (e.g. daily close prices).
    window:
        Number of periods for the rolling return calculation.
    method:
        Z-score method (``"ewm"`` or ``"full"``).
    halflife:
        EWM halflife for the z-score computation over the return
        distribution. Default 252 (daily frequency, ~1 year).
    min_observations:
        Minimum observations for z-score computation.

    Returns
    -------
    float or None
        Z-score of the latest rolling return, or None if
        insufficient data.
    """
    series = pd.Series(prices, dtype=np.float64)
    clean = series.dropna()

    if len(clean) < window + min_observations:
        return None

    # Percentage change over the rolling window
    returns = clean.pct_change(periods=window).dropna()

    if len(returns) < min_observations:
        return None

    return compute_zscore(
        returns.to_list(),
        method=method,
        halflife=halflife,
        min_observations=min_observations,
    )
