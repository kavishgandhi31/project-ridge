"""LLM layer domain types -- citations, requests, responses, eval.

These are the canonical shapes the LLM layer reads and produces.
The grounded-generation pattern works in three stages:

1. Context builder fetches observations from the DB and formats them
   with numbered citation markers [1], [2], etc.
2. Provider generates narrative text referencing those markers.
3. Citation parser extracts markers from the output, resolves them
   back to observations, and flags ungrounded numeric claims.

All types are frozen Pydantic models with zero I/O, following the
same pattern as Observation, ScoreResult, and TierAssignment.
"""

from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskType(StrEnum):
    """LLM task categories for provider routing.

    Each prompt template declares one of these. The router maps
    task types to providers via config, so business logic never
    picks which model to call -- that decision lives in YAML.

    COUNTRY_NARRATIVE and ALERT_RATIONALE are the Phase 6 templates.
    INTERACTIVE_QUERY and CLASSIFICATION are reserved for Phase 8+.
    """

    COUNTRY_NARRATIVE = "country_narrative"
    ALERT_RATIONALE = "alert_rationale"
    INTERACTIVE_QUERY = "interactive_query"
    CLASSIFICATION = "classification"


class Citation(BaseModel):
    """A single grounded reference linking a number to its source observation.

    The ref_number is the [1], [2], etc. that appears in the context
    block and (ideally) in the LLM's output. The remaining fields are
    the composite PK of the observation table -- enough to look up the
    exact row and verify the cited value matches.

    The display_label is the human-readable form that appears in the
    context block (e.g. "CPI_YOY (NGA, 2026-03): 33.20%").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref_number: int = Field(
        ...,
        ge=1,
        description="Sequential reference number used in context and output ([1], [2], etc.).",
    )
    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO3 code of the cited observation.",
    )
    indicator_code: str = Field(
        ...,
        min_length=1,
        description="Canonical indicator code (e.g. CPI_YOY).",
    )
    source_id: str = Field(
        ...,
        min_length=1,
        description="Data source that produced the observation (e.g. 'fred').",
    )
    date: datetime.date = Field(
        ...,
        description="Observation date (the date the data point refers to).",
    )
    value: float = Field(
        ...,
        description="The numeric value being cited.",
    )
    vintage: datetime.datetime = Field(
        ...,
        description="When the source published this specific value (composite PK completeness).",
    )
    display_label: str = Field(
        ...,
        min_length=1,
        description=(
            "Human-readable label for the context block, e.g. " "'CPI_YOY (NGA, 2026-03): 33.20%'."
        ),
    )


class GroundedContext(BaseModel):
    """Materialized context window for a grounded prompt.

    Built by the context builder from the Observation store. Contains
    the formatted text block (with [1], [2] markers), the citation
    lookup table, and metadata about what was included vs. truncated
    due to token budget constraints.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Country this context was built for.",
    )
    reference_date: datetime.date = Field(
        ...,
        description="As-of date for the context (most recent data cutoff).",
    )
    context_block: str = Field(
        ...,
        description=(
            "Formatted text block with numbered citation markers. "
            "This is injected into the prompt template."
        ),
    )
    citations: tuple[Citation, ...] = Field(
        ...,
        description="Citation lookup table -- maps ref numbers to observation PKs.",
    )
    token_estimate: int = Field(
        ...,
        ge=0,
        description="Approximate token count of context_block (for budget tracking).",
    )
    indicators_included: tuple[str, ...] = Field(
        default=(),
        description="Canonical indicator codes that made it into the context.",
    )
    indicators_truncated: tuple[str, ...] = Field(
        default=(),
        description="Indicator codes dropped due to token budget. Logged for diagnostics.",
    )
    score_result_included: bool = Field(
        default=False,
        description="Whether the current ScoreResult was included in the context.",
    )
    events_included: int = Field(
        default=0,
        ge=0,
        description="Number of EventRecords included in the context (news/sentiment).",
    )


