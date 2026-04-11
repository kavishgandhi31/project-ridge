"""Source metadata types — what a source exposes and how to request from it."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field

from hornet.domain.observation import Frequency


class IndicatorSpec(BaseModel):
    """One indicator a source currently exposes.

    Returned (as part of a SourceManifest) by SourceAdapter.discover().
    This is how we avoid hardcoding indicator lists in YAML: the adapter
    tells us at runtime what it knows about, we store it, and we diff
    against yesterday to detect new or removed series.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    indicator_code: str = Field(
        ...,
        description="Canonical indicator code this source provides data for.",
    )
    source_native_code: str = Field(
        ...,
        description="The source's own ID for this series (e.g. 'FPCPITOTLZGNGA' for FRED).",
    )
    frequency: Frequency = Field(
        ...,
        description="Native frequency of this series from this source.",
    )
    countries_iso3: frozenset[str] = Field(
        ...,
        description="Countries this source has data for on this indicator.",
    )
    name: str | None = Field(
        default=None,
        description="Human-readable name, if the source provides one.",
    )
    unit: str | None = Field(
        default=None,
        description="Unit of measure, if the source provides one.",
    )


class SourceManifest(BaseModel):
    """Runtime snapshot of what a source exposes. Returned by discover().

    Diffing today's manifest against yesterday's is how we detect:
    - new series the source started publishing (potential new signal)
    - series the source stopped publishing (potential data problem)
    - countries added or removed from coverage
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    indicators: tuple[IndicatorSpec, ...]
    discovered_at: datetime.datetime = Field(
        ...,
        description="When this manifest was generated.",
    )


class FetchRequest(BaseModel):
    """A request to pull observations from a source.

    Empty sets mean 'everything the source supports' — the adapter is
    responsible for enumerating via its own manifest. This lets the
    orchestrator hand off a high-level request without having to know
    each source's coverage up front.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    countries_iso3: frozenset[str] = Field(
        default_factory=frozenset,
        description="ISO3 country filter. Empty = all countries the source covers.",
    )
    indicator_codes: frozenset[str] = Field(
        default_factory=frozenset,
        description="Indicator filter. Empty = all indicators the source covers.",
    )
    start: datetime.date | None = Field(
        default=None,
        description="Earliest observation date to fetch. None = source default.",
    )
    end: datetime.date | None = Field(
        default=None,
        description="Latest observation date to fetch. None = source default (usually today).",
    )
