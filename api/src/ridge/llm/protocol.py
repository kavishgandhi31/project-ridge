"""LLMProvider protocol -- the contract every LLM backend must satisfy.

Three providers ship in Phase 6:

* OllamaProvider  -- local inference via Ollama /api/chat
* ClaudeProvider  -- Anthropic SDK async (Sonnet default)
* OpenAICompatibleProvider -- any server that speaks /v1/chat/completions
  (vLLM, LM Studio, llama.cpp, text-generation-webui, etc.)

The protocol is deliberately minimal: generate + health_check +
capabilities. Providers do NOT parse citations, do NOT cache, do NOT
persist results. Those concerns live in the citation parser, router,
and DB repo respectively.

ProviderCapabilities enables the context builder and router to adapt
behavior per provider (token budgets, structured output support,
streaming for interactive queries in Phase 8).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ridge.domain.llm import LLMRequest, LLMResponse


class ProviderCapabilities(BaseModel):
    """What an LLM provider can do -- used by router and context builder.

    The context builder reads ``max_context_tokens`` to decide how much
    observation data to include. The router reads ``supports_json_mode``
    and ``supports_tool_use`` to decide whether to request structured
    output or fall back to regex extraction. Phase 8 will read
    ``supports_streaming`` for interactive queries.

    Token counter strategy tells the context builder how to estimate
    token counts:
    * "tiktoken" -- use the tiktoken library (accurate for OpenAI-family models)
    * "approximate" -- use the ~4 chars/token heuristic (safe fallback)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_context_tokens: int = Field(
        ...,
        ge=1,
        description="Maximum context window in tokens (prompt + completion budget).",
    )
    supports_json_mode: bool = Field(
        default=False,
        description="Whether the provider supports native JSON output mode.",
    )
    supports_tool_use: bool = Field(
        default=False,
        description="Whether the provider supports tool/function calling for structured output.",
    )
    supports_streaming: bool = Field(
        default=False,
        description="Whether the provider supports streaming responses (Phase 8 interactive).",
    )
    supports_vision: bool = Field(
        default=False,
        description="Whether the provider accepts image inputs (future-proofing).",
    )
    token_counter: Literal["tiktoken", "approximate"] = Field(
        default="approximate",
        description="Strategy for estimating token counts in the context builder.",
    )


class ProviderHealth(BaseModel):
    """Operational status of an LLM provider.

    Returned by ``LLMProvider.health_check()``. The router uses this
    to skip unhealthy providers and fall back (or fail closed).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(
        ...,
        min_length=1,
        description="Which provider was checked.",
    )
    healthy: bool = Field(
        ...,
        description="True if the provider responded within timeout.",
    )
    latency_ms: int | None = Field(
        default=None,
        description="Round-trip time of the health probe in milliseconds.",
    )
    model_id: str | None = Field(
        default=None,
        description="Model the provider reported as loaded (Ollama) or configured.",
    )
    error: str | None = Field(
        default=None,
        description="Error message if unhealthy.",
    )


@runtime_checkable
class LLMProvider(Protocol):
    """The contract every LLM backend must implement.

    Three methods:

    * ``generate(request)`` sends a prompt and returns the raw LLM
      response. The provider translates LLMRequest into its native
      API format and LLMResponse back. No citation parsing, no
      caching, no persistence -- just the API call.

    * ``health_check()`` probes the provider and returns a
      ProviderHealth. The router calls this before dispatch to skip
      unhealthy providers. For Ollama, this pings ``/api/tags``.
      For Claude, this validates the API key. For OpenAI-compat,
      this hits ``/v1/models``.

    * ``capabilities`` (property) returns ProviderCapabilities so
      the context builder and router can adapt behavior per provider.

    Concrete providers are constructed with their configuration
    (model name, API key, base URL, timeout) and an httpx.AsyncClient
    (or the Anthropic SDK client). They are stateless beyond the
    HTTP client.
    """

    @property
    def provider_id(self) -> str:
        """Stable identifier for this provider (e.g. 'ollama', 'claude')."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What this provider can do -- used by router and context builder."""
        ...

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a prompt and return the raw response.

        Raises
        ------
        ProviderError
            If the API call fails after retries. The router catches
            this and either falls back or fails closed.
        """
        ...

    async def health_check(self) -> ProviderHealth:
        """Probe the provider and return operational status.

        Must not raise -- always returns a ProviderHealth, even if
        the probe fails (healthy=False, error=<message>).
        """
        ...


class ProviderError(Exception):
    """Raised when an LLM provider call fails after retries.

    Carries the provider_id and original error message so the router
    can log which provider failed and decide whether to fall back.
    """

    def __init__(self, provider_id: str, message: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"[{provider_id}] {message}")
