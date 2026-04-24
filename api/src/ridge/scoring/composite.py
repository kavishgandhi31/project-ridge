"""Composite score computation — ported verbatim from v1 scorer.py lines 803-886.

Two strategies:

``zero_pad`` (legacy)
    Missing dimensions contribute 0.0, divided by full weight total.
    Dilutes genuine stress signals when coverage is thin.

``renormalize`` (default)
    Average across only present dimensions, multiplied by a coverage-
    confidence factor. Countries below min_dimensions return None.
"""

from __future__ import annotations

import math

import structlog

from ridge.domain.scoring import DimensionScore, ScoringConfig

logger = structlog.get_logger(__name__)


def compute_composite(
    dimension_scores: dict[str, DimensionScore],
    config: ScoringConfig,
) -> float | None:
    """Compute a single weighted composite score from dimension scores.

    Ported from v1 ``Scorer.composite_score()`` (scorer.py lines 803-886).

    Parameters
    ----------
    dimension_scores:
        Maps dimension name -> DimensionScore. Values with
        ``value=None`` are treated as missing.
    config:
        Scoring configuration with weights and composite policy.

    Returns
    -------
    float or None
        Weighted composite, or None if coverage is insufficient.
    """
    present = {dim: ds for dim, ds in dimension_scores.items() if ds.value is not None}

    if not present:
        return None

    weights = config.dimension_weights

    # Legacy zero-pad path
    if config.composite_strategy == "zero_pad":
        weighted_sum = 0.0
        total_weight = sum(weights.values())
        for dim, ds in dimension_scores.items():
            weight = weights.get(dim, 0.0)
            weighted_sum += (ds.value or 0.0) * weight
        composite = weighted_sum / total_weight
        return round(_clamp(composite, config), 2)

    # Renormalize strategy
    total_dims = len(weights) or 1
    n_present = len(present)

    if n_present < config.min_dimensions_for_composite:
        return None

    present_weight = sum(weights.get(d, 0.0) for d in present)
    if present_weight == 0:
        return None

    weighted_sum = 0.0
    for dim, ds in present.items():
        # ds.value is guaranteed non-None by the present filter above
        val = ds.value
        assert val is not None  # narrowing for mypy; enforced by `present` filter
        weighted_sum += val * weights.get(dim, 0.0)
    renormalised = weighted_sum / present_weight

    coverage_fraction = n_present / total_dims
    if config.coverage_confidence == "none":
        confidence = 1.0
    elif config.coverage_confidence == "linear":
        confidence = coverage_fraction
    elif config.coverage_confidence == "sqrt":
        confidence = math.sqrt(coverage_fraction)
    else:
        logger.debug(
            "composite.unknown_coverage_confidence",
            value=config.coverage_confidence,
        )
        confidence = 1.0

    composite = renormalised * confidence
    return round(_clamp(composite, config), 2)


def _clamp(value: float, config: ScoringConfig) -> float:
    """Clamp a score to the configured scale bounds."""
    return max(config.scale_min, min(config.scale_max, value))
