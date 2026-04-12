"""Domain types -- pure Pydantic models with zero I/O.

These are the canonical shapes every other layer reads and writes.
Adapters normalize into these; scoring, quality, alerting, and API
layers consume them. Keeping this package free of side effects (no DB,
no HTTP, no filesystem) is non-negotiable -- it's what makes the
rest of the codebase testable.
"""

from hornet.alerts.config import AlertConfig
from hornet.domain.alerting import (
    AlertTier,
    Digest,
    DigestSummary,
    DispatchResult,
    TierAssignment,
    tier_rank,
)
from hornet.domain.event import EventRecord
from hornet.domain.llm import (
    Citation,
    EvalQuestion,
    EvalResult,
    GroundedContext,
    GroundedResponse,
    LLMRequest,
    LLMResponse,
    TaskType,
)
from hornet.domain.observation import Frequency, Observation
from hornet.domain.pipeline import PipelineRun, RunStatus, RunType
from hornet.domain.scoring import (
    ALL_DIMENSIONS,
    DimensionName,
    DimensionScore,
    NewsHeat,
    ScoreResult,
    ScoringConfig,
)
from hornet.domain.source import (
    CountrySpec,
    FetchRequest,
    IndicatorSpec,
    SourceIndicatorSpec,
    SourceManifest,
)
from hornet.quality.config import QualityConfig
from hornet.quality.issue import IssueSeverity, QualityIssue

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
