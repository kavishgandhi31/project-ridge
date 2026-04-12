"""Live smoke test: one country narrative through the full LLM pipeline.

Requires:
- Ollama running locally with qwen3:14b-q4_K_M
- No DB needed -- uses synthetic observations

Usage:
    cd hornet && .venv/bin/python scripts/smoke_test_llm.py
"""

from __future__ import annotations

import asyncio
import datetime
import json
import sys

from hornet.domain.observation import Observation
from hornet.domain.scoring import DimensionScore, ScoreResult
from hornet.llm.citations import validate_response
from hornet.llm.config import LLMConfig
from hornet.llm.context import build_grounded_context
from hornet.llm.providers.ollama import OllamaProvider
from hornet.llm.templates.country_narrative import CountryNarrativeTemplate

COUNTRY_DATA: dict[str, dict[str, object]] = {
    "NGA": {
        "name": "Nigeria",
        "obs": [
            ("CPI_YOY", "2026-03-01", 33.20, "monthly"),
            ("GDP_GROWTH", "2025-12-31", 3.10, "quarterly"),
            ("CURRENT_ACCOUNT_GDP", "2025-12-31", -1.80, "quarterly"),
            ("RESERVES_MONTHS_IMPORTS", "2025-12-31", 4.20, "quarterly"),
            ("GOVT_DEBT_GDP", "2025-12-31", 38.50, "annual"),
            ("UNEMPLOYMENT", "2025-12-31", 33.30, "annual"),
            ("POLICY_RATE", "2026-03-01", 27.50, "monthly"),
        ],
        "dims": {
            "growth_momentum": -0.8,
            "external_balance": -1.2,
            "monetary_stance": -2.1,
            "risk_sentiment": -0.5,
        },
        "composite": -1.15,
    },
    "TUR": {
        "name": "Turkey",
        "obs": [
            ("CPI_YOY", "2026-03-01", 42.10, "monthly"),
            ("GDP_GROWTH", "2025-12-31", 2.80, "quarterly"),
            ("CURRENT_ACCOUNT_GDP", "2025-12-31", -4.50, "quarterly"),
            ("POLICY_RATE", "2026-03-01", 45.00, "monthly"),
            ("FX_USD", "2026-03-28", 38.75, "daily"),
            ("GOVT_DEBT_GDP", "2025-12-31", 30.20, "annual"),
            ("TRADE_OPENNESS", "2025-12-31", 62.40, "annual"),
            ("UNEMPLOYMENT", "2025-12-31", 9.80, "annual"),
        ],
        "dims": {
            "growth_momentum": -0.4,
            "external_balance": -1.8,
            "monetary_stance": -2.5,
            "risk_sentiment": -1.3,
        },
        "composite": -1.50,
    },
}


def _make_observations(iso3: str) -> list[Observation]:
    """Build synthetic observations for a country."""
    now = datetime.datetime.now(datetime.UTC)
    data = COUNTRY_DATA[iso3]
    obs_specs = data["obs"]
    assert isinstance(obs_specs, list)

    result: list[Observation] = []
    for spec in obs_specs:
        assert isinstance(spec, tuple)
        code, date_str, value, freq = spec
        result.append(
            Observation(
                country_iso3=iso3,
                indicator_code=str(code),
                source_id="worldbank",
                date=datetime.date.fromisoformat(str(date_str)),
                value=float(value),  # type: ignore[arg-type]
                frequency=str(freq),  # type: ignore[arg-type]
                vintage=now,
                ingested_at=now,
            )
        )
    return result


def _make_score(iso3: str) -> ScoreResult:
    data = COUNTRY_DATA[iso3]
    dims_raw = data["dims"]
    assert isinstance(dims_raw, dict)
    composite = data["composite"]
    assert isinstance(composite, float)

    dimensions: dict[str, DimensionScore] = {}
    for dim_name, val in dims_raw.items():
        assert isinstance(val, float)
        dimensions[dim_name] = DimensionScore(
            dimension=dim_name,
            value=val,
            n_series_used=2,
            n_series_stale=0,
            n_concepts=2,
        )

    return ScoreResult(
        country_iso3=iso3,
        run_id="smoke-test",
        scored_at=datetime.datetime.now(datetime.UTC),
        dimensions=dimensions,
        composite=composite,
        coverage_fraction=1.0,
    )


