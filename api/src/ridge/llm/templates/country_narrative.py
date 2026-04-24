"""Country narrative template -- batch macro narrative for each country.

Produces a structured narrative (headline, body, key risks, outlook)
grounded in the observation data. Runs nightly via Ollama (zero cost)
for all countries with sufficient data coverage.
"""

from __future__ import annotations

from ridge.domain.llm import GroundedContext, LLMRequest, TaskType
from ridge.llm.templates.base import load_prompt_prose


class CountryNarrativeTemplate:
    """Assembles LLMRequests for country narrative generation."""

    def __init__(self) -> None:
        self._system_prompt = load_prompt_prose("country_narrative.md")

    @property
    def task_type(self) -> TaskType:
        return TaskType.COUNTRY_NARRATIVE

    @property
    def template_name(self) -> str:
        return "country_narrative"

    def build_request(
        self,
        context: GroundedContext,
        *,
        country_name: str,
        run_id: str,
    ) -> LLMRequest:
        """Build an LLMRequest for a country narrative.

        The user prompt contains:
        1. Country identification
        2. Score summary (if available)
        3. Observation data with citation markers
        4. News events (if available)
        """
        user_prompt = (
            f"Write a macro narrative for {country_name} ({context.country_iso3}) "
            f"as of {context.reference_date.isoformat()}.\n\n"
            f"{context.context_block}"
        )

        return LLMRequest(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            task_type=self.task_type,
            max_tokens=2000,
            temperature=0.3,
            response_format="json",
            metadata={
                "run_id": run_id,
                "country_iso3": context.country_iso3,
                "template_name": self.template_name,
                "n_citations": len(context.citations),
            },
        )
