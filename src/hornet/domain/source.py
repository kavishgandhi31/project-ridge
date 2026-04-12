"""Source metadata types — what a source exposes and how to request from it."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class CountrySpec(BaseModel):
    """Country registry record — the authoritative identity of a country.

    Persisted in the ``country`` table. Every ISO3 code used anywhere in
    Hornet must resolve to a row in this table. This is what lets the
    WorldBank adapter map its native ISO2 responses to canonical ISO3,
    what lets Phase 3 scoring group by region, and what the Phase 6 LLM
    layer reads to produce country narratives.

    Kept minimal on purpose: Phase 2 only needs iso3, iso2, name. The
    region and income_group columns exist so later phases can populate
    them without a schema change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 3166-1 alpha-3 country code, uppercase. Primary identity.",
    )
    iso2: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code, uppercase. Unique per country.",
    )
    name: str = Field(
        ...,
        min_length=1,
        description="Human-readable country name in English.",
    )
    region: str | None = Field(
        default=None,
        description="World Bank region classification (e.g. 'Sub-Saharan Africa'). Optional.",
    )
    income_group: str | None = Field(
        default=None,
        description="World Bank income group (e.g. 'Upper middle income'). Optional.",
    )
    enabled: bool = Field(
        default=True,
        description="Soft disable flag. Disabled countries are ignored by adapters and scoring.",
    )
    notes: str | None = Field(
        default=None,
        description="Free-form operator notes. Not consumed by any code path.",
    )

    @field_validator("iso3", "iso2", mode="before")
    @classmethod
    def _uppercase_codes(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v


class SourceIndicatorSpec(BaseModel):
    """Registered mapping from a source's native series to a canonical indicator.

    Persisted in the ``source_indicator`` table. One row per
    (source_id, source_native_code) pair. Replaces the hardcoded
    ``_PILOT_SERIES`` / ``_INDICATORS`` dicts that Phase 1 shipped in
    the FRED and WorldBank adapters.

    The ``countries_iso3`` field captures the coverage shape: FRED-style
    sources have one country per row (the ISO3 is baked into the native
    code), WorldBank-style sources have all covered countries on one row
    (the native code applies globally). Both shapes coexist in the same
    table because both are legitimate — the adapter knows how to handle
    its own native code format.

    Separate from ``IndicatorSpec`` because that type lives inside a
    ``SourceManifest`` which is already scoped to one source; the DB
    table mixes all sources so it needs ``source_id`` explicitly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(
        ...,
        min_length=1,
        description="The source that exposes this series (e.g. 'fred', 'worldbank').",
    )
    source_native_code: str = Field(
        ...,
        min_length=1,
        description="The source's own identifier for this series.",
    )
    indicator_code: str = Field(
        ...,
        min_length=1,
        description="Canonical Hornet indicator code this series maps to.",
    )
    frequency: Frequency = Field(
        ...,
        description="Native frequency of the series as the source publishes it.",
    )
    countries_iso3: frozenset[str] = Field(
        ...,
        description=(
            "Set of ISO3 country codes this series covers. FRED-style sources "
            "typically have one country; WorldBank-style sources have many."
        ),
    )
    name: str | None = Field(
        default=None,
        description="Human-readable name if the source provides one.",
    )
    unit: str | None = Field(
        default=None,
        description="Unit of measure if the source provides one.",
    )
    enabled: bool = Field(
        default=True,
        description="Soft disable flag. Disabled series are skipped by discover() and fetch().",
    )
    notes: str | None = Field(
        default=None,
        description="Free-form operator notes. Not consumed by any code path.",
    )

    @field_validator("countries_iso3", mode="before")
    @classmethod
    def _uppercase_countries(cls, v: object) -> object:
        """Auto-uppercase ISO3 codes in countries_iso3.

        YAML authors may write lowercase; this normalizes before the
        frozenset is constructed so downstream lookups always match.
        """
        if isinstance(v, frozenset):
            return frozenset(s.upper() if isinstance(s, str) else s for s in v)
        if isinstance(v, list | set | tuple):
            return frozenset(s.upper() if isinstance(s, str) else s for s in v)
        return v

    def to_manifest_spec(self) -> IndicatorSpec:
        """Convert this registry record to the lighter manifest-shape IndicatorSpec.

        The manifest type omits ``source_id`` because a ``SourceManifest``
        is already scoped to one source.
        """
        return IndicatorSpec(
            indicator_code=self.indicator_code,
            source_native_code=self.source_native_code,
            frequency=self.frequency,
            countries_iso3=self.countries_iso3,
            name=self.name,
            unit=self.unit,
        )