class LLMRequest(BaseModel):
    """What goes to a provider -- provider-agnostic request shape.

    Templates produce these. The router dispatches them to the
    appropriate provider. Providers translate them into their
    native API format (Ollama /api/chat, Anthropic messages API,
    OpenAI /v1/chat/completions).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    system_prompt: str = Field(
        ...,
        description="System-level instructions (grounding rules, output format, persona).",
    )
    user_prompt: str = Field(
        ...,
        description="User-level prompt with grounded context and specific question/task.",
    )
    task_type: TaskType = Field(
        ...,
        description="Task category for routing and billing.",
    )
    max_tokens: int = Field(
        default=4000,
        ge=1,
        description="Maximum tokens in the response.",
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description=(
            "Sampling temperature. Low (0.1-0.3) for factual grounded output, "
            "higher for creative tasks. Default 0.3 balances coherence and variety."
        ),
    )
    response_format: Literal["text", "json"] = Field(
        default="json",
        description=(
            "Expected response format. 'json' enables JSON mode on providers "
            "that support it; the response parser handles extraction for those "
            "that do not."
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Pass-through metadata for logging and billing. Typical keys: "
            "run_id, country_iso3, template_name. Never sent to the LLM."
        ),
    )


class LLMResponse(BaseModel):
    """Raw response from a provider -- before citation parsing.

    This is the provider's output, unprocessed. Citation extraction,
    JSON parsing, and grounding validation happen downstream in the
    citation parser, producing a GroundedResponse.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(
        ...,
        description="Raw text content from the LLM.",
    )
    provider_id: str = Field(
        ...,
        min_length=1,
        description="Which provider produced this (e.g. 'ollama', 'claude', 'openai_compat').",
    )
    model_id: str = Field(
        ...,
        min_length=1,
        description="Specific model used (e.g. 'qwen3:14b', 'claude-sonnet-4-20250514').",
    )
    tokens_in: int = Field(
        ...,
        ge=0,
        description="Input tokens consumed.",
    )
    tokens_out: int = Field(
        ...,
        ge=0,
        description="Output tokens generated.",
    )
    latency_ms: int = Field(
        ...,
        ge=0,
        description="Wall-clock latency in milliseconds.",
    )
    finish_reason: str | None = Field(
        default=None,
        description=(
            "Why generation stopped: 'stop' (natural), 'length' (hit max_tokens), "
            "'error', or None if the provider did not report one."
        ),
    )
    generated_at: datetime.datetime = Field(
        ...,
        description="UTC timestamp when the response was received.",
    )


