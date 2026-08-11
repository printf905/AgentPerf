from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ComparisonVerdict = Literal[
    "ACCEPT",
    "REJECT_QUALITY_REGRESSION",
    "NO_MATERIAL_CHANGE",
    "INCONCLUSIVE",
    "REGRESSION",
]
FindingLifecycleStatus = Literal[
    "RESOLVED",
    "IMPROVED",
    "PERSISTENT",
    "REGRESSED",
    "NEW",
]


@dataclass(frozen=True)
class MetricDelta:
    baseline: float | int | None
    candidate: float | int | None
    delta: float | int | None
    percent_delta: float | None
    measurement_quality: str = "DERIVED"


@dataclass(frozen=True)
class ComponentAccountingSummary:
    total_processed_tokens: MetricDelta
    total_unique_tokens: MetricDelta
    other_processed_tokens: MetricDelta
    attribution_coverage_ratio: MetricDelta
    baseline_confidence: str = "UNAVAILABLE"
    candidate_confidence: str = "UNAVAILABLE"
    source: str = "component"


@dataclass(frozen=True)
class TokenDelta:
    input_tokens: MetricDelta
    output_tokens: MetricDelta
    component_processed_tokens: dict[str, MetricDelta] = field(default_factory=dict)
    component_accounting: ComponentAccountingSummary | None = None


@dataclass(frozen=True)
class ContextGrowthDelta:
    final_step_input_tokens: MetricDelta
    max_step_input_tokens: MetricDelta
    growth_slope_tokens_per_step: MetricDelta
    baseline_steps: int
    candidate_steps: int


@dataclass(frozen=True)
class LatencyDelta:
    tool_latency_ms: MetricDelta
    queue_p50_ms: MetricDelta
    queue_p95_ms: MetricDelta
    scheduled_to_first_p50_ms: MetricDelta
    scheduled_to_first_p95_ms: MetricDelta
    generation_p50_ms: MetricDelta
    generation_p95_ms: MetricDelta
    client_p50_ms: MetricDelta
    client_p95_ms: MetricDelta


@dataclass(frozen=True)
class CacheDelta:
    cached_tokens: MetricDelta
    cache_miss_tokens: MetricDelta
    cached_token_ratio: MetricDelta


@dataclass(frozen=True)
class QualityDelta:
    mean_score: MetricDelta
    pass_rate: MetricDelta
    baseline_tasks_with_quality: int
    candidate_tasks_with_quality: int
    mean_score_tolerance: float | None
    pass_rate_tolerance: float | None
    passed: bool | None


@dataclass(frozen=True)
class FindingChange:
    finding_id: str
    lifecycle: FindingLifecycleStatus
    baseline_severity: str | None
    candidate_severity: str | None
    baseline_materiality: str | None = None
    candidate_materiality: str | None = None
    scope: str | None = None
    baseline_summary: str | None = None
    candidate_summary: str | None = None


@dataclass(frozen=True)
class AcceptanceResult:
    verdict: ComparisonVerdict
    reason: str
    performance_improved: bool
    quality_passed: bool | None
    material_regression: bool


@dataclass(frozen=True)
class RunComparison:
    baseline_id: str
    candidate_id: str
    matched_tasks: list[str]
    unmatched_baseline_tasks: list[str]
    unmatched_candidate_tasks: list[str]
    token_deltas: TokenDelta
    context_growth_delta: ContextGrowthDelta
    latency_deltas: LatencyDelta
    cache_deltas: CacheDelta
    quality_deltas: QualityDelta
    finding_changes: list[FindingChange]
    acceptance_result: AcceptanceResult
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
