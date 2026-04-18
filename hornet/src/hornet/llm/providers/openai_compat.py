"""OpenAI-compatible provider -- any server speaking /v1/chat/completions.

Covers vLLM, LM Studio, llama.cpp server, text-generation-webui,
and any other server that exposes an OpenAI-format API. This is the
"plug and play" provider -- swap local inference backends by changing
a URL and model name in config, no code changes.

Uses httpx directly (not the openai SDK) to avoid adding another
heavy dependency. The OpenAI chat completions API is simple enough
that a raw HTTP client is cleaner than pulling in the full SDK.
"""

from __future__ import annotations

import datetime
import time

import httpx
import structlog

from hornet.domain.llm import LLMRequest, LLMResponse
from hornet.llm.config import OpenAICompatConfig
from hornet.llm.protocol import ProviderCapabilities, ProviderError, ProviderHealth

logger = structlog.get_logger(__name__)


class OpenAICompatProvider:
    """LLM provider for any OpenAI-compatible chat completions server.

    Constructed with an OpenAICompatConfig. Creates its own
    httpx.AsyncClient pointing at the configured base_url.
    """

    def __init__(self, config: OpenAICompatConfig) -> None:
        self._config = config
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
        )
        self._capabilities = ProviderCapabilities(
            max_context_tokens=config.max_context_tokens,
            supports_json_mode=True,
            supports_tool_use=False,
            supports_streaming=True,
            supports_vision=False,
            token_counter="approximate",
        )

    @property
    def provider_id(self) -> str:
        return "openai_compat"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a chat completion request in OpenAI format."""
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ]

        payload: dict[str, object] = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        start = time.monotonic()
        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                self.provider_id,
                f"Server returned HTTP {e.response.status_code}: {e.response.text[:500]}",
            ) from e
        except httpx.ConnectError as e:
            raise ProviderError(
                self.provider_id,
                f"Cannot connect to {self._config.base_url}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError(
                self.provider_id,
                f"Request timed out after {self._config.timeout_seconds}s: {e}",
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        data = resp.json()

        # OpenAI format: choices[0].message.content
        choices = data.get("choices", [])
        if not choices:
            raise ProviderError(
                self.provider_id,
                f"No choices in response: {data}",
            )

        choice = choices[0]
        content = choice.get("message", {}).get("content", "")
        finish_reason = choice.get("finish_reason")

        # Token usage
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        return LLMResponse(
            content=content,
            provider_id=self.provider_id,
            model_id=self._config.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            generated_at=datetime.datetime.now(datetime.UTC),
        )

    async def health_check(self) -> ProviderHealth:
        """Check if the server is reachable by hitting /models."""
        start = time.monotonic()
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            latency_ms = int((time.monotonic() - start) * 1000)

            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", [])]

            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=True,
                latency_ms=latency_ms,
                model_id=self._config.model
                if self._config.model in models
                else models[0]
                if models
                else None,
            )

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=False,
                latency_ms=latency_ms,
                error=str(e),
            )

    async def close(self) -> None:
        """Close the HTTP client. Call on shutdown."""
        await self._client.aclose()
