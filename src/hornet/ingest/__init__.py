"""Ingest orchestration -- calls SourceAdapters and persists Observations.

Three discrete responsibilities:

* ``runner`` -- takes a constructed adapter and persists its output.
* ``factory`` -- builds adapters from the DB-backed registry. Handles
  credential lookup and repo queries so the runner stays storage-only.
* (future) a CLI entrypoint that wires them together.

Phase 1 shipped only ``runner``. Phase 2 adds ``factory`` so adapters
no longer carry hardcoded indicator dicts.
"""

from hornet.ingest.factory import (
    MissingCredentialError,
    build_fred_adapter,
    build_worldbank_adapter,
    build_yfinance_adapter,
)
from hornet.ingest.runner import IngestResult, run_ingest

__all__ = [
    "IngestResult",
    "MissingCredentialError",
    "build_fred_adapter",
    "build_worldbank_adapter",
    "build_yfinance_adapter",
    "run_ingest",
]
