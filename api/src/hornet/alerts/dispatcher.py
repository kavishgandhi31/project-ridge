"""Dispatcher -- route TierAssignments into tier buckets.

The dispatcher is the decision layer between tier evaluation and
output. It groups assignments by effective tier, enforces the daily
escalation limit (cost control for Claude API), and sorts each
bucket by severity (highest |composite| first).

This is a pure function -- no I/O, no state. The escalation limit
is enforced per-call (one call per pipeline run).

Usage:
    from hornet.alerts.dispatcher import dispatch

    result = dispatch(assignments, config)
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from hornet.alerts.config import AlertConfig
from hornet.domain.alerting import AlertTier, DispatchResult, TierAssignment

logger = structlog.get_logger(__name__)


def dispatch(
    assignments: Sequence[TierAssignment],
    config: AlertConfig,
) -> DispatchResult:
    """Route tier assignments into buckets and enforce escalation limit.

    Parameters
    ----------
    assignments:
        TierAssignments from the tier evaluator, one per country.
    config:
        Alert config with ``max_daily_escalations``.

    Returns
    -------
    DispatchResult
        Assignments grouped by effective tier, sorted by |composite|
        descending within each group.
    """
    escalate: list[TierAssignment] = []
    alert: list[TierAssignment] = []
    watch: list[TierAssignment] = []
    no_signal: list[TierAssignment] = []

    escalation_count = 0

    for assignment in assignments:
        tier = assignment.effective_tier

        if tier == AlertTier.ESCALATE:
            if escalation_count < config.max_daily_escalations:
                escalate.append(assignment)
                escalation_count += 1
            else:
                # Over the daily limit -- downgrade to ALERT so it
                # still appears in the digest, just without a Claude
                # API call. Log the downgrade for audit.
                logger.warning(
                    "dispatch.escalation_limit_reached",
                    country=assignment.country_iso3,
                    limit=config.max_daily_escalations,
                )
                alert.append(assignment)

        elif tier == AlertTier.ALERT:
            alert.append(assignment)

        elif tier == AlertTier.WATCH:
            watch.append(assignment)

        else:
            no_signal.append(assignment)

    # Sort each bucket by severity (highest |composite| first).
    def _sort_key(a: TierAssignment) -> float:
        return abs(a.composite) if a.composite is not None else 0.0

    escalate.sort(key=_sort_key, reverse=True)
    alert.sort(key=_sort_key, reverse=True)
    watch.sort(key=_sort_key, reverse=True)

    logger.info(
        "dispatch.complete",
        n_escalate=len(escalate),
        n_alert=len(alert),
        n_watch=len(watch),
        n_no_signal=len(no_signal),
    )

    return DispatchResult(
        escalate=tuple(escalate),
        alert=tuple(alert),
        watch=tuple(watch),
        no_signal=tuple(no_signal),
    )
