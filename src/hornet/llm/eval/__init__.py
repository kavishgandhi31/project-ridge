"""Eval harness for grounded LLM output quality.

Two modes:
1. Offline: scores pre-recorded golden outputs (for CI, no model needed).
2. Live: calls a real model and scores the output (for nightly eval).

Metrics: grounding score, citation completeness, hallucination count,
forbidden pattern matches.
"""
