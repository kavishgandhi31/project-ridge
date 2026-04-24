"""Domain types -- pure Pydantic models with zero I/O.

These are the canonical shapes every other layer reads and writes.
Adapters normalize into these; scoring, quality, alerting, and API
layers consume them. Keeping this package free of side effects (no DB,
no HTTP, no filesystem) is non-negotiable -- it's what makes the
rest of the codebase testable.
"""

from ridge.alerts.config import AlertConfig
from ridge.domain.alerting import (
    AlertTier,
    Digest,
    DigestSummary,
    DispatchResult,
    TierAssignment,
    tier_rank,
)
from ridge.domain.event import EventRecord
from ridge.domain.llm import (
    Citation,
    EvalQuestion,
    EvalResult,
    GroundedContext,
    GroundedResponse,
    LLMRequest,
    LLMResponse,
    TaskType,
)
from ridge.domain.observation import Frequency, Observation
from ridge.domain.pipeline import PipelineRun, RunStatus, RunType
from ridge.domain.scoring import (
    ALL_DIMENSIONS,
    DimensionName,
    DimensionScore,
    NewsHeat,
    ScoreResult,
    ScoringConfig,
)
from ridge.domain.source import (
    CountrySpec,
    FetchRequest,
    IndicatorSpec,
    SourceIndicatorSpec,
    SourceManifest,
)
from ridge.quality.config import QualityConfig
from ridge.quality.issue import IssueSeverity, QualityIssue

__all__ = [
    "ALL_DIMENSIONS",
    "AlertConfig",
    "AlertTier",
    "Citation",
    "CountrySpec",
    "Digest",
    "DigestSummary",
    "DimensionName",
    "DimensionScore",
    "DispatchResult",
    "EvalQuestion",
    "EvalResult",
    "EventRecord",
    "FetchRequest",
    "Frequency",
    "GroundedContext",
    "GroundedResponse",
    "IndicatorSpec",
    "IssueSeverity",
    "LLMRequest",
    "LLMResponse",
    "NewsHeat",
    "Observation",
    "PipelineRun",
    "QualityConfig",
    "QualityIssue",
    "RunStatus",
    "RunType",
    "ScoreResult",
    "ScoringConfig",
    "SourceIndicatorSpec",
    "SourceManifest",
    "TaskType",
    "TierAssignment",
    "tier_rank",
]
