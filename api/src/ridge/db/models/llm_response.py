"""LLMResponseRow -- the SQLAlchemy storage mirror of GroundedResponse.

Persists every LLM generation with its citations, grounding score,
and provider metadata. This is the audit trail that proves every
number in a narrative traces back to a real observation.

Regular table (not hypertable) -- volume is low (~183 countries/day
for narratives, ~0-10/day for ESCALATE rationales).
"""

from __future__ import annotations

import datetime
import hashlib
from typing import Any

from sqlalchemy import Double, Index, Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from ridge.db.base import Base
from ridge.domain.llm import Citation, GroundedResponse, TaskType


def deterministic_response_id(run_id: str, country_iso3: str, template_name: str) -> str:
    """Stable hash of the natural key so upsert ON CONFLICT actually fires."""
    key = f"{run_id}:{country_iso3}:{template_name}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


class LLMResponseRow(Base):
    """SQLAlchemy ORM row for the ``llm_response`` table.

    Stores the full LLM output, extracted citations (JSONB), grounding
    score, and provider/template metadata. One row per generation.
    """

    __tablename__ = "llm_response"

    response_id: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    country_iso3: Mapped[str] = mapped_column(String(3), nullable=False)
    template_name: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_used: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    citations_available_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ungrounded_claims: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    grounding_score: Mapped[float] = mapped_column(Double, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("response_id", name="llm_response_pk"),
        Index("llm_response_run_idx", "run_id"),
        Index("llm_response_country_idx", "country_iso3", "generated_at"),
        Index("llm_response_template_idx", "template_name"),
    )

    @classmethod
    def from_domain(cls, response: GroundedResponse) -> LLMResponseRow:
        """Construct a storage row from a GroundedResponse."""
        citations_json = [
            {
                "ref_number": c.ref_number,
                "country_iso3": c.country_iso3,
                "indicator_code": c.indicator_code,
                "source_id": c.source_id,
                "date": c.date.isoformat(),
                "value": c.value,
                "vintage": c.vintage.isoformat(),
                "display_label": c.display_label,
            }
            for c in response.citations_used
        ]

        return cls(
            response_id=deterministic_response_id(
                response.run_id, response.country_iso3, response.template_name
            ),
            run_id=response.run_id,
            country_iso3=response.country_iso3,
            template_name=response.template_name,
            task_type=response.task_type.value,
            provider_id=response.provider_id,
            model_id=response.model_id,
            content=response.content,
            citations_used=citations_json,
            citations_available_count=len(response.citations_available),
            ungrounded_claims=list(response.ungrounded_claims),
            grounding_score=response.grounding_score,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            latency_ms=response.latency_ms,
            generated_at=response.generated_at,
        )

    def to_domain(self) -> GroundedResponse:
        """Reconstruct a GroundedResponse. Lossy on citations_available (not stored)."""
        citations = tuple(
            Citation(
                ref_number=c["ref_number"],
                country_iso3=c["country_iso3"],
                indicator_code=c["indicator_code"],
                source_id=c["source_id"],
                date=datetime.date.fromisoformat(c["date"]),
                value=c["value"],
                vintage=datetime.datetime.fromisoformat(c["vintage"]),
                display_label=c["display_label"],
            )
            for c in self.citations_used
        )
        return GroundedResponse(
            content=self.content,
            citations_used=citations,
            citations_available=citations,
            ungrounded_claims=tuple(self.ungrounded_claims),
            grounding_score=self.grounding_score,
            provider_id=self.provider_id,
            model_id=self.model_id,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            latency_ms=self.latency_ms,
            task_type=TaskType(self.task_type),
            template_name=self.template_name,
            country_iso3=self.country_iso3,
            run_id=self.run_id,
            generated_at=self.generated_at,
        )
