"""Alerts package -- tier evaluation, dispatch, and digest composition.

The alert layer sits downstream of scoring. It takes ScoreResults,
evaluates them against configurable thresholds and escalation modifiers,
routes them into tier buckets, and composes a structured digest.

Public API:
    AlertConfig        -- thresholds and modifier parameters
    assign_tier        -- pure function: ScoreResult + history -> TierAssignment
    dispatch           -- route TierAssignments into buckets
    compose_digest     -- build structured Digest from dispatch + quality + scores
    render_digest_text -- format Digest as human-readable text
"""

from ridge.alerts.config import AlertConfig
from ridge.alerts.digest import compose_digest, render_digest_text
from ridge.alerts.dispatcher import dispatch
from ridge.alerts.tier import assign_tier

__all__ = [
    "AlertConfig",
    "assign_tier",
    "compose_digest",
    "dispatch",
    "render_digest_text",
]
