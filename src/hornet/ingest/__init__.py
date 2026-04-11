"""Ingest orchestration — calls SourceAdapters and persists Observations.

Phase 1: minimal one-adapter runner. Phase 4 will add quality hooks,
Phase 5 will add multi-source pipeline staging. For now this module
exists to keep the adapter code separate from storage concerns.
"""

from hornet.ingest.runner import IngestResult, run_ingest

__all__ = ["IngestResult", "run_ingest"]
