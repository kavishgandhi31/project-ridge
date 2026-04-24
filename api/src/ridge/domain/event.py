"""The canonical EventRecord type -- one news/sentiment data point.

EventRecord is the parallel domain type to Observation, introduced
for GDELT and GoogleNews data that does not fit the numeric
``(country, indicator, date, float)`` shape of Observation.

Three event_type values are expected in Phase 2:

* ``"tone"`` -- daily average news sentiment for a country (GDELT).
  ``value`` is the tone score (-100 to +100), no title/url.
* ``"volume"`` -- daily article count for a country (GDELT).
  ``value`` is the count, no title/url.
* ``"headline"`` -- individual article metadata (GDELT + GoogleNews).
  ``title``, ``url`` are populated; ``value`` may hold per-article
  tone (GDELT) or be None (GoogleNews). ``metadata`` carries
  source_name, image_url, etc.

EventRecords are immutable (frozen) and append-only, same as
Observations. Deduplication is via ``dedup_key`` -- a computed
string the adapter builds from the event's natural identity:

* Aggregated signals: ``"{source_id}:{event_type}:{country_iso3}:{date}"``
* Headlines: ``"{source_id}:headline:{md5(url)}"``

The database enforces uniqueness on ``(date, dedup_key)`` via the
composite primary key on the ``event_record`` hypertable.
"""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventRecord(BaseModel):
    """A single news/sentiment data point, normalized across event sources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    country_iso3: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 3166-1 alpha-3 country code, uppercase.",
    )
    source_id: str = Field(
        ...,
        min_length=1,
        description="The source that produced this event (e.g. 'gdelt', 'googlenews').",
    )
    event_type: str = Field(
        ...,
        min_length=1,
        description="Event category: 'tone', 'volume', or 'headline'.",
    )
    date: datetime.date = Field(
        ...,
        description="The date the event refers to.",
    )
    dedup_key: str = Field(
        ...,
        min_length=1,
        description=(
            "Application-computed deduplication key. Unique per event. "
            "Used as part of the composite PK for idempotent inserts."
        ),
    )
    value: float | None = Field(
        default=None,
        description="Numeric value: tone score, article count, or per-article tone. None for text-only events.",
    )
    title: str | None = Field(
        default=None,
        description="Article headline text. None for aggregated signals.",
    )
    url: str | None = Field(
        default=None,
        description="Article URL. None for aggregated signals.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Extensible metadata bag (stored as JSONB). Carries source_name, "
            "image_url, per-article tone breakdown, etc. Empty dict for "
            "aggregated signals that have no extra metadata."
        ),
    )
    ingested_at: datetime.datetime = Field(
        ...,
        description="When Ridge pulled this event from the source.",
    )

    @field_validator("country_iso3", mode="before")
    @classmethod
    def _uppercase_iso3(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v
