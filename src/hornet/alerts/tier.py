"""Tier evaluator -- pure functions for alert tier assignment.

Ports v1's ``Scorecard.assign_tier()`` and its three escalation
modifiers as standalone pure functions. No class, no state, no I/O.

Modifier application order (load-bearing, ported from v1):
    1. Raw tier from abs(composite) vs thresholds
    2. Coverage gate -- cap ESCALATE at ALERT if coverage < min
    3. Streak requirement -- cap ESCALATE at ALERT if insufficient
       consecutive prior ALERT+ runs
    4. Velocity boost -- promote tier one level if composite moved
       fast AND direction is deteriorating (negative composite)
       Subject to re-application of coverage gate post-boost.

Usage:
    from hornet.alerts.tier import assign_tier

    assignment = assign_tier(
        score_result=score,
        config=alert_config,
        country_name="Turkey",
        region="Europe & Central Asia",
        prior_records=prior_alert_records,
    )
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any

from hornet.alerts.config import AlertConfig
from hornet.domain.alerting import AlertTier, TierAssignment
from hornet.domain.scoring import ScoreResult


def _raw_tier(composite: float, config: AlertConfig) -> AlertTier | None:
    """Assign tier from absolute composite value vs thresholds.

    Evaluates from highest to lowest so the first match wins.
    Returns None if below all thresholds.
    """
    abs_comp = abs(composite)
    if abs_comp >= config.escalate_threshold:
        return AlertTier.ESCALATE
    if abs_comp >= config.alert_threshold:
        return AlertTier.ALERT
    if abs_comp >= config.watch_threshold:
        return AlertTier.WATCH
    return None


def count_alert_streak(prior_records: Sequence[dict[str, Any]]) -> int:
    """Count consecutive prior runs at ALERT or ESCALATE tier.

    ``prior_records`` must be ordered most-recent-first. Counting
    stops at the first entry that is not ALERT or ESCALATE.

    This is a verbatim port of v1's ``Scorecard._count_alert_streak``.
    """
    streak = 0
    for record in prior_records:
        tier = record.get("effective_tier")
        if tier in (AlertTier.ALERT, AlertTier.ESCALATE, "ALERT", "ESCALATE"):
            streak += 1
        else:
            break
    return streak


def compute_velocity(
    current_composite: float,
    prior_records: Sequence[dict[str, Any]],
) -> float | None:
    """Compute absolute composite change from the most recent prior run.

    Skips prior records with None composite (same as v1). Returns
    None if no usable prior composite exists.
    """
    for record in prior_records:
        prior_composite = record.get("composite")
        if prior_composite is not None:
            return float(abs(current_composite - prior_composite))
    return None


def _promote_tier(tier: AlertTier | None) -> AlertTier:
    """Bump tier one level up, capped at ESCALATE.

    None -> WATCH -> ALERT -> ESCALATE -> ESCALATE
    """
    if tier is None:
        return AlertTier.WATCH
    if tier == AlertTier.WATCH:
        return AlertTier.ALERT
    if tier == AlertTier.ALERT:
        return AlertTier.ESCALATE
    return AlertTier.ESCALATE


def assign_tier(
    score_result: ScoreResult,
    config: AlertConfig,
    *,
    country_name: str,
    region: str | None = None,
    prior_records: Sequence[dict[str, Any]] | None = None,
    evaluated_at: datetime.datetime | None = None,
) -> TierAssignment:
    """Evaluate a ScoreResult against alert rules and return a TierAssignment.

    This is the main entry point. It applies raw thresholds then the
    three modifiers in v1's exact order: coverage gate, streak, velocity.

    Parameters
    ----------
    score_result:
        The scoring output to evaluate.
    config:
        Alert thresholds and modifier parameters.
    country_name:
        Human-readable name for digest rendering.
    region:
        World Bank region for digest grouping.
    prior_records:
        Previous alert records for this country, most-recent-first.
        Each dict must have at least ``effective_tier`` and ``composite``
        keys. Pass None or empty list for first-ever run (falls back to
        raw thresholds with no modifiers).
    evaluated_at:
        Timestamp for the assignment. Defaults to now(UTC).

    Returns
    -------
    TierAssignment
        Complete evaluation result with raw tier, effective tier,
        streak, velocity, and which modifiers fired.
    """
    evaluated_at = evaluated_at or datetime.datetime.now(datetime.UTC)
    history = prior_records or []
    modifiers: list[str] = []

    composite = score_result.composite
    coverage = score_result.coverage_fraction

    # --- Step 1: Raw tier from thresholds ---
    if composite is None:
        return TierAssignment(
            country_iso3=score_result.country_iso3,
            country_name=country_name,
            region=region,
            run_id=score_result.run_id,
            evaluated_at=evaluated_at,
            composite=None,
            coverage_fraction=coverage,
            raw_tier=None,
            effective_tier=None,
            streak_length=0,
            velocity=None,
            modifiers_applied=(),
        )

    raw = _raw_tier(composite, config)
    effective = raw

    # --- Step 2: Coverage gate (pre-modifier) ---
    if effective == AlertTier.ESCALATE and coverage < config.min_coverage_for_escalate:
        effective = AlertTier.ALERT
        modifiers.append("coverage_gate")

    # --- Step 3: Streak requirement ---
    streak = count_alert_streak(history) if history else 0

    if (
        effective == AlertTier.ESCALATE
        and config.streak_required > 0
        and streak < config.streak_required
    ):
        effective = AlertTier.ALERT
        modifiers.append("streak_hold")

    # --- Step 4: Velocity boost ---
    # Only applies when:
    #   - effective tier is NOT already ESCALATE
    #   - composite is negative (deteriorating, not improving)
    #   - there is prior history to compute velocity from
    #   - raw tier was NOT ESCALATE that got demoted (those already
    #     failed a gate -- don't re-promote via velocity)
    velocity: float | None = None

    if history:
        velocity = compute_velocity(composite, history)

    velocity_boost_applied = False
    if (
        velocity is not None
        and velocity > config.velocity_threshold
        and effective is not None
        and effective != AlertTier.ESCALATE
        and composite < 0  # Only for deteriorating
        and raw != AlertTier.ESCALATE  # Don't re-promote demoted ESCALATE
    ):
        effective = _promote_tier(effective)
        modifiers.append("velocity_boost")
        velocity_boost_applied = True

    # Re-apply coverage gate after velocity boost to ESCALATE
    if (
        velocity_boost_applied
        and effective == AlertTier.ESCALATE
        and coverage < config.min_coverage_for_escalate
    ):
        effective = AlertTier.ALERT
        modifiers.append("coverage_gate_post_velocity")

    return TierAssignment(
        country_iso3=score_result.country_iso3,
        country_name=country_name,
        region=region,
        run_id=score_result.run_id,
        evaluated_at=evaluated_at,
        composite=composite,
        coverage_fraction=coverage,
        raw_tier=raw,
        effective_tier=effective,
        streak_length=streak,
        velocity=velocity,
        modifiers_applied=tuple(modifiers),
    )
