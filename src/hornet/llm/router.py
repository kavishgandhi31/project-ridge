"""Task-type router -- dispatches LLM requests to the right provider.

The router is the single entry point for all LLM generation. Business
logic (templates, pipeline runner) calls ``router.generate(request)``
and never knows which provider handles it. The routing decision is
config-driven via LLMConfig.routing.

Safety guards:
    1. Health check before dispatch (skips unhealthy providers).
    2. Per-provider daily token budget (prevents runaway API spend).
    3. Fail-closed by default (skip generation rather than silently
       falling back to an expensive provider).
    4. Fallback chain with explicit cost guard.

Token budget tracking is in-memory (resets on process restart).
This is intentional for Phase 6 -- a persistent budget tracker
adds DB complexity for a guard that's primarily about preventing
$200 mistakes, not precise billing. Phase 9 (monetization) will
add proper usage metering.
"""

from __future__ import annotations

import datetime
from collections import defaultdict

import structlog

from hornet.domain.llm import LLMRequest, LLMResponse, TaskType
from hornet.llm.config import LLMConfig
from hornet.llm.protocol import LLMProvider, ProviderError, ProviderHealth

logger = structlog.get_logger(__name__)


class BudgetExhaustedError(Exception):
    """Raised when a provider's daily token budget is exhausted."""

    def __init__(self, provider_id: str, budget: int, used: int) -> None:
        self.provider_id = provider_id
        self.budget = budget
        self.used = used
        super().__init__(
            f"[{provider_id}] Daily token budget exhausted: " f"{used:,} / {budget:,} tokens used"
        )


class NoProviderAvailableError(Exception):
    """Raised when no provider is available for a task type.

    This means the primary provider is unhealthy or over budget,
    and either there is no fallback configured or the fallback
    is also unavailable.
    """

    def __init__(self, task_type: TaskType, reason: str) -> None:
        self.task_type = task_type
        super().__init__(f"No provider available for {task_type.value}: {reason}")


class _TokenBudgetTracker:
    """In-memory daily token budget tracker.

    Resets at UTC midnight. Tracks cumulative tokens_in + tokens_out
    per provider per calendar day.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._budgets: dict[str, int] = {
            "ollama": config.cost_guard.ollama_daily_tokens,
            "claude": config.cost_guard.claude_daily_tokens,
            "openai_compat": config.cost_guard.openai_compat_daily_tokens,
        }
        self._usage: dict[str, int] = defaultdict(int)
        self._usage_date: datetime.date = datetime.datetime.now(datetime.UTC).date()

    def _maybe_reset(self) -> None:
        """Reset usage if the date has changed (UTC midnight rollover)."""
        today = datetime.datetime.now(datetime.UTC).date()
        if today != self._usage_date:
            self._usage.clear()
            self._usage_date = today

    def check_budget(self, provider_id: str) -> None:
        """Raise BudgetExhaustedError if the provider's daily budget is spent."""
        self._maybe_reset()
        budget = self._budgets.get(provider_id, 0)
        if budget == 0:
            return  # 0 = unlimited
        used = self._usage[provider_id]
        if used >= budget:
            raise BudgetExhaustedError(provider_id, budget, used)

    def record_usage(self, provider_id: str, tokens_in: int, tokens_out: int) -> None:
        """Record token usage for a provider."""
        self._maybe_reset()
        self._usage[provider_id] += tokens_in + tokens_out

    def remaining(self, provider_id: str) -> int | None:
        """Return remaining tokens for a provider, or None if unlimited."""
        self._maybe_reset()
        budget = self._budgets.get(provider_id, 0)
        if budget == 0:
            return None
        return max(0, budget - self._usage[provider_id])


class LLMRouter:
    """Routes LLM requests to providers based on task type and config.

    Constructed with an LLMConfig and a dict of provider instances.
    The pipeline runner builds the router at startup and passes it
    to templates.
    """

    def __init__(
        self,
        config: LLMConfig,
        providers: dict[str, LLMProvider],
    ) -> None:
        self._config = config
        self._providers = providers
        self._budget = _TokenBudgetTracker(config)

    @property
    def available_providers(self) -> tuple[str, ...]:
        """Provider IDs that are registered."""
        return tuple(self._providers.keys())

    async def health_check_all(self) -> dict[str, ProviderHealth]:
        """Run health checks on all registered providers."""
        results: dict[str, ProviderHealth] = {}
        for provider_id, provider in self._providers.items():
            results[provider_id] = await provider.health_check()
        return results

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Route a request to the appropriate provider and return the response.

        Routing logic:
        1. Look up primary provider for the request's task_type.
        2. Check health and budget of the primary provider.
        3. If primary is unavailable, try the fallback (if configured).
        4. If no provider is available, raise NoProviderAvailableError
           (fail-closed -- we do NOT silently degrade).

        After a successful generation, token usage is recorded against
        the provider's daily budget.
        """
        primary_id = self._config.routing.provider_for(request.task_type)
        fallback_id = self._config.routing.fallback

        # Try primary
        response = await self._try_provider(primary_id, request)
        if response is not None:
            return response

        # Try fallback if configured and different from primary
        if fallback_id is not None and fallback_id != primary_id:
            logger.warning(
                "router.falling_back",
                task_type=request.task_type.value,
                primary=primary_id,
                fallback=fallback_id,
            )
            response = await self._try_provider(fallback_id, request)
            if response is not None:
                return response

        # No provider available -- fail closed
        if fallback_id is None or fallback_id == primary_id:
            reason = f"Primary '{primary_id}' unavailable, no fallback configured"
        else:
            reason = f"Primary '{primary_id}' and fallback '{fallback_id}' both unavailable"
        raise NoProviderAvailableError(request.task_type, reason)

    async def _try_provider(
        self,
        provider_id: str,
        request: LLMRequest,
    ) -> LLMResponse | None:
        """Attempt generation with a specific provider.

        Returns the response on success, None if the provider is
        unavailable (unhealthy, over budget, or errored).
        """
        provider = self._providers.get(provider_id)
        if provider is None:
            logger.warning("router.provider_not_registered", provider=provider_id)
            return None

        # Check budget before calling
        try:
            self._budget.check_budget(provider_id)
        except BudgetExhaustedError:
            logger.warning(
                "router.budget_exhausted",
                provider=provider_id,
                remaining=self._budget.remaining(provider_id),
            )
            return None

        # Health check
        health = await provider.health_check()
        if not health.healthy:
            logger.warning(
                "router.provider_unhealthy",
                provider=provider_id,
                error=health.error,
            )
            return None

        # Generate
        try:
            response = await provider.generate(request)
        except ProviderError as e:
            logger.error(
                "router.generation_failed",
                provider=provider_id,
                error=str(e),
            )
            return None

        # Validate non-empty content
        if not response.content.strip():
            logger.warning(
                "router.empty_response",
                provider=provider_id,
                tokens_out=response.tokens_out,
                finish_reason=response.finish_reason,
            )
            return None

        # Record usage
        self._budget.record_usage(provider_id, response.tokens_in, response.tokens_out)

        logger.info(
            "router.generation_complete",
            provider=provider_id,
            model=response.model_id,
            task_type=request.task_type.value,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            latency_ms=response.latency_ms,
            budget_remaining=self._budget.remaining(provider_id),
        )

        return response

    def budget_status(self) -> dict[str, int | None]:
        """Return remaining budget for each provider (None = unlimited)."""
        return {pid: self._budget.remaining(pid) for pid in self._providers}
