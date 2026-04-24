"""Grounded context builder -- deterministic retrieval with citation markers.

This is the core of the "grounded generation" pattern. Instead of
vector-search RAG, the context builder fetches observations from the
DB using the same queries the scoring engine uses, formats them with
numbered citation markers [1], [2], ..., and produces a GroundedContext
that the prompt template injects into the LLM prompt.

The LLM never retrieves data -- we hand it exactly the data it should
reference, with citation markers already attached. The output parser
then checks that every numeric claim in the LLM's response has a
corresponding marker.

Token budget management:
    The context builder receives a token budget from the router (derived
    from the target provider's max_context_tokens minus the system prompt
    and completion reserve). Observations are prioritized by recency and
    dimension weight. When the budget is exhausted, remaining indicators
    are truncated and recorded in ``indicators_truncated``.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Sequence

import structlog

from ridge.domain.event import EventRecord
from ridge.domain.llm import Citation, GroundedContext
from ridge.domain.observation import Observation
from ridge.domain.scoring import DimensionScore, ScoreResult

logger = structlog.get_logger(__name__)

# Rough estimate: one citation line is ~15-20 tokens.
# "  [1] CPI_YOY (NGA, 2026-03): 33.20% (source: worldbank)\n" ~ 18 tokens
_TOKENS_PER_CITATION_LINE = 20
# Header/section overhead per indicator group
_TOKENS_PER_SECTION_HEADER = 10
# Score summary section overhead
_TOKENS_SCORE_SUMMARY = 200
# Events section overhead per event
_TOKENS_PER_EVENT = 25


def _estimate_tokens(text: str) -> int:
    """Rough token estimate using the ~4 chars/token heuristic.

    This is intentionally conservative (overestimates). For accurate
    counts, the provider's token_counter capability should be used
    at the router level for final validation.
    """
    return len(text) // 3 + 1


def _format_value(value: float, indicator_code: str) -> str:
    """Format a numeric value for display in the context block.

    Uses indicator-appropriate formatting: percentages for rates,
    two decimal places for indices, etc. Pattern-based matching
    so new indicator codes don't require updating this function.
    """
    # Percentage-unit indicators (rates, ratios, spreads, yields)
    pct_indicators = {
        "CPI_YOY",
        "GDP_GROWTH",
        "CURRENT_ACCOUNT_GDP",
        "GOVT_DEBT_GDP",
        "UNEMPLOYMENT",
        "TRADE_OPENNESS",
        "CREDIT_GAP",
        "POLICY_RATE",
        "LENDING_RATE",
        "DGS10",
        "DGS2",
        "T10Y2Y",
    }
    # Pattern-based: UST_*, TIPS_*, BREAKEVEN_*, SPREAD_*, *_SPREAD
    pct_prefixes = ("UST_", "TIPS_", "BREAKEVEN_", "SPREAD_")
    pct_suffixes = ("_SPREAD",)

    if indicator_code in pct_indicators:
        return f"{value:.2f}%"
    if any(indicator_code.startswith(p) for p in pct_prefixes):
        return f"{value:.2f}%"
    if any(indicator_code.endswith(s) for s in pct_suffixes):
        return f"{value:.2f}%"
    if indicator_code.startswith("FX_"):
        return f"{value:.4f}"
    # USD-denominated prices (commodities, ETFs)
    if indicator_code in ("GOLD", "GOLD_FUTURES", "SILVER_FUTURES"):
        return f"${value:,.2f}"
    if "OIL" in indicator_code or "NATGAS" in indicator_code:
        return f"${value:.2f}"
    return f"{value:.2f}"


def _format_date(date: datetime.date) -> str:
    """Format a date for human-readable display.

    Uses natural language dates so the LLM echoes them naturally:
    daily/weekly -> "Apr 18, 2026", monthly -> "Mar 2026",
    quarterly -> "Q1 2026", annual -> "2026".
    """
    # If day is 1 it's likely a monthly/quarterly/annual bucket
    if date.day == 1 and date.month in (1, 4, 7, 10):
        # Could be quarterly or annual
        if date.month == 1:
            return str(date.year)
        return f"Q{(date.month - 1) // 3 + 1} {date.year}"
    if date.day == 1:
        return date.strftime("%b %Y")
    return date.strftime("%b %d, %Y")


def build_observation_context(
    observations: Sequence[Observation],
    *,
    token_budget: int,
    max_points_per_indicator: int = 3,
    dimension_priority: Sequence[str] | None = None,
) -> tuple[str, tuple[Citation, ...], tuple[str, ...], tuple[str, ...]]:
    """Build the citation-marked context block from observations.

    Groups observations by indicator_code, takes the N most recent
    per indicator, formats them with numbered citation markers, and
    respects the token budget.

    Parameters
    ----------
    observations:
        Latest-vintage observations for one country.
    token_budget:
        Maximum tokens for the observation section of the context.
    max_points_per_indicator:
        How many recent data points per indicator. More points let
        the LLM identify trends; fewer save tokens.
    dimension_priority:
        Optional ordering of dimensions for prioritization. Indicators
        belonging to higher-priority dimensions get included first.
        If None, indicators are ordered alphabetically.

    Returns
    -------
    tuple of (context_block, citations, indicators_included, indicators_truncated)
    """
    if not observations:
        return ("No observation data available for this country.", (), (), ())

    # Separate actuals from forecasts
    actuals: list[Observation] = []
    forecasts: list[Observation] = []
    for obs in observations:
        if obs.frequency == "forecast":
            forecasts.append(obs)
        else:
            actuals.append(obs)

    # Group by indicator_code, then take most recent N per indicator
    by_indicator: dict[str, list[Observation]] = defaultdict(list)
    for obs in actuals:
        by_indicator[obs.indicator_code].append(obs)

    by_indicator_forecast: dict[str, list[Observation]] = defaultdict(list)
    for obs in forecasts:
        by_indicator_forecast[obs.indicator_code].append(obs)

    # Sort each group by date descending, take most recent N
    for code in by_indicator:
        by_indicator[code].sort(key=lambda o: o.date, reverse=True)
        by_indicator[code] = by_indicator[code][:max_points_per_indicator]

    for code in by_indicator_forecast:
        by_indicator_forecast[code].sort(key=lambda o: o.date)
        by_indicator_forecast[code] = by_indicator_forecast[code][:max_points_per_indicator]

    # Order indicators: by dimension priority if given, else alphabetically
    indicator_codes = sorted(by_indicator.keys())
    forecast_codes = sorted(by_indicator_forecast.keys())

    lines: list[str] = []
    citations: list[Citation] = []
    included: list[str] = []
    truncated: list[str] = []
    ref_number = 1
    tokens_used = 0

    # Actuals first
    if actuals:
        lines.append("=== ACTUAL DATA ===")
        tokens_used += _TOKENS_PER_SECTION_HEADER

    for code in indicator_codes:
        obs_list = by_indicator[code]
        section_tokens = _TOKENS_PER_SECTION_HEADER + (_TOKENS_PER_CITATION_LINE * len(obs_list))

        if tokens_used + section_tokens > token_budget:
            truncated.append(code)
            continue

        included.append(code)
        for obs in obs_list:
            formatted_value = _format_value(obs.value, obs.indicator_code)
            display_label = (
                f"{obs.indicator_code} ({obs.country_iso3}, "
                f"{_format_date(obs.date)}): {formatted_value}"
            )
            line = f"  [{ref_number}] {display_label} (source: {obs.source_id})"
            lines.append(line)
            citations.append(
                Citation(
                    ref_number=ref_number,
                    country_iso3=obs.country_iso3,
                    indicator_code=obs.indicator_code,
                    source_id=obs.source_id,
                    date=obs.date,
                    value=obs.value,
                    vintage=obs.vintage,
                    display_label=display_label,
                )
            )
            ref_number += 1

        tokens_used += section_tokens

    # Forecasts section (IMF WEO projections, etc.)
    if forecast_codes and tokens_used < token_budget:
        lines.append("")
        lines.append("=== IMF/FORECAST PROJECTIONS (not actuals) ===")
        tokens_used += _TOKENS_PER_SECTION_HEADER * 2

        for code in forecast_codes:
            obs_list = by_indicator_forecast[code]
            section_tokens = _TOKENS_PER_SECTION_HEADER + (
                _TOKENS_PER_CITATION_LINE * len(obs_list)
            )

            if tokens_used + section_tokens > token_budget:
                truncated.append(f"{code} (forecast)")
                continue

            included.append(f"{code} (forecast)")
            for obs in obs_list:
                formatted_value = _format_value(obs.value, obs.indicator_code)
                display_label = (
                    f"{obs.indicator_code} ({obs.country_iso3}, "
                    f"{_format_date(obs.date)}, IMF forecast): {formatted_value}"
                )
                line = f"  [{ref_number}] {display_label} (source: {obs.source_id})"
                lines.append(line)
                citations.append(
                    Citation(
                        ref_number=ref_number,
                        country_iso3=obs.country_iso3,
                        indicator_code=obs.indicator_code,
                        source_id=obs.source_id,
                        date=obs.date,
                        value=obs.value,
                        vintage=obs.vintage,
                        display_label=display_label,
                    )
                )
                ref_number += 1

            tokens_used += section_tokens

    context_block = "\n".join(lines) if lines else "No observation data available."

    if truncated:
        logger.info(
            "context_builder.truncated",
            n_included=len(included),
            n_truncated=len(truncated),
            truncated_codes=truncated,
        )

    return (
        context_block,
        tuple(citations),
        tuple(included),
        tuple(truncated),
    )


def build_score_summary(score_result: ScoreResult) -> str:
    """Format the ScoreResult as a readable summary for the context.

    This is NOT citation-marked -- it's a structural overview of the
    scores that the LLM uses to understand the country's position.
    The observations ARE citation-marked; the summary connects them.
    """
    lines = [
        f"Composite Score: {score_result.composite:+.2f}"
        if score_result.composite is not None
        else "Composite Score: N/A (insufficient data)",
        f"Data Coverage: {score_result.coverage_fraction:.0%}",
        "",
        "Dimension Scores:",
    ]

    dimension_labels: dict[str, str] = {
        "growth_momentum": "Growth Momentum",
        "external_balance": "External Balance",
        "monetary_stance": "Monetary Stance",
        "risk_sentiment": "Risk Sentiment",
    }

    for dim_key, label in dimension_labels.items():
        dim_score: DimensionScore | None = score_result.dimensions.get(dim_key)
        if dim_score is not None and dim_score.value is not None:
            lines.append(
                f"  {label}: {dim_score.value:+.2f} "
                f"({dim_score.n_series_used} series, "
                f"{dim_score.n_concepts} concepts)"
            )
        else:
            lines.append(f"  {label}: N/A")

    if score_result.news_heat is not None:
        lines.append("")
        lines.append(
            f"News Heat: {score_result.news_heat.sigma:+.1f} sigma "
            f"(volume ratio: {score_result.news_heat.volume_ratio:.1f}x)"
        )

    return "\n".join(lines)


def build_events_summary(
    events: Sequence[EventRecord],
    *,
    max_events: int = 10,
) -> str:
    """Format recent events for the context block.

    Headlines and tone scores from GDELT/GoogleNews. Limited to
    max_events most recent to keep token usage bounded.
    """
    if not events:
        return "No recent news events."

    # Sort by date descending, take most recent
    sorted_events = sorted(events, key=lambda e: e.date, reverse=True)[:max_events]

    lines = []
    for evt in sorted_events:
        date_str = _format_date(evt.date)
        if evt.title:
            tone_str = f" (tone: {evt.value:+.1f})" if evt.value is not None else ""
            lines.append(f"  {date_str}: {evt.title}{tone_str}")
        elif evt.event_type == "tone" and evt.value is not None:
            lines.append(f"  {date_str}: Aggregate tone = {evt.value:+.1f}")
        elif evt.event_type == "volume" and evt.value is not None:
            lines.append(f"  {date_str}: News volume = {evt.value:.0f} articles")

    return "\n".join(lines) if lines else "No recent news events."


def build_grounded_context(
    *,
    country_iso3: str,
    reference_date: datetime.date,
    observations: Sequence[Observation],
    score_result: ScoreResult | None = None,
    events: Sequence[EventRecord] | None = None,
    token_budget: int = 8000,
    max_points_per_indicator: int = 3,
) -> GroundedContext:
    """Build a complete grounded context for a prompt template.

    This is the main entry point. It assembles:
    1. Score summary (if available)
    2. Observation data with citation markers
    3. News events summary (if available)

    All within the token budget.

    Parameters
    ----------
    country_iso3:
        Target country.
    reference_date:
        As-of date for the context.
    observations:
        Latest-vintage observations from the DB.
    score_result:
        Current ScoreResult if available (included as structural overview).
    events:
        Recent EventRecords if available (news/sentiment context).
    token_budget:
        Total tokens available for the context block. Allocated:
        ~200 for score summary, ~200 for events, rest for observations.
    max_points_per_indicator:
        Data points per indicator in the observation section.
    """
    sections: list[str] = []
    budget_remaining = token_budget

    # 1. Score summary (fixed cost, always included if available)
    score_included = False
    if score_result is not None:
        score_summary = build_score_summary(score_result)
        sections.append("CURRENT SCORES:")
        sections.append(score_summary)
        budget_remaining -= _TOKENS_SCORE_SUMMARY
        score_included = True

    # 2. Events summary (bounded cost)
    events_count = 0
    if events:
        events_summary = build_events_summary(events)
        events_tokens = _TOKENS_PER_EVENT * min(len(events), 10)
        if budget_remaining > events_tokens + 500:  # leave at least 500 for observations
            sections.append("")
            sections.append("RECENT NEWS:")
            sections.append(events_summary)
            budget_remaining -= events_tokens
            events_count = min(len(events), 10)

    # 3. Observations with citations (variable cost, budget-constrained)
    obs_context, citations, included, truncated = build_observation_context(
        observations,
        token_budget=max(budget_remaining, 500),
        max_points_per_indicator=max_points_per_indicator,
    )
    sections.append("")
    sections.append("MACRO DATA (with citation references):")
    sections.append(obs_context)

    context_block = "\n".join(sections)
    token_estimate = _estimate_tokens(context_block)

    return GroundedContext(
        country_iso3=country_iso3,
        reference_date=reference_date,
        context_block=context_block,
        citations=citations,
        token_estimate=token_estimate,
        indicators_included=included,
        indicators_truncated=truncated,
        score_result_included=score_included,
        events_included=events_count,
    )
