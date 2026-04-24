"""Tests for LLM configuration and YAML loading."""

from __future__ import annotations

import pytest

from ridge.domain.llm import TaskType
from ridge.llm.config import (
    CostGuard,
    LLMConfig,
    OllamaConfig,
    OpenAICompatConfig,
    RoutingConfig,
)
from ridge.seeds.loader import load_llm_config_from_yaml


def test_default_llm_config() -> None:
    """Default config uses Ollama + Claude, no openai_compat."""
    cfg = LLMConfig()
    assert cfg.ollama.model == "qwen3:14b-q4_K_M"
    assert cfg.claude.model == "claude-sonnet-4-20250514"
    assert cfg.openai_compat is None
    assert cfg.min_grounding_score == 0.8


def test_routing_provider_for() -> None:
    routing = RoutingConfig()
    assert routing.provider_for(TaskType.COUNTRY_NARRATIVE) == "ollama"
    assert routing.provider_for(TaskType.ALERT_RATIONALE) == "claude"
    assert routing.provider_for(TaskType.INTERACTIVE_QUERY) == "claude"
    assert routing.provider_for(TaskType.CLASSIFICATION) == "ollama"


def test_routing_validation_rejects_unknown_provider() -> None:
    """Routing to a non-configured provider raises validation error."""
    with pytest.raises(Exception, match="nonexistent"):
        LLMConfig(
            routing=RoutingConfig(country_narrative="nonexistent"),
        )


def test_routing_openai_compat_accepted_when_configured() -> None:
    """When openai_compat is configured, routing to it is valid."""
    cfg = LLMConfig(
        openai_compat=OpenAICompatConfig(base_url="http://localhost:8080/v1", model="test"),
        routing=RoutingConfig(country_narrative="openai_compat"),
    )
    assert cfg.routing.provider_for(TaskType.COUNTRY_NARRATIVE) == "openai_compat"


def test_cost_guard_defaults() -> None:
    guard = CostGuard()
    assert guard.ollama_daily_tokens == 0  # unlimited
    assert guard.claude_daily_tokens == 500_000
    assert guard.openai_compat_daily_tokens == 0


def test_load_from_yaml_default() -> None:
    """The packaged llm_config.yaml loads without errors."""
    cfg = load_llm_config_from_yaml()
    assert cfg.ollama.model == "qwen3:14b-q4_K_M"
    assert cfg.routing.fallback == "claude"


def test_load_from_yaml_custom() -> None:
    """Custom YAML overrides defaults."""
    yaml_text = """
ollama:
  model: "llama4:8b"
  base_url: "http://localhost:11434"
  max_context_tokens: 16384
  timeout_seconds: 120
  max_tokens: 2000
claude:
  model: "claude-sonnet-4-20250514"
  max_context_tokens: 200000
  timeout_seconds: 60
  max_tokens: 4000
routing:
  country_narrative: "ollama"
  alert_rationale: "claude"
  interactive_query: "claude"
  classification: "ollama"
  fallback: "claude"
cost_guard:
  ollama_daily_tokens: 0
  claude_daily_tokens: 1000000
  openai_compat_daily_tokens: 0
min_grounding_score: 0.9
context_token_reserve: 500
"""
    cfg = load_llm_config_from_yaml(yaml_text)
    assert cfg.ollama.model == "llama4:8b"
    assert cfg.min_grounding_score == 0.9
    assert cfg.cost_guard.claude_daily_tokens == 1_000_000


def test_ollama_config_frozen() -> None:
    cfg = OllamaConfig()
    with pytest.raises((TypeError, ValueError)):
        cfg.model = "other"  # type: ignore[misc]
