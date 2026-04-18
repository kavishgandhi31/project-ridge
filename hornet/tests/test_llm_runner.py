"""Tests for the LLM stage runner -- end-to-end with mock providers."""

from __future__ import annotations

import datetime

from hornet.domain.alerting import DispatchResult, TierAssignment
from hornet.domain.llm import LLMRequest, LLMResponse
from hornet.domain.observation import Observation
from hornet.domain.scoring import DimensionScore, ScoreResult
from hornet.llm.config import LLMConfig
from hornet.llm.protocol import ProviderCapabilities, ProviderHealth
from hornet.llm.router import LLMRouter
from hornet.llm.runner import run_llm_stage


class _MockProvider:
    """Mock provider returning realistic grounded content."""

    def __init__(
        self,
        provider_id: str = "mock",
        healthy: bool = True,
        content: str = '{"headline":"Test","narrative":"CPI at 33.2% [1] and GDP at 3.1% [2].","key_risks":["Risk"],"outlook":"Stable."}',
    ) -> None:
        self._pid = provider_id
        self._healthy = healthy
        self._content = content
        self.generate_count = 0

    @property
    def provider_id(self) -> str:
        return self._pid

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(max_context_tokens=32768)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.generate_count += 1
        return LLMResponse(
            content=self._content,
            provider_id=self._pid,
            model_id="mock-model",
            tokens_in=100,
            tokens_out=50,
            latency_ms=100,
            finish_reason="stop",
            generated_at=datetime.datetime.now(datetime.UTC),
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self._pid,
            healthy=self._healthy,
            latency_ms=10,
        )


def _obs(indicator: str, value: float, country: str = "NGA") -> Observation:
    now = datetime.datetime.now(datetime.UTC)
    return Observation(
        country_iso3=country,
        indicator_code=indicator,
        source_id="worldbank",
        date=datetime.date(2026, 3, 1),
        value=value,
        frequency="monthly",
        vintage=now,
        ingested_at=now,
    )


def _score(country: str = "NGA", composite: float = -1.5) -> ScoreResult:
    return ScoreResult(
        country_iso3=country,
        run_id="test-run",
        scored_at=datetime.datetime.now(datetime.UTC),
        dimensions={
            "growth_momentum": DimensionScore(
                dimension="growth_momentum",
                value=-0.8,
            ),
        },
        composite=composite,
        coverage_fraction=0.5,
    )


def _tier(country: str, tier_value: str) -> TierAssignment:
    from hornet.domain.alerting import AlertTier

    return TierAssignment(
        country_iso3=country,
        country_name=country,
        run_id="test-run",
        evaluated_at=datetime.datetime.now(datetime.UTC),
        composite=-2.0,
        coverage_fraction=0.75,
        raw_tier=AlertTier(tier_value),
        effective_tier=AlertTier(tier_value),
    )


async def test_runner_generates_narratives() -> None:
    """Runner generates narratives for scored countries."""
    ollama = _MockProvider(provider_id="ollama")
    claude = _MockProvider(provider_id="claude")
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": ollama, "claude": claude})

    dispatch = DispatchResult(
        watch=(_tier("NGA", "WATCH"),),
    )

    result = await run_llm_stage(
        router=router,
        dispatch=dispatch,
        observations_by_country={"NGA": [_obs("CPI_YOY", 33.2), _obs("GDP_GROWTH", 3.1)]},
        scores_by_country={"NGA": _score("NGA")},
        country_names={"NGA": "Nigeria"},
        run_id="test-run",
        reference_date=datetime.date(2026, 4, 1),
    )

    assert result.total_generated >= 1
    assert len(result.narratives) == 1
    assert result.narratives[0].country_iso3 == "NGA"
    assert result.total_errors == 0
    assert ollama.generate_count == 1  # narratives route to ollama


