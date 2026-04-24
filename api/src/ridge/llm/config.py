"""LLM layer configuration -- provider settings, routing, cost guards.

Loaded from a YAML seed file (llm_config.yaml) at construction time,
same pattern as ScoringConfig and AlertConfig. A future phase will
persist this in a DB table for runtime modification via the API.

Provider-specific settings (model name, base URL, timeout) live in
their respective sub-models. Routing maps TaskType to provider_id.
Cost guards set per-provider daily token budgets to prevent runaway
spend (e.g. a misconfigured batch routing all 183 countries to Claude).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ridge.domain.llm import TaskType


class OllamaConfig(BaseModel):
    """Configuration for the Ollama local inference provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server base URL.",
    )
    model: str = Field(
        default="qwen3:14b-q4_K_M",
        description="Model tag to request from Ollama (must match `ollama list` output).",
    )
    max_context_tokens: int = Field(
        default=32768,
        ge=1,
        description="Context window size for this model (prompt + completion).",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Request timeout. Local models can be slow on first load.",
    )
    max_tokens: int = Field(
        default=4000,
        ge=1,
        description="Default max completion tokens.",
    )


class ClaudeConfig(BaseModel):
    """Configuration for the Anthropic Claude API provider.

    API key comes from Settings (RIDGE_ANTHROPIC_API_KEY env var),
    not from this config -- secrets never live in YAML.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Anthropic model ID.",
    )
    max_context_tokens: int = Field(
        default=200000,
        ge=1,
        description="Context window size for this model.",
    )
    timeout_seconds: int = Field(
        default=60,
        ge=1,
        description="Request timeout for API calls.",
    )
    max_tokens: int = Field(
        default=4000,
        ge=1,
        description="Default max completion tokens.",
    )


class OpenAICompatConfig(BaseModel):
    """Configuration for any server speaking the OpenAI chat completions API.

    Covers vLLM, LM Studio, llama.cpp server, text-generation-webui,
    and any other OpenAI-compatible endpoint. API key is optional --
    many local servers do not require one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = Field(
        ...,
        min_length=1,
        description="Server base URL (e.g. 'http://localhost:8080/v1').",
    )
    model: str = Field(
        ...,
        min_length=1,
        description="Model name to send in the request.",
    )
    max_context_tokens: int = Field(
        default=32768,
        ge=1,
        description="Context window size for this model.",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Request timeout.",
    )
    max_tokens: int = Field(
        default=4000,
        ge=1,
        description="Default max completion tokens.",
    )
    api_key: str | None = Field(
        default=None,
        description="API key if the server requires one. None for local unauthenticated servers.",
    )


class CostGuard(BaseModel):
    """Per-provider daily token budget to prevent runaway spend.

    The router tracks cumulative tokens_in + tokens_out per provider
    per calendar day (UTC). When the budget is exhausted, the router
    refuses to dispatch to that provider. If the provider is the only
    option (no fallback configured), the request fails closed.

    Set to 0 to disable the guard for a provider.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ollama_daily_tokens: int = Field(
        default=0,
        ge=0,
        description="Daily token budget for Ollama. 0 = unlimited (local, zero cost).",
    )
    claude_daily_tokens: int = Field(
        default=500_000,
        ge=0,
        description=(
            "Daily token budget for Claude. Default 500k tokens/day "
            "(~$1.50/day at Sonnet pricing). 0 = unlimited."
        ),
    )
    openai_compat_daily_tokens: int = Field(
        default=0,
        ge=0,
        description="Daily token budget for OpenAI-compatible provider. 0 = unlimited.",
    )


class RoutingConfig(BaseModel):
    """Maps task types to provider IDs.

    Each TaskType must map to a provider_id that matches one of the
    configured providers. The fallback provider is used when the
    primary provider is unhealthy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    country_narrative: str = Field(
        default="ollama",
        description="Provider for batch country narratives (nightly, zero cost).",
    )
    alert_rationale: str = Field(
        default="claude",
        description="Provider for ESCALATE-tier deep analysis (needs real reasoning).",
    )
    interactive_query: str = Field(
        default="claude",
        description="Provider for user questions (Phase 8).",
    )
    classification: str = Field(
        default="ollama",
        description="Provider for tagging and categorization.",
    )
    fallback: str | None = Field(
        default="claude",
        description=(
            "Fallback provider when the primary is unhealthy. "
            "None = fail closed (skip generation rather than fallback)."
        ),
    )

    def provider_for(self, task_type: TaskType) -> str:
        """Return the configured provider_id for a task type."""
        mapping: dict[TaskType, str] = {
            TaskType.COUNTRY_NARRATIVE: self.country_narrative,
            TaskType.ALERT_RATIONALE: self.alert_rationale,
            TaskType.INTERACTIVE_QUERY: self.interactive_query,
            TaskType.CLASSIFICATION: self.classification,
        }
        return mapping[task_type]


class LLMConfig(BaseModel):
    """Top-level LLM layer configuration.

    Loaded from ``llm_config.yaml``. Groups provider configs,
    routing rules, cost guards, and grounding thresholds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ollama: OllamaConfig = Field(
        default_factory=OllamaConfig,
        description="Ollama provider configuration.",
    )
    claude: ClaudeConfig = Field(
        default_factory=ClaudeConfig,
        description="Claude provider configuration.",
    )
    openai_compat: OpenAICompatConfig | None = Field(
        default=None,
        description=(
            "OpenAI-compatible provider configuration. "
            "None = not configured (Ollama and Claude only)."
        ),
    )
    routing: RoutingConfig = Field(
        default_factory=RoutingConfig,
        description="Task-type to provider routing rules.",
    )
    cost_guard: CostGuard = Field(
        default_factory=CostGuard,
        description="Per-provider daily token budgets.",
    )
    min_grounding_score: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum grounding score for an LLM response to be accepted. "
            "Responses below this threshold are logged with a warning "
            "and flagged for review."
        ),
    )
    context_token_reserve: int = Field(
        default=1000,
        ge=0,
        description=(
            "Tokens to reserve for the system prompt and output. "
            "Context builder gets max_context_tokens - max_tokens - this reserve."
        ),
    )

    @model_validator(mode="after")
    def _validate_routing_providers(self) -> LLMConfig:
        """Ensure routing references only configured providers."""
        available = {"ollama", "claude"}
        if self.openai_compat is not None:
            available.add("openai_compat")

        for task_type in TaskType:
            provider = self.routing.provider_for(task_type)
            if provider not in available:
                msg = (
                    f"Routing maps {task_type.value} to '{provider}', "
                    f"but only {sorted(available)} are configured."
                )
                raise ValueError(msg)

        if self.routing.fallback is not None and self.routing.fallback not in available:
            msg = (
                f"Fallback provider '{self.routing.fallback}' "
                f"is not in configured providers {sorted(available)}."
            )
            raise ValueError(msg)

        return self
