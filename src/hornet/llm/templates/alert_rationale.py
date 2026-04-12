"""Alert rationale template -- ESCALATE-tier deep analysis.

Produces a structured analysis (signal drivers, contagion risk,
recommended actions, confidence level) for countries that have
triggered the ESCALATE threshold. Runs via Claude (needs real
reasoning for contagion and recommendation quality).

This is the v2 equivalent of v1's ClaudeAnalyser, but grounded
in citation-marked observations rather than untyped scorecard dicts.
"""

from __future__ import annotations

from hornet.domain.llm import GroundedContext, LLMRequest, TaskType
from hornet.llm.templates.base import load_prompt_prose


class AlertRationaleTemplate:
    """Assembles LLMRequests for ESCALATE-tier deep analysis."""

    def __init__(self) -> None:
        self._system_prompt = load_prompt_prose("alert_rationale.md")

    @property
    def task_type(self) -> TaskType:
        return TaskType.ALERT_RATIONALE

    @property
    def template_name(self) -> str:
        return "alert_rationale"

    def build_request(
        self,
        context: GroundedContext,
        *,
        country_name: str,
        run_id: str,
    ) -> LLMRequest:
        """Build an LLMRequest for an ESCALATE-tier deep analysis.

        The user prompt contains:
        1. Country identification and ESCALATE status
        2. Score summary with dimension detail
        3. Observation data with citation markers
        4. News events for situational context
        """
        user_prompt = (
            f"Provide an ESCALATE-tier deep analysis for {country_name} "
            f"({context.country_iso3}) as of {context.reference_date.isoformat()}.\n\n"
            f"This country has triggered the ESCALATE threshold, indicating "
            f"significant macro deterioration that requires immediate desk attention.\n\n"
            f"{context.context_block}"
        )

        return LLMRequest(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            task_type=self.task_type,
            max_tokens=4000,
            temperature=0.2,
            response_format="json",
            metadata={
                "run_id": run_id,
                "country_iso3": context.country_iso3,
                "template_name": self.template_name,
                "n_citations": len(context.citations),
            },
        )
