from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ARTIFACT_SCHEMA_VERSION = 1

MetricDirection = Literal["higher_is_better", "lower_is_better", "neutral"]


@dataclass(frozen=True)
class ArtifactLocation:
    trace: str = "trace.json"
    tasks: str = "tasks.json"
    quality: str = "quality.json"
    findings: str = "findings.json"
    environment: str = "environment.json"
    summary: str = "summary.json"


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_schema_version: int
    artifact_id: str
    created_at: str
    agentperf_version: str
    workload_id: str | None = None
    framework: str | None = None
    agent_name: str | None = None
    backend: str | None = None
    model: str | None = None
    task_count: int | None = None
    serving_telemetry: bool = False
    locations: ArtifactLocation = field(default_factory=ArtifactLocation)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityMetric:
    name: str
    value: float | bool | str
    direction: MetricDirection = "higher_is_better"
    aggregation: str = "mean"
    tolerance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    execution_id: str | None = None
    passed: bool | None = None
    quality_score: float | None = None
    evaluator: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: float | None = None
    agent_run_ids: list[str] = field(default_factory=list)
    quality_metrics: list[QualityMetric] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
