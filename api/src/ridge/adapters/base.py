"""SourceAdapter protocol — the contract every data source must satisfy."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ridge.domain.event import EventRecord
from ridge.domain.observation import Observation
from ridge.domain.source import FetchRequest, SourceManifest


class HealthReport(BaseModel):
    """Operational status of a source adapter.

    Returned by ``SourceAdapter.health()``. Populated by the monitoring
    layer into a dashboard view so failing sources are visible before
    they corrupt downstream scoring.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    healthy: bool
    latency_ms: int | None = Field(
        default=None,
        description="Round-trip time of the last successful probe.",
    )
    last_success_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent successful fetch.",
    )
    last_error: str | None = Field(
        default=None,
        description="Human-readable description of the most recent error, if any.",
    )


@runtime_checkable
class SourceAdapter(Protocol):
    """The contract every data source must implement.

    Three methods:

    * ``discover()`` returns a SourceManifest describing what the source
      currently exposes (which indicators, which countries, at what
      frequency). Called on a schedule — nightly for most sources —
      so new or removed series surface automatically without a config
      change.

    * ``fetch(request)`` returns a list of canonical Observations for
      the requested scope. Returning a list (rather than an async
      iterator) keeps the contract simple; source pagination and
      retries are the adapter's private concern.

    * ``health()`` returns a HealthReport for the monitoring layer.

    Concrete adapters will subclass a shared BaseClient (ported from v1)
    that provides rate limiting, retries, a circuit breaker, and an
    HTTP session. This protocol only specifies the public surface —
    implementation details are deliberately not constrained.
    """

    source_id: str

    async def discover(self) -> SourceManifest: ...

    async def fetch(self, request: FetchRequest) -> list[Observation]: ...

    async def health(self) -> HealthReport: ...

    async def close(self) -> None: ...


@runtime_checkable
class EventSourceAdapter(Protocol):
    """Contract for event/news sources that produce EventRecords.

    Parallel to SourceAdapter but returns EventRecord instead of
    Observation. Used by GDELT and GoogleNews.

    No ``discover()`` -- event sources do not expose a manifest of
    indicators. Their configuration comes from the source_indicator
    registry the same way numeric adapters work, but the
    ``indicator_code`` field carries the event_type (tone, volume,
    headline) rather than a canonical macro indicator.
    """

    source_id: str

    async def fetch_events(self, request: FetchRequest) -> list[EventRecord]: ...

    async def health(self) -> HealthReport: ...

    async def close(self) -> None: ...
