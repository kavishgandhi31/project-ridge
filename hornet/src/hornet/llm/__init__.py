"""LLM layer -- grounded generation with citation tracking.

This package provides the abstraction for multiple LLM providers
(Ollama, Claude, OpenAI-compatible), a task-type router for
config-driven provider selection, a grounded context builder that
fetches observations from the DB and attaches citation markers, and
an eval harness for regression testing output quality.

The key architectural pattern: templates build deterministic,
citation-marked context from the Observation store. Providers
generate narrative text. The citation parser resolves references
back to observation PKs and flags ungrounded claims. No vector
search, no embedding retrieval -- context is deterministic.
"""

from hornet.llm.citations import validate_response
from hornet.llm.config import LLMConfig
from hornet.llm.context import build_grounded_context
from hornet.llm.protocol import LLMProvider, ProviderCapabilities, ProviderError, ProviderHealth
from hornet.llm.router import LLMRouter, NoProviderAvailableError
from hornet.llm.runner import LLMStageResult, run_llm_stage

__all__ = [
    "LLMConfig",
    "LLMProvider",
    "LLMRouter",
    "LLMStageResult",
    "NoProviderAvailableError",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderHealth",
    "build_grounded_context",
    "run_llm_stage",
    "validate_response",
]