class GroundedResponse(BaseModel):
    """LLM output after citation extraction and grounding validation.

    This is the final product of the grounded-generation pipeline:
    narrative text with every numeric claim traced back to its source
    observation. The grounding_score is the key quality metric --
    it measures what fraction of numeric claims are backed by citations.

    Persisted to the llm_response DB table for audit and the Phase 8
    frontend to render citation chips.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(
        ...,
        description="The narrative text from the LLM.",
    )
    citations_used: tuple[Citation, ...] = Field(
        default=(),
        description="Citations actually referenced in the LLM output (resolved from [N] markers).",
    )
    citations_available: tuple[Citation, ...] = Field(
        default=(),
        description="All citations that were in the context (superset of citations_used).",
    )
    ungrounded_claims: tuple[str, ...] = Field(
        default=(),
        description=(
            "Numeric strings found in the output without a citation marker. "
            "Each entry is the raw text fragment (e.g. '45.2%'). These are "
            "potential hallucinations that need review."
        ),
    )
    grounding_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of numeric claims that are grounded by citations. "
            "1.0 = every number is cited. 0.0 = no citations found. "
            "This is the primary quality gate for LLM output."
        ),
    )

    # -- Provider metadata (carried from LLMResponse) --

    provider_id: str = Field(
        ...,
        min_length=1,
        description="Which provider produced this.",
    )
    model_id: str = Field(
        ...,
        min_length=1,
        description="Specific model used.",
    )
    tokens_in: int = Field(..., ge=0, description="Input tokens consumed.")
    tokens_out: int = Field(..., ge=0, description="Output tokens generated.")
    latency_ms: int = Field(..., ge=0, description="Wall-clock latency in milliseconds.")

    # -- Context metadata (carried from template/router) --

    task_type: TaskType = Field(..., description="Which task type produced this.")
    template_name: str = Field(
        ...,
        min_length=1,
        description="Name of the prompt template (e.g. 'country_narrative').",
    )
    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Country this response is about.",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="Pipeline run that triggered this generation.",
    )
    generated_at: datetime.datetime = Field(
        ...,
        description="UTC timestamp when the response was received.",
    )


# ------------------------------------------------------------------
# Eval types
# ------------------------------------------------------------------


class EvalQuestion(BaseModel):
    """One regression test case for the eval harness.

    Defines the input parameters and expected output characteristics
    for a single eval question. The harness runs the question through
    a template + provider, then scores the output against these
    expectations.

    Questions are loaded from YAML (eval/questions.yaml). The harness
    supports two modes: live (calls a real model) and offline (scores
    a pre-recorded golden output).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier (e.g. 'narrative_nga_01').",
    )
    template_name: str = Field(
        ...,
        min_length=1,
        description="Which prompt template to exercise.",
    )
    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Target country.",
    )
    reference_date: datetime.date = Field(
        ...,
        description="As-of date for the context builder.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of what this question tests.",
    )
    required_indicators: tuple[str, ...] = Field(
        default=(),
        description=(
            "Indicator codes that MUST appear in citations. " "Completeness metric checks these."
        ),
    )
    min_citations: int = Field(
        default=1,
        ge=0,
        description="Minimum number of citations expected in the output.",
    )
    max_ungrounded: int = Field(
        default=0,
        ge=0,
        description=(
            "Maximum tolerable ungrounded numeric claims. "
            "0 = strict (every number must be cited)."
        ),
    )
    forbidden_patterns: tuple[str, ...] = Field(
        default=(),
        description=(
            "Regex patterns that indicate hallucination or format violation. "
            "If any match, the question fails regardless of other metrics."
        ),
    )


class EvalResult(BaseModel):
    """Result of running one eval question through the harness.

    Captures all metrics computed by the harness plus a pass/fail
    verdict. Persisted for trend tracking across nightly eval runs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str = Field(
        ...,
        min_length=1,
        description="Which question was evaluated.",
    )
    grounding_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of numeric claims backed by citations.",
    )
    citation_completeness: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of required_indicators actually cited.",
    )
    n_citations_used: int = Field(
        ...,
        ge=0,
        description="Total citations found in the output.",
    )
    n_ungrounded: int = Field(
        ...,
        ge=0,
        description="Ungrounded numeric claims found.",
    )
    n_forbidden_matches: int = Field(
        default=0,
        ge=0,
        description="Number of forbidden patterns that matched.",
    )
    passed: bool = Field(
        ...,
        description=(
            "True if: grounding_score >= threshold AND "
            "n_ungrounded <= max_ungrounded AND "
            "n_forbidden_matches == 0 AND "
            "n_citations_used >= min_citations AND "
            "all required_indicators cited."
        ),
    )
    failure_reasons: tuple[str, ...] = Field(
        default=(),
        description="Why this question failed (empty if passed).",
    )
    evaluated_at: datetime.datetime = Field(
        ...,
        description="When the eval ran.",
    )
    provider_id: str = Field(
        ...,
        min_length=1,
        description="Provider used for this eval run.",
    )
    model_id: str = Field(
        ...,
        min_length=1,
        description="Model used for this eval run.",
    )
    latency_ms: int = Field(
        ...,
        ge=0,
        description="End-to-end latency for this question (context build + LLM call + parsing).",
    )
