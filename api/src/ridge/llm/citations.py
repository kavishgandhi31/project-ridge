"""Citation extraction and grounding validation.

After the LLM generates a response, this module:

1. Extracts [N] reference markers from the output text.
2. Resolves each marker to a Citation from the context's lookup table.
3. Detects ungrounded numeric claims -- numbers in the output that
   do NOT have an associated citation marker nearby.
4. Computes a grounding score: cited_claims / (cited_claims + ungrounded).

The ungrounded-claim detector uses regex to find numeric patterns
(percentages, decimals, signed numbers) while filtering out:
- Year references (2020-2030)
- The citation markers themselves ([1], [2])
- Ordinals (1st, 2nd, 3rd)
- Common non-data numbers (e.g. "four dimensions")

This is inherently heuristic -- the eval harness measures how well
it works in practice and flags false positives/negatives.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import structlog

from ridge.domain.llm import Citation, GroundedResponse, LLMResponse, TaskType

logger = structlog.get_logger(__name__)

# Matches [N] where N is one or more digits
_CITATION_RE = re.compile(r"\[(\d+)\]")

# Matches numeric values that might be data claims:
#   - Percentages: 33.2%, -1.5%
#   - Decimals with sign: +2.1, -0.5
#   - Plain decimals: 3.14, 0.5
#   - Large numbers: 1,234 or 1234.5
# But NOT:
#   - Years: 2020, 2025, 2026 (4-digit numbers between 1900-2099)
#   - Citation markers: [1], [2] (handled separately)
#   - Ordinals: 1st, 2nd, 3rd, 4th
#   - Section numbers: "Section 2", "Step 3"
_NUMERIC_CLAIM_RE = re.compile(
    r"(?<!\[)"  # not preceded by [
    r"[+-]?"  # optional sign
    r"\d[\d,]*"  # digits with optional commas
    r"(?:\.\d+)?"  # optional decimal
    r"%?"  # optional percent
    r"(?!\])"  # not followed by ]
    r"(?!(?:st|nd|rd|th)\b)"  # not an ordinal
)

# Years pattern -- 4-digit numbers in 1900-2099 range
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Numbers that are clearly not data claims
_NON_DATA_NUMBERS = frozenset(
    {
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "100",
    }
)


def extract_citation_refs(text: str) -> tuple[int, ...]:
    """Extract all [N] citation reference numbers from text.

    Returns a tuple of unique ref numbers in the order they first
    appear. Duplicates are removed (a citation referenced twice
    still counts as one citation used).
    """
    seen: set[int] = set()
    refs: list[int] = []
    for match in _CITATION_RE.finditer(text):
        ref = int(match.group(1))
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return tuple(refs)


def resolve_citations(
    ref_numbers: Sequence[int],
    citation_table: Mapping[int, Citation],
) -> tuple[tuple[Citation, ...], tuple[int, ...]]:
    """Resolve ref numbers to Citations from the lookup table.

    Returns:
    - resolved: Citations that were found in the table.
    - unresolved: Ref numbers with no matching Citation (possible
      hallucinated references).
    """
    resolved: list[Citation] = []
    unresolved: list[int] = []
    for ref in ref_numbers:
        citation = citation_table.get(ref)
        if citation is not None:
            resolved.append(citation)
        else:
            unresolved.append(ref)
    return tuple(resolved), tuple(unresolved)


def detect_ungrounded_claims(
    text: str,
    cited_ref_numbers: frozenset[int],
    *,
    known_score_values: frozenset[float] = frozenset(),
) -> tuple[str, ...]:
    """Find numeric values in text that lack a nearby citation marker.

    A numeric claim is "grounded" if there is a [N] marker within
    a window of ~80 characters on either side of the number.
    Ungrounded claims are potential hallucinations.

    ``known_score_values`` are dimension/composite scores from the
    ScoreResult that appear in the context's score summary section.
    These are legitimate numbers the LLM may reference without a
    citation marker (they are structural metadata, not observation
    data). Pass them to suppress false positives.

    This is heuristic -- the eval harness measures precision/recall
    of this detector.
    """
    # Build a set of string representations of known score values
    # to match against detected claims (e.g. -2.10, -1.20)
    known_strs: frozenset[str] = frozenset(
        f"{v:.2f}".lstrip("+") for v in known_score_values
    ) | frozenset(f"{v:.1f}".lstrip("+") for v in known_score_values)

    claims: list[str] = []

    for match in _NUMERIC_CLAIM_RE.finditer(text):
        value_str = match.group(0).strip()

        # Skip small integers that are not data (list items, counts, etc.)
        clean_value = value_str.lstrip("+-").rstrip("%").replace(",", "")
        if clean_value in _NON_DATA_NUMBERS:
            continue

        # Skip years
        if _YEAR_RE.match(clean_value):
            continue

        # Skip if this number IS a citation marker (e.g. inside [N])
        start = match.start()
        if start > 0 and text[start - 1] == "[":
            continue

        # Skip known score values (dimension scores, composite)
        if value_str.lstrip("+-") in known_strs or value_str in known_strs:
            continue

        # Check if there is a citation marker within a window around the number
        window_start = max(0, start - 80)
        window_end = min(len(text), match.end() + 80)
        window = text[window_start:window_end]

        citation_in_window = _CITATION_RE.search(window)
        if citation_in_window is not None:
            # There is a citation nearby -- this claim is grounded
            continue

        claims.append(value_str)

    return tuple(claims)


def compute_grounding_score(
    n_cited: int,
    n_ungrounded: int,
) -> float:
    """Compute the grounding score: cited / (cited + ungrounded).

    Returns 1.0 if there are no numeric claims at all (vacuously
    grounded). Returns 0.0 if all claims are ungrounded.
    """
    total = n_cited + n_ungrounded
    if total == 0:
        return 1.0
    return n_cited / total


def validate_response(
    llm_response: LLMResponse,
    citations_available: tuple[Citation, ...],
    *,
    task_type: TaskType,
    template_name: str,
    country_iso3: str,
    run_id: str,
    known_score_values: frozenset[float] = frozenset(),
    min_grounding_score: float = 0.8,
) -> GroundedResponse:
    """Parse an LLM response and produce a grounded, validated result.

    This is the main entry point for citation validation. It:
    1. Extracts [N] markers from the response.
    2. Resolves them against the citation table.
    3. Detects ungrounded numeric claims.
    4. Computes the grounding score.
    5. Packages everything into a GroundedResponse.

    Parameters
    ----------
    llm_response:
        Raw response from the provider.
    citations_available:
        All citations that were in the context block.
    task_type:
        Task category (for metadata).
    template_name:
        Which template generated this.
    country_iso3:
        Target country.
    run_id:
        Pipeline run ID.
    """
    # Build citation lookup table
    citation_table: dict[int, Citation] = {c.ref_number: c for c in citations_available}

    # 1. Extract citation refs from output
    ref_numbers = extract_citation_refs(llm_response.content)

    # 2. Resolve to actual Citations
    citations_used, unresolved_refs = resolve_citations(ref_numbers, citation_table)

    if unresolved_refs:
        logger.warning(
            "citations.unresolved_refs",
            country=country_iso3,
            unresolved=unresolved_refs,
            template=template_name,
        )

    # 3. Detect ungrounded numeric claims
    cited_refs = frozenset(c.ref_number for c in citations_used)
    ungrounded_claims = detect_ungrounded_claims(
        llm_response.content,
        cited_refs,
        known_score_values=known_score_values,
    )

    # 4. Compute grounding score
    # "cited claims" = unique citations used (each citation grounds one number)
    grounding_score = compute_grounding_score(
        n_cited=len(citations_used),
        n_ungrounded=len(ungrounded_claims),
    )

    if grounding_score < min_grounding_score:
        logger.warning(
            "citations.low_grounding",
            country=country_iso3,
            score=grounding_score,
            n_cited=len(citations_used),
            n_ungrounded=len(ungrounded_claims),
            template=template_name,
        )

    return GroundedResponse(
        content=llm_response.content,
        citations_used=citations_used,
        citations_available=citations_available,
        ungrounded_claims=ungrounded_claims,
        grounding_score=grounding_score,
        provider_id=llm_response.provider_id,
        model_id=llm_response.model_id,
        tokens_in=llm_response.tokens_in,
        tokens_out=llm_response.tokens_out,
        latency_ms=llm_response.latency_ms,
        task_type=task_type,
        template_name=template_name,
        country_iso3=country_iso3,
        run_id=run_id,
        generated_at=llm_response.generated_at,
    )
