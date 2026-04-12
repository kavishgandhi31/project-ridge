"""Read-side repository functions over the registry tables.

Repos are thin, typed query functions — no caching, no business logic,
just ``(session, args) -> domain objects``. They exist so callers
(adapters, ingest runner, API handlers) don't write raw SQLAlchemy
statements at every use site and stay testable against in-memory
domain objects instead of an actual DB.

One module per table. Async functions only.
"""

from hornet.db.repos.country import (
    list_countries,
    load_iso2_to_iso3_map,
)
from hornet.db.repos.source_indicator import (
    list_source_indicators,
)

__all__ = [
    "list_countries",
    "list_source_indicators",
    "load_iso2_to_iso3_map",
]
