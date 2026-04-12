"""Digest composer and text renderer.

Two-stage design:
    1. ``compose_digest`` builds a structured ``Digest`` domain object
       from dispatch results, quality issues, and score results.
    2. ``render_digest_text`` formats a ``Digest`` as the human-readable
       text output that v1 analysts are used to.

The structured ``Digest`` is the API-facing shape. Phase 6 (LLM),
Phase 7 (Streamlit), and Phase 8 (Next.js) will add their own
renderers against the same type.

Usage:
    from hornet.alerts.digest import compose_digest, render_digest_text

    digest = compose_digest(dispatch_result, quality_issues, scores, run_id)
    text = render_digest_text(digest)
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from hornet.domain.alerting import (
    Digest,
    DigestSummary,
    DispatchResult,
    TierAssignment,
)
from hornet.domain.scoring import ScoreResult
from hornet.quality.issue import IssueSeverity, QualityIssue

# Dimension display labels (friendlier than config keys).
_DIMENSION_LABELS: dict[str, str] = {
    "growth_momentum": "Growth",
    "external_balance": "External",
    "monetary_stance": "Monetary",
    "risk_sentiment": "Risk",
}


# ------------------------------------------------------------------
# Composer
# ------------------------------------------------------------------


def compose_digest(
    dispatch_result: DispatchResult,
    quality_issues: Sequence[QualityIssue],
    score_results: Sequence[ScoreResult],
    run_id: str,
    *,
    generated_at: datetime.datetime | None = None,
) -> Digest:
    """Build a structured Digest from pipeline outputs.

    Parameters
    ----------
    dispatch_result:
        Tier assignments grouped by tier.
    quality_issues:
        Quality issues from the current run.
    score_results:
        All ScoreResults for dimension detail in tier sections.
    run_id:
        Pipeline run ID.
    generated_at:
        Timestamp for the digest. Defaults to now(UTC).

    Returns
    -------
    Digest
        Structured digest ready for rendering.
    """
    generated_at = generated_at or datetime.datetime.now(datetime.UTC)

    summary = DigestSummary(
        run_id=run_id,
        generated_at=generated_at,
        total_scored=dispatch_result.total,
        n_escalate=len(dispatch_result.escalate),
        n_alert=len(dispatch_result.alert),
        n_watch=len(dispatch_result.watch),
        n_no_signal=len(dispatch_result.no_signal),
    )

    scores_by_country = {sr.country_iso3: sr for sr in score_results}

    return Digest(
        summary=summary,
        dispatch=dispatch_result,
        quality_issues=tuple(quality_issues),
        scores_by_country=scores_by_country,
    )


# ------------------------------------------------------------------
# Text renderer
# ------------------------------------------------------------------


def _format_dimensions(score: ScoreResult) -> str:
    """Format dimension scores as a compact one-liner.

    Example: "Growth: -1.2 | External: +0.5 | Monetary: N/A | Risk: -2.1"
    """
    parts: list[str] = []
    for dim_key, label in _DIMENSION_LABELS.items():
        ds = score.dimensions.get(dim_key)
        if ds is not None and ds.value is not None:
            parts.append(f"{label}: {ds.value:+.1f}")
        else:
            parts.append(f"{label}: N/A")
    return " | ".join(parts)


def _format_assignment_detail(
    assignment: TierAssignment,
    score: ScoreResult | None,
) -> str:
    """Format one country as a multi-line detail block."""
    comp_str = f"{assignment.composite:+.2f}" if assignment.composite is not None else "N/A"
    cov_str = f"{assignment.coverage_fraction:.0%}"

    lines = [
        f"  {assignment.country_name} ({assignment.country_iso3})"
        f"  --  Composite: {comp_str}  |  Coverage: {cov_str}",
    ]

    if assignment.region:
        lines.append(f"    Region: {assignment.region}")

    if score is not None:
        lines.append(f"    {_format_dimensions(score)}")

    # Show modifier activity
    if assignment.streak_length > 0:
        lines.append(f"    Streak: {assignment.streak_length} consecutive ALERT+ runs")
    if assignment.velocity is not None:
        lines.append(f"    Velocity: {assignment.velocity:.2f} (|delta| from prior run)")
    if assignment.modifiers_applied:
        lines.append(f"    Modifiers: {', '.join(assignment.modifiers_applied)}")

    # Flag low coverage
    if assignment.coverage_fraction < 0.5:
        lines.append("    ** LOW DATA COVERAGE -- interpret with caution **")

    return "\n".join(lines)


def _format_assignment_brief(assignment: TierAssignment) -> str:
    """One-line format for WATCH tier (less detail needed)."""
    comp_str = f"{assignment.composite:+.2f}" if assignment.composite is not None else "N/A"
    return f"  {assignment.country_name} ({assignment.country_iso3}): {comp_str}"


def _render_header(summary: DigestSummary) -> str:
    """Build the digest header with timestamp and summary counts."""
    ts = summary.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "=" * 70,
        "  HORNET DAILY DIGEST",
        f"  Generated: {ts}",
        f"  Run: {summary.run_id}",
        "=" * 70,
        "",
        f"  Countries scored:  {summary.total_scored}",
        f"  ESCALATE:          {summary.n_escalate}",
        f"  ALERT:             {summary.n_alert}",
        f"  WATCH:             {summary.n_watch}",
        f"  No signal:         {summary.n_no_signal}",
        "",
    ]
    return "\n".join(lines)


def _render_tier_section(
    title: str,
    assignments: Sequence[TierAssignment],
    scores_by_country: dict[str, ScoreResult],
    *,
    detailed: bool = True,
) -> str:
    """Build a digest section for a given tier."""
    if not assignments:
        return f"--- {title} ---\n  (none)\n"

    lines = [f"--- {title} ({len(assignments)}) ---"]
    for assignment in assignments:
        if detailed:
            score = scores_by_country.get(assignment.country_iso3)
            lines.append(_format_assignment_detail(assignment, score))
        else:
            lines.append(_format_assignment_brief(assignment))
        lines.append("")
    return "\n".join(lines)


def _render_quality_section(issues: Sequence[QualityIssue]) -> str:
    """Build a DATA QUALITY section from quality issues."""
    if not issues:
        return ""

    critical = [i for i in issues if i.severity == IssueSeverity.CRITICAL]
    warnings = [i for i in issues if i.severity == IssueSeverity.WARNING]

    lines = ["--- DATA QUALITY ---"]

    if critical:
        lines.append(f"  {len(critical)} CRITICAL issues:")
        for issue in critical:
            scope = issue.country_iso3 or "GLOBAL"
            lines.append(f"    - [{issue.check_name}] {scope}: {issue.message}")
        lines.append("")

    if warnings:
        lines.append(f"  {len(warnings)} warnings:")
        for issue in warnings[:20]:  # Cap at 20 to keep digest scannable
            scope = issue.country_iso3 or "GLOBAL"
            lines.append(f"    - [{issue.check_name}] {scope}: {issue.message}")
        if len(warnings) > 20:
            lines.append(f"    ... and {len(warnings) - 20} more")
        lines.append("")

    return "\n".join(lines)


def _render_low_coverage_section(
    dispatch_result: DispatchResult,
) -> str:
    """Flag countries with <50% dimension coverage across all tiers."""
    all_assignments = (
        dispatch_result.escalate
        + dispatch_result.alert
        + dispatch_result.watch
        + dispatch_result.no_signal
    )
    low_cov = [a for a in all_assignments if a.coverage_fraction < 0.5]

    if not low_cov:
        return ""

    lines = [
        "--- LOW COVERAGE WARNINGS ---",
        f"  {len(low_cov)} countries have <50% dimension coverage:",
    ]
    for a in low_cov:
        lines.append(
            f"    - {a.country_name} ({a.country_iso3}): " f"{a.coverage_fraction:.0%} coverage"
        )
    lines.append("")
    return "\n".join(lines)


def render_digest_text(digest: Digest) -> str:
    """Format a structured Digest as human-readable text.

    This is the Phase 5 consumer of the Digest type. Future phases
    will add HTML, JSON, and LLM-prompt renderers.

    Parameters
    ----------
    digest:
        Structured Digest from ``compose_digest``.

    Returns
    -------
    str
        Multi-line text suitable for file output or console display.
    """
    sections: list[str] = [
        _render_header(digest.summary),
    ]

    # Data quality context first (before tier alerts).
    quality_text = _render_quality_section(digest.quality_issues)
    if quality_text:
        sections.append(quality_text)

    # Tier alert sections.
    sections.append(
        _render_tier_section(
            "ESCALATE -- REQUIRES DEEP ANALYSIS",
            digest.dispatch.escalate,
            digest.scores_by_country,
        )
    )
    sections.append(
        _render_tier_section(
            "ALERT -- REQUIRES HUMAN REVIEW",
            digest.dispatch.alert,
            digest.scores_by_country,
        )
    )
    sections.append(
        _render_tier_section(
            "WATCH -- LOGGED",
            digest.dispatch.watch,
            digest.scores_by_country,
            detailed=False,
        )
    )

    # Low coverage warnings.
    low_cov_text = _render_low_coverage_section(digest.dispatch)
    if low_cov_text:
        sections.append(low_cov_text)

    return "\n".join(sections)
