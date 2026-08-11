from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RegressionStatus = Literal["PASS", "FAIL", "INCONCLUSIVE"]
CheckCategory = Literal[
    "TASK_COVERAGE",
    "QUALITY",
    "PERFORMANCE",
    "FINDINGS",
    "ARTIFACT",
    "ENVIRONMENT",
]


@dataclass(frozen=True)
class QualityMetricPolicy:
    max_drop: float | None = None


@dataclass(frozen=True)
class PerformanceMetricPolicy:
    max_increase_percent: float | None = None
    max_increase_absolute: float | None = None
    min_attribution_coverage: float | None = None
    require_attribution_confidence: str | None = None


@dataclass(frozen=True)
class FindingPolicy:
    fail_on_new_material_findings: bool = False
    fail_on_regressed_material_findings: bool = False


@dataclass(frozen=True)
class TaskCoveragePolicy:
    require_same_tasks: bool = False
    minimum_task_coverage: float | None = None
    allow_partial: bool = False


@dataclass(frozen=True)
class RegressionPolicy:
    schema_version: int = 1
    quality: dict[str, QualityMetricPolicy] = field(default_factory=dict)
    performance: dict[str, PerformanceMetricPolicy] = field(default_factory=dict)
    findings: FindingPolicy = field(default_factory=FindingPolicy)
    task_coverage: TaskCoveragePolicy = field(default_factory=TaskCoveragePolicy)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegressionCheck:
    category: CheckCategory
    metric: str
    result: RegressionStatus
    baseline: float | int | str | None = None
    candidate: float | int | str | None = None
    allowed: float | int | str | None = None
    actual_delta: float | int | None = None
    actual_percent_delta: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegressionResult:
    status: RegressionStatus
    checks: list[RegressionCheck]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
