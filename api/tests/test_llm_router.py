"""Tests for the LLM router -- routing, health checks, budget guards."""

from __future__ import annotations

import datetime

import pytest

from ridge.domain.llm import LLMRequest, LLMResponse, TaskType
from ridge.llm.config import LLMConfig, RoutingConfig
from ridge.llm.protocol import ProviderCapabilities, ProviderHealth
from ridge.llm.router import (
    LLMRouter,
    NoProviderAvailableError,
)

# -- Mock provider --


class MockProvider:
    """A mock LLM provider for testing the router."""

    def __init__(
        self,
        provider_id: str = "mock",
        healthy: bool = True,
        response_content: str = "Mock response [1]",
        tokens_in: int = 100,
        tokens_out: int = 50,
    ) -> None:
        self._provider_id = provider_id
        self._healthy = healthy
        self._response_content = response_content
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.generate_count = 0

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            max_context_tokens=32768,
            supports_json_mode=True,
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.generate_count += 1
        return LLMResponse(
            content=self._response_content,
            provider_id=self._provider_id,
            model_id="mock-model",
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            latency_ms=100,
            finish_reason="stop",
            generated_at=datetime.datetime.now(datetime.UTC),
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self._provider_id,
            healthy=self._healthy,
            latency_ms=10,
            model_id="mock-model",
        )


def _request(task_type: TaskType = TaskType.COUNTRY_NARRATIVE) -> LLMRequest:
    return LLMRequest(
        system_prompt="Test system prompt.",
        user_prompt="Test user prompt.",
        task_type=task_type,
    )


# -- Tests --


async def test_router_routes_to_primary() -> None:
    """Router dispatches to the provider mapped to the task type."""
    ollama = MockProvider(provider_id="ollama")
    claude = MockProvider(provider_id="claude")
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": ollama, "claude": claude})

    # COUNTRY_NARRATIVE routes to ollama by default
    await router.generate(_request(TaskType.COUNTRY_NARRATIVE))
    assert ollama.generate_count == 1
    assert claude.generate_count == 0

    # ALERT_RATIONALE routes to claude
    await router.generate(_request(TaskType.ALERT_RATIONALE))
    assert claude.generate_count == 1


async def test_router_falls_back_on_unhealthy() -> None:
    """Router falls back to fallback provider when primary is unhealthy."""
    ollama = MockProvider(provider_id="ollama", healthy=False)
    claude = MockProvider(provider_id="claude")
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": ollama, "claude": claude})

    await router.generate(_request(TaskType.COUNTRY_NARRATIVE))
    assert ollama.generate_count == 0  # skipped (unhealthy)
    assert claude.generate_count == 1  # fallback


async def test_router_fails_closed_when_all_unhealthy() -> None:
    """Router raises NoProviderAvailableError when all providers are down."""
    ollama = MockProvider(provider_id="ollama", healthy=False)
    claude = MockProvider(provider_id="claude", healthy=False)
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": ollama, "claude": claude})

    with pytest.raises(NoProviderAvailableError):
        await router.generate(_request(TaskType.COUNTRY_NARRATIVE))


async def test_router_budget_tracking() -> None:
    """Router tracks token usage and blocks when budget exhausted."""
    claude = MockProvider(provider_id="claude", tokens_in=400_000, tokens_out=100_000)
    config = LLMConfig()  # default claude budget: 500k
    router = LLMRouter(config, {"claude": claude})

    # First call: 500k tokens, exhausts the budget
    await router.generate(_request(TaskType.ALERT_RATIONALE))
    assert claude.generate_count == 1

    # Second call: budget exhausted, should try fallback (which is also claude)
    # Since fallback == primary == claude, and budget is exhausted, fails closed
    with pytest.raises(NoProviderAvailableError):
        await router.generate(_request(TaskType.ALERT_RATIONALE))


async def test_router_budget_unlimited() -> None:
    """Unlimited budget (0) never triggers exhaustion."""
    ollama = MockProvider(provider_id="ollama", tokens_in=1_000_000, tokens_out=500_000)
    config = LLMConfig()  # ollama budget: 0 (unlimited)
    router = LLMRouter(config, {"ollama": ollama, "claude": MockProvider(provider_id="claude")})

    # Multiple calls should all succeed
    for _ in range(5):
        await router.generate(_request(TaskType.COUNTRY_NARRATIVE))
    assert ollama.generate_count == 5


async def test_router_budget_status() -> None:
    """budget_status reports remaining tokens."""
    config = LLMConfig()
    router = LLMRouter(
        config,
        {
            "ollama": MockProvider(provider_id="ollama"),
            "claude": MockProvider(provider_id="claude"),
        },
    )

    status = router.budget_status()
    assert status["ollama"] is None  # unlimited
    assert status["claude"] == 500_000  # full budget


async def test_router_fallback_none_fails_closed() -> None:
    """When fallback=None and primary is unhealthy, fail closed with clear message."""
    ollama = MockProvider(provider_id="ollama", healthy=False)
    config = LLMConfig(
        routing=RoutingConfig(fallback=None),
    )
    router = LLMRouter(config, {"ollama": ollama, "claude": MockProvider(provider_id="claude")})

    with pytest.raises(NoProviderAvailableError, match="no fallback configured"):
        await router.generate(_request(TaskType.COUNTRY_NARRATIVE))


async def test_router_rejects_empty_content() -> None:
    """Router treats empty-string responses as failures."""
    empty_provider = MockProvider(provider_id="ollama", response_content="")
    claude = MockProvider(provider_id="claude")
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": empty_provider, "claude": claude})

    # Primary returns empty -> falls back to claude
    resp = await router.generate(_request(TaskType.COUNTRY_NARRATIVE))
    assert resp.provider_id == "claude"
    assert empty_provider.generate_count == 1
    assert claude.generate_count == 1


async def test_router_health_check_all() -> None:
    """health_check_all returns status for all providers."""
    ollama = MockProvider(provider_id="ollama", healthy=True)
    claude = MockProvider(provider_id="claude", healthy=False)
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": ollama, "claude": claude})

    results = await router.health_check_all()
    assert results["ollama"].healthy is True
    assert results["claude"].healthy is False
