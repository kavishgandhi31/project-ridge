"""Prompt templates for grounded LLM generation.

Each template has two layers:
1. A Python class that assembles the grounded context (fetches data,
   builds citation table, constructs GroundedContext).
2. A .md prose file that provides the system prompt and output
   format instructions.

The Python class reads the .md file at construction time and
combines it with the assembled context to produce an LLMRequest.
"""
