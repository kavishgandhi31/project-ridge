"""PromptTemplate protocol -- the contract every template must satisfy.

Templates are responsible for:
1. Declaring their task type (for routing).
2. Building an LLMRequest from domain data + grounded context.

Templates are NOT responsible for:
- Choosing which provider to use (that's the router).
- Parsing or validating the response (that's the citation parser).
- Persisting the response (that's the DB repo).
"""

from __future__ import annotations

from importlib import resources
from typing import Protocol

from ridge.domain.llm import GroundedContext, LLMRequest, TaskType


class PromptTemplate(Protocol):
    """Contract for prompt templates.

    Each template declares a task_type and a template_name, and
    can build an LLMRequest from a GroundedContext.
    """

    @property
    def task_type(self) -> TaskType:
        """Task category for router dispatch."""
        ...

    @property
    def template_name(self) -> str:
        """Unique name for this template (e.g. 'country_narrative')."""
        ...

    def build_request(
        self,
        context: GroundedContext,
        *,
        country_name: str,
        run_id: str,
    ) -> LLMRequest:
        """Assemble an LLMRequest from a grounded context.

        Parameters
        ----------
        context:
            The grounded context built by the context builder.
        country_name:
            Human-readable country name for the prompt.
        run_id:
            Pipeline run ID for metadata tracking.
        """
        ...


_PROMPTS_PACKAGE = "ridge.llm.templates.prompts"


def load_prompt_prose(filename: str) -> str:
    """Load a .md prompt prose file from the prompts package.

    Uses importlib.resources so prompt files are found both in an
    editable install and in a built wheel.
    """
    ref = resources.files(_PROMPTS_PACKAGE) / filename
    return ref.read_text(encoding="utf-8")
