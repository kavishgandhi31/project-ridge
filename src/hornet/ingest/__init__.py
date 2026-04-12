"""Ingest orchestration -- calls SourceAdapters and persists Observations."""

from hornet.ingest.factory import (
    MissingCredentialError,
    build_bis_adapter,
    build_fred_adapter,
    build_gdelt_adapter,
    build_imf_adapter,
    build_oecd_adapter,
    build_worldbank_adapter,
    build_yfinance_adapter,
)
from hornet.ingest.runner import EventIngestResult, IngestResult, run_event_ingest, run_ingest

__all__ = [
    "EventIngestResult",
    "IngestResult",
    "MissingCredentialError",
    "build_bis_adapter",
    "build_fred_adapter",
    "build_gdelt_adapter",
    "build_imf_adapter",
    "build_oecd_adapter",
    "build_worldbank_adapter",
    "build_yfinance_adapter",
    "run_event_ingest",
    "run_ingest",
]