async def main() -> None:
    iso3 = sys.argv[1].upper() if len(sys.argv) > 1 else "NGA"
    if iso3 not in COUNTRY_DATA:
        print(f"Unknown country: {iso3}. Available: {', '.join(COUNTRY_DATA.keys())}")
        sys.exit(1)

    country_name = str(COUNTRY_DATA[iso3]["name"])
    print("=" * 60)
    print(f"LIVE SMOKE TEST: {country_name} country narrative via Ollama")
    print("=" * 60)

    # 1. Build grounded context
    observations = _make_observations(iso3)
    score = _make_score(iso3)

    context = build_grounded_context(
        country_iso3=iso3,
        reference_date=datetime.date(2026, 4, 1),
        observations=observations,
        score_result=score,
        token_budget=8000,
    )

    print(
        f"\nContext built: {len(context.citations)} citations, " f"~{context.token_estimate} tokens"
    )
    print(f"Indicators included: {', '.join(context.indicators_included)}")
    print(f"Indicators truncated: {', '.join(context.indicators_truncated) or 'none'}")

    # 2. Build LLM request via template
    template = CountryNarrativeTemplate()
    request = template.build_request(context, country_name=country_name, run_id="smoke-test")

    print(
        f"\nRequest built: task_type={request.task_type.value}, "
        f"max_tokens={request.max_tokens}, temp={request.temperature}"
    )

    # 3. Call Ollama
    config = LLMConfig()
    provider = OllamaProvider(config.ollama)

    print(f"\nCalling Ollama ({config.ollama.model})...")
    print("(This may take 30-120 seconds on first inference...)")

    try:
        llm_response = await provider.generate(request)
    except Exception as e:
        print(f"\nERROR: {e}")
        await provider.close()
        sys.exit(1)

    print(
        f"\nResponse received: {llm_response.tokens_in} in / "
        f"{llm_response.tokens_out} out tokens, "
        f"{llm_response.latency_ms}ms"
    )

    # 4. Validate citations
    # Extract known score values so they don't trigger false positives
    score_values: set[float] = set()
    if score.composite is not None:
        score_values.add(score.composite)
    for dim in score.dimensions.values():
        if dim.value is not None:
            score_values.add(dim.value)

    grounded = validate_response(
        llm_response,
        context.citations,
        task_type=template.task_type,
        template_name=template.template_name,
        country_iso3=iso3,
        run_id="smoke-test",
        known_score_values=frozenset(score_values),
    )

    print(f"\n{'=' * 60}")
    print("GROUNDING RESULTS")
    print(f"{'=' * 60}")
    print(f"Grounding score: {grounded.grounding_score:.2f}")
    print(f"Citations used: {len(grounded.citations_used)} / {len(grounded.citations_available)}")
    print(f"Ungrounded claims: {len(grounded.ungrounded_claims)}")
    if grounded.ungrounded_claims:
        print(f"  Values: {', '.join(grounded.ungrounded_claims[:10])}")

    # 5. Show raw content
    print(f"\n{'=' * 60}")
    print("RAW LLM OUTPUT")
    print(f"{'=' * 60}")
    print(grounded.content)

    # 6. Try to parse as JSON
    print(f"\n{'=' * 60}")
    print("JSON PARSE CHECK")
    print(f"{'=' * 60}")
    try:
        parsed = json.loads(grounded.content)
        print("JSON parsed successfully!")
        for key in ("headline", "narrative", "key_risks", "outlook"):
            if key in parsed:
                print(f"  {key}: present")
            else:
                print(f"  {key}: MISSING")
    except json.JSONDecodeError as e:
        print(f"JSON parse FAILED: {e}")
        # Try to extract JSON from markdown code block
        import re

        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", grounded.content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                print("  (extracted from markdown code block)")
            except json.JSONDecodeError:
                print("  (could not extract from markdown either)")

    await provider.close()

    # 7. Verdict
    print(f"\n{'=' * 60}")
    passed = grounded.grounding_score >= 0.5  # lenient for first run
    if passed:
        print("SMOKE TEST: PASS (grounding >= 0.5)")
    else:
        print("SMOKE TEST: FAIL (grounding < 0.5)")
    print(f"{'=' * 60}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
