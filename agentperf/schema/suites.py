from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SUITE_SCHEMA_VERSION = 1

SuiteStatus = Literal["PASS", "FAIL", "INCONCLUSIVE"]


@dataclass(frozen=True)
class TaskSetSpec:
    task_set_id: str | None = None
    fingerprint: str | None = None


@dataclass(frozen=True)
class SuiteEnvironmentPolicy:
    latency_requires_compatible: bool = True
    allow_environment_mismatch: bool = False


@dataclass(frozen=True)
class SuiteManifest:
    schema_version: int
    suite_id: str
    suite_version: int
    baseline_artifact: str
    regression_policy: str
    description: str | None = None
    agent: str | None = None
    framework: str | None = None
    task_set: TaskSetSpec = field(default_factory=TaskSetSpec)
    expected_task_count: int | None = None
    quality_metrics: list[str] = field(default_factory=list)
    environment: SuiteEnvironmentPolicy = field(default_factory=SuiteEnvironmentPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)