async def test_runner_generates_rationales_for_escalate() -> None:
    """Runner generates rationales for ESCALATE countries."""
    ollama = _MockProvider(provider_id="ollama")
    claude = _MockProvider(
        provider_id="claude",
        content='{"signal_drivers":["CPI at 33.2% [1]"],"contagion_risk":"EM spillover","recommended_actions":["Review exposure"],"confidence_level":"high","confidence_justification":"Good coverage"}',
    )
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": ollama, "claude": claude})

    dispatch = DispatchResult(
        escalate=(_tier("NGA", "ESCALATE"),),
    )

    result = await run_llm_stage(
        router=router,
        dispatch=dispatch,
        observations_by_country={"NGA": [_obs("CPI_YOY", 33.2)]},
        scores_by_country={"NGA": _score("NGA")},
        country_names={"NGA": "Nigeria"},
        run_id="test-run",
        reference_date=datetime.date(2026, 4, 1),
    )

    assert len(result.rationales) == 1
    assert result.rationales[0].country_iso3 == "NGA"
    # Narrative also generated (for all scored countries)
    assert len(result.narratives) == 1
    assert claude.generate_count == 1  # rationale routes to claude
    assert ollama.generate_count == 1  # narrative routes to ollama


async def test_runner_handles_provider_failure_gracefully() -> None:
    """Failed generation for one country does not block others."""
    call_count = 0

    class _FailOnSecondCall:
        @property
        def provider_id(self) -> str:
            return "ollama"

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(max_context_tokens=32768)

        async def generate(self, request: LLMRequest) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Return empty content to trigger the router's empty-response guard
                return LLMResponse(
                    content="",
                    provider_id="ollama",
                    model_id="mock",
                    tokens_in=10,
                    tokens_out=0,
                    latency_ms=50,
                    generated_at=datetime.datetime.now(datetime.UTC),
                )
            return LLMResponse(
                content='{"headline":"OK","narrative":"Data [1]","key_risks":[],"outlook":"Fine"}',
                provider_id="ollama",
                model_id="mock",
                tokens_in=100,
                tokens_out=50,
                latency_ms=100,
                finish_reason="stop",
                generated_at=datetime.datetime.now(datetime.UTC),
            )

        async def health_check(self) -> ProviderHealth:
            return ProviderHealth(provider_id="ollama", healthy=True, latency_ms=10)

    claude = _MockProvider(provider_id="claude")
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": _FailOnSecondCall(), "claude": claude})

    dispatch = DispatchResult()

    result = await run_llm_stage(
        router=router,
        dispatch=dispatch,
        observations_by_country={
            "NGA": [_obs("CPI_YOY", 33.2)],
            "TUR": [_obs("CPI_YOY", 42.1, "TUR")],
            "ZAF": [_obs("CPI_YOY", 5.5, "ZAF")],
        },
        scores_by_country={
            "NGA": _score("NGA"),
            "TUR": _score("TUR"),
            "ZAF": _score("ZAF"),
        },
        country_names={"NGA": "Nigeria", "TUR": "Turkey", "ZAF": "South Africa"},
        run_id="test-run",
        reference_date=datetime.date(2026, 4, 1),
    )

    # All 3 succeed: the empty-response country falls back to claude
    # The key guarantee: no crash, no exception, all countries processed
    assert result.total_generated == 3
    assert result.total_errors == 0


async def test_runner_with_no_countries() -> None:
    """Runner handles empty country set gracefully."""
    config = LLMConfig()
    router = LLMRouter(
        config,
        {
            "ollama": _MockProvider(provider_id="ollama"),
            "claude": _MockProvider(provider_id="claude"),
        },
    )

    result = await run_llm_stage(
        router=router,
        dispatch=DispatchResult(),
        observations_by_country={},
        scores_by_country={},
        country_names={},
        run_id="test-run",
        reference_date=datetime.date(2026, 4, 1),
    )

    assert result.total_generated == 0
    assert result.total_errors == 0


async def test_runner_narrative_countries_subset() -> None:
    """Runner only generates narratives for specified subset."""
    ollama = _MockProvider(provider_id="ollama")
    claude = _MockProvider(provider_id="claude")
    config = LLMConfig()
    router = LLMRouter(config, {"ollama": ollama, "claude": claude})

    result = await run_llm_stage(
        router=router,
        dispatch=DispatchResult(),
        observations_by_country={
            "NGA": [_obs("CPI_YOY", 33.2)],
            "TUR": [_obs("CPI_YOY", 42.1, "TUR")],
        },
        scores_by_country={
            "NGA": _score("NGA"),
            "TUR": _score("TUR"),
        },
        country_names={"NGA": "Nigeria", "TUR": "Turkey"},
        run_id="test-run",
        reference_date=datetime.date(2026, 4, 1),
        narrative_countries=["NGA"],  # only NGA
    )

    assert len(result.narratives) == 1
    assert result.narratives[0].country_iso3 == "NGA"
    assert ollama.generate_count == 1
