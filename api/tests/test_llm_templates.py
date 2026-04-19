"""Tests for prompt templates -- context assembly and request building."""

from __future__ import annotations

import datetime

from hornet.domain.llm import Citation, GroundedContext, TaskType
from hornet.llm.templates.alert_rationale import AlertRationaleTemplate
from hornet.llm.templates.country_narrative import CountryNarrativeTemplate


def _sample_context() -> GroundedContext:
    return GroundedContext(
        country_iso3="NGA",
        reference_date=datetime.date(2026, 4, 1),
        context_block="[1] CPI_YOY (NGA, 2026-03): 33.20% (source: worldbank)",
        citations=(
            Citation(
                ref_number=1,
                country_iso3="NGA",
                indicator_code="CPI_YOY",
                source_id="worldbank",
                date=datetime.date(2026, 3, 1),
                value=33.2,
                vintage=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
                display_label="CPI_YOY (NGA, 2026-03): 33.20%",
            ),
        ),
        token_estimate=30,
        indicators_included=("CPI_YOY",),
    )


# -- Country Narrative Template --


def test_narrative_template_properties() -> None:
    t = CountryNarrativeTemplate()
    assert t.task_type == TaskType.COUNTRY_NARRATIVE
    assert t.template_name == "country_narrative"


def test_narrative_template_builds_request() -> None:
    t = CountryNarrativeTemplate()
    ctx = _sample_context()
    req = t.build_request(ctx, country_name="Nigeria", run_id="test-run")

    assert req.task_type == TaskType.COUNTRY_NARRATIVE
    assert "Nigeria" in req.user_prompt
    assert "NGA" in req.user_prompt
    assert "[1]" in req.user_prompt
    assert req.response_format == "json"
    assert req.max_tokens == 2000
    assert req.metadata["template_name"] == "country_narrative"
    assert req.metadata["run_id"] == "test-run"


def test_narrative_system_prompt_has_grounding_rules() -> None:
    t = CountryNarrativeTemplate()
    ctx = _sample_context()
    req = t.build_request(ctx, country_name="Nigeria", run_id="test")
    # System prompt should contain citation instructions
    assert "[N]" in req.system_prompt
    assert "NEVER invent" in req.system_prompt


# -- Alert Rationale Template --


def test_rationale_template_properties() -> None:
    t = AlertRationaleTemplate()
    assert t.task_type == TaskType.ALERT_RATIONALE
    assert t.template_name == "alert_rationale"


def test_rationale_template_builds_request() -> None:
    t = AlertRationaleTemplate()
    ctx = _sample_context()
    req = t.build_request(ctx, country_name="Nigeria", run_id="test-run")

    assert req.task_type == TaskType.ALERT_RATIONALE
    assert "ESCALATE" in req.user_prompt
    assert "Nigeria" in req.user_prompt
    assert req.max_tokens == 4000
    assert req.temperature == 0.2  # lower for rationale


def test_rationale_system_prompt_has_output_schema() -> None:
    t = AlertRationaleTemplate()
    ctx = _sample_context()
    req = t.build_request(ctx, country_name="Nigeria", run_id="test")
    assert "signal_drivers" in req.system_prompt
    assert "contagion_risk" in req.system_prompt
    assert "recommended_actions" in req.system_prompt
    assert "confidence_level" in req.system_prompt
