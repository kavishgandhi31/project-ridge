"""Domain types — pure Pydantic models with zero I/O.

These are the canonical shapes every other layer reads and writes.
Adapters normalize into these; scoring, quality, and API layers
consume them. Keeping this package free of side effects (no DB,
no HTTP, no filesystem) is non-negotiable — it's what makes the
rest of the codebase testable.
"""

from hornet.domain.observation import Frequency, Observation
from hornet.domain.source import FetchRequest, IndicatorSpec, SourceManifest

__all__ = [
    "FetchRequest",
    "Frequency",
    "IndicatorSpec",
    "Observation",
    "SourceManifest",
]
