"""LLM provider implementations.

Each provider translates the generic LLMRequest into a specific
API call (Ollama HTTP, Anthropic SDK, OpenAI-format HTTP) and
returns an LLMResponse. Providers are stateless beyond their
HTTP client -- they don't cache, don't persist, don't parse
citations. Those concerns live in the router and citation parser.
"""
