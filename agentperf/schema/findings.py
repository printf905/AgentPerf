from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["LOW", "MEDIUM", "HIGH"]
Confidence = Literal["LOW", "MEDIUM", "HIGH"]
RecommendationApplicability = Literal[
    "OBSERVATION_ONLY",
    "CONDITIONAL",
    "INVESTIGATE",
    "ACTIONABLE",
]
ExpectedMetricDirection = Literal[
    "DECREASE",
    "INCREASE",
    "NO_REGRESSION",
    "RESOLVE_OR_IMPROVE_FINDING",
]


@dataclass(frozen=True)
class ExpectedMetricChange:
    metric: str
    direction: ExpectedMetricDirection
    required: bool = True
    rationale: str = ""


@dataclass(frozen=True)
class RecommendationContract:
    objective: str
    applicability: RecommendationApplicability
    interventions: list[str] = field(default_factory=list)
    expected_metric_changes: list[ExpectedMetricChange] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    verification_requirements: list[str] = field(default_factory=list)
    quality_requirement: str | None = "within_configured_tolerance"
    evidence_level: Confidence | None = None
    schema_version: int = 1


@dataclass(frozen=True)
class FindingProvenance:
    agent_span_ids: list[str] = field(default_factory=list)
    llm_call_ids: list[str] = field(default_factory=list)
    llm_request_ids: list[str] = field(default_factory=list)
    serving_request_ids: list[str] = field(default_factory=list)
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    derived_metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    id: str
    severity: Severity
    title: str
    summary: str
    evidence: dict[str, Any]
    affected_spans: list[str]
    recommendation: str
    confidence: Confidence
    validation_plan: list[str] = field(default_factory=list)
    provenance: FindingProvenance = field(default_factory=FindingProvenance)
    recommendation_contract: RecommendationContract | None = None
