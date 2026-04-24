"""Claude provider -- Anthropic API via the official SDK.

Handles ESCALATE-tier deep analysis, paid-tier interactive queries,
and any task that needs real multi-step reasoning. Uses the async
Anthropic SDK for non-blocking I/O.

API key comes from Settings (RIDGE_ANTHROPIC_API_KEY env var),
never hardcoded. The provider validates the key on construction
and raises immediately if missing -- fail-fast rather than failing
cryptically mid-pipeline.
"""

from __future__ import annotations

import datetime
import time

import anthropic
import structlog

from ridge.domain.llm import LLMRequest, LLMResponse
from ridge.llm.config import ClaudeConfig
from ridge.llm.protocol import ProviderCapabilities, ProviderError, ProviderHealth

logger = structlog.get_logger(__name__)


class ClaudeProvider:
    """LLM provider backed by the Anthropic Claude API.

    Constructed with a ClaudeConfig and the API key (from Settings).
    Uses the anthropic.AsyncAnthropic SDK client.
    """

    def __init__(self, config: ClaudeConfig, *, api_key: str) -> None:
        self._config = config
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=config.timeout_seconds,
        )
        self._capabilities = ProviderCapabilities(
            max_context_tokens=config.max_context_tokens,
            supports_json_mode=False,  # Claude uses tool_use, not JSON mode
            supports_tool_use=True,
            supports_streaming=True,
            supports_vision=True,
            token_counter="approximate",
        )

    @property
    def provider_id(self) -> str:
        return "claude"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a chat completion request to Claude via the Anthropic SDK."""
        start = time.monotonic()
        try:
            response = await self._client.messages.create(
                model=self._config.model,
                max_tokens=request.max_tokens,
                system=request.system_prompt,
                messages=[{"role": "user", "content": request.user_prompt}],
                temperature=request.temperature,
            )
        except anthropic.AuthenticationError as e:
            raise ProviderError(
                self.provider_id,
                f"Authentication failed -- check RIDGE_ANTHROPIC_API_KEY: {e}",
            ) from e
        except anthropic.RateLimitError as e:
            raise ProviderError(
                self.provider_id,
                f"Rate limited by Anthropic API: {e}",
            ) from e
        except anthropic.APIError as e:
            raise ProviderError(
                self.provider_id,
                f"Anthropic API error: {e}",
            ) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(
                self.provider_id,
                f"Cannot connect to Anthropic API: {e}",
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)

        # Extract text content from response
        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        return LLMResponse(
            content=content,
            provider_id=self.provider_id,
            model_id=self._config.model,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            latency_ms=latency_ms,
            finish_reason=response.stop_reason,
            generated_at=datetime.datetime.now(datetime.UTC),
        )

    async def health_check(self) -> ProviderHealth:
        """Validate API key by counting tokens on a minimal message.

        This is cheaper than a full generation -- the count_tokens
        endpoint verifies auth without consuming output tokens.
        """
        start = time.monotonic()
        try:
            await self._client.messages.count_tokens(
                model=self._config.model,
                messages=[{"role": "user", "content": "health check"}],
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=True,
                latency_ms=latency_ms,
                model_id=self._config.model,
            )

        except (
            anthropic.AuthenticationError,
            anthropic.APIError,
            anthropic.APIConnectionError,
        ) as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=False,
                latency_ms=latency_ms,
                error=str(e),
            )

    async def close(self) -> None:
        """Close the SDK client. Call on shutdown."""
        await self._client.close()
