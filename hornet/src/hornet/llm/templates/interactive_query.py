"""Interactive query template -- answers user questions about a country.

Used by the POST /ask endpoint. Routes to Claude (per llm_config.yaml)
for interactive latency and reasoning quality. Produces plain text
with inline [N] citations, NOT JSON.
"""

from __future__ import annotations

from hornet.domain.llm import GroundedContext, LLMRequest, TaskType
from hornet.llm.templates.base import load_prompt_prose


class InteractiveQueryTemplate:
    """Assembles LLMRequests for interactive user questions."""

    def __init__(self) -> None:
        self._system_prompt = load_prompt_prose("interactive_query.md")

    @property
    def task_type(self) -> TaskType:
        return TaskType.INTERACTIVE_QUERY

    @property
    def template_name(self) -> str:
        return "interactive_query"

    def build_request(
        self,
        context: GroundedContext,
        *,
        country_name: str,
        run_id: str,
        user_question: str,
    ) -> LLMRequest:
        """Build an LLMRequest for an interactive query.

        The user prompt contains:
        1. The user's question
        2. Country context with citation markers
        """
        user_prompt = (
            f"Question about {country_name} ({context.country_iso3}) "
            f"as of {context.reference_date.isoformat()}:\n\n"
            f"{user_question}\n\n"
            f"--- Data ---\n\n"
            f"{context.context_block}"
        )

        return LLMRequest(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            task_type=self.task_type,
            max_tokens=1500,
            temperature=0.3,
            response_format="text",
            metadata={
                "run_id": run_id,
                "country_iso3": context.country_iso3,
                "template_name": self.template_name,
                "n_citations": len(context.citations),
                "user_question": user_question,
            },
        )
