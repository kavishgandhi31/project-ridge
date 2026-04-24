"""The canonical Observation type — one macro data point, normalized."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Frequency = Literal["daily", "weekly", "monthly", "quarterly", "annual", "forecast"]
"""Observation frequency tier.

Matches v1's frequency set so the scoring engine can be ported without
semantic changes. "forecast" is not strictly a frequency — it's a semantic
tag for WEO-style forward-looking estimates that the scorer weights
differently from actuals. We inherit v1's conflation intentionally:
changing it would force scoring-math changes, which we don't want during
migration.
"""


class Observation(BaseModel):
    """A single macro data point, normalized across all sources.

    Every source adapter converts its native response (FRED JSON, yfinance
    DataFrame, WorldBank bulk JSON, BIS CSV, etc.) into a stream of these
    before data touches any downstream code. Once an Observation exists,
    the code consuming it doesn't need to know or care which source it
    came from — everything downstream (scoring, quality, API, LLM grounding)
    reads the same shape.

    Observations are immutable (frozen) and append-only. To correct a value,
    write a new Observation with a later ``vintage``; never mutate. This is
    what makes replaying history as-of any past date trivially correct, and
    what lets us detect silent revisions from sources like FRED.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 3166-1 alpha-3 country code, uppercase (e.g. NGA, BRA).",
    )
    indicator_code: str = Field(
        ...,
        min_length=1,
        description=(
            "Canonical indicator code (e.g. CPI_YOY, POLICY_RATE, CA_GDP). "
            "Source-agnostic — the mapping from a source's native code to "
            "this canonical code lives in the SourceIndicator table."
        ),
    )
    source_id: str = Field(
        ...,
        min_length=1,
        description="The source that produced this observation (e.g. 'fred', 'worldbank').",
    )
    date: datetime.date = Field(
        ...,
        description="The date the observation refers to — NOT when it was ingested.",
    )
    value: float = Field(
        ...,
        description="The numeric value. Units are defined by the indicator's metadata.",
    )
    frequency: Frequency = Field(
        ...,
        description="Observation frequency tier. Used by the scoring engine to weight tiers.",
    )
    vintage: datetime.datetime = Field(
        ...,
        description=(
            "When the source published THIS specific value. Distinct from "
            "ingested_at. Two observations with the same (country, indicator, "
            "date) but different vintages represent a source revision — the "
            "later vintage is the corrected value, the earlier is what was "
            "originally published. This is how we detect FRED silent revisions."
        ),
    )
    ingested_at: datetime.datetime = Field(
        ...,
        description="When Ridge pulled this value from the source.",
    )
    quality_flags: tuple[str, ...] = Field(
        default=(),
        description=(
            "Tags set by the quality layer (e.g. 'outlier_4sigma', 'flatline', "
            "'revision_detected'). Empty tuple when the observation is clean. "
            "Tuple (not list) because observations are immutable."
        ),
    )

    @field_validator("country_iso3", mode="before")
    @classmethod
    def _uppercase_iso3(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v
