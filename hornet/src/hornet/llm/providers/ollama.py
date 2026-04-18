"""Ollama provider -- local inference via the Ollama HTTP API.

Talks to a local Ollama server at /api/chat for generation and
/api/tags for health checks. Zero-cost inference for batch work
and free-tier queries.

The Ollama API is simple:
    POST /api/chat with model, messages, options
    Returns a JSON response with message.content and eval metrics.

Ollama supports JSON mode via format="json" in the request, but
quality varies by model. The provider reports supports_json_mode=True
so the router can request it, but the citation parser has a regex
fallback for models that produce malformed JSON.
"""

from __future__ import annotations

import datetime
import time

import httpx
import structlog

from hornet.domain.llm import LLMRequest, LLMResponse
from hornet.llm.config import OllamaConfig
from hornet.llm.protocol import ProviderCapabilities, ProviderError, ProviderHealth

logger = structlog.get_logger(__name__)


class OllamaProvider:
    """LLM provider backed by a local Ollama server.

    Constructed with an OllamaConfig. Creates its own httpx.AsyncClient
    for the Ollama server's base URL.
    """

    def __init__(self, config: OllamaConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
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
        return "ollama"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a chat completion request to Ollama.

        Translates LLMRequest into Ollama's /api/chat format.
        """
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ]

        payload: dict[str, object] = {
            "model": self._config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
            # Disable Qwen3's thinking/reasoning mode. Without this,
            # the model generates a long internal chain-of-thought
            # before the answer, adding 1-2 minutes of hidden latency.
            "think": False,
        }

        if request.response_format == "json":
            payload["format"] = "json"

        start = time.monotonic()
        try:
            resp = await self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                self.provider_id,
                f"Ollama returned HTTP {e.response.status_code}: {e.response.text[:500]}",
            ) from e
        except httpx.ConnectError as e:
            raise ProviderError(
                self.provider_id,
                f"Cannot connect to Ollama at {self._config.base_url}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderError(
                self.provider_id,
                f"Ollama request timed out after {self._config.timeout_seconds}s: {e}",
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        # Ollama provides token counts in eval_count and prompt_eval_count
        tokens_in = data.get("prompt_eval_count", 0)
        tokens_out = data.get("eval_count", 0)
        done_reason = data.get("done_reason")

        return LLMResponse(
            content=content,
            provider_id=self.provider_id,
            model_id=self._config.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            finish_reason=done_reason,
            generated_at=datetime.datetime.now(datetime.UTC),
        )

    async def health_check(self) -> ProviderHealth:
        """Check if Ollama is running and the configured model is loaded."""
        start = time.monotonic()
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            latency_ms = int((time.monotonic() - start) * 1000)

            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]

            # Check if the configured model (or a variant) is available
            model_base = self._config.model.split(":")[0]
            model_found = any(model_base in m for m in models)

            if not model_found:
                return ProviderHealth(
                    provider_id=self.provider_id,
                    healthy=False,
                    latency_ms=latency_ms,
                    error=(
                        f"Model '{self._config.model}' not found. "
                        f"Available: {', '.join(models[:5])}"
                    ),
                )

            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=True,
                latency_ms=latency_ms,
                model_id=self._config.model,
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
