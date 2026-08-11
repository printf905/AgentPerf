from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar, cast
from uuid import uuid4

from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact, load_artifact
from agentperf.instrumentation import TraceRecorder
from agentperf.schema.artifacts import ArtifactStatus, QualityMetric, TaskResult

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class QualityResult:
    score: float | None = None
    passed: bool | None = None
    metrics: list[QualityMetric] = field(default_factory=list)
    evaluator_name: str | None = None
    evaluator_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


Evaluator = Callable[[T, R], QualityResult]


class ExperimentSession(AbstractContextManager["ExperimentSession"]):
    """Lightweight experiment recorder that finalizes to an AgentPerf artifact.

    The session is intentionally not a workflow engine. It owns one
    ``TraceRecorder``, records task results and quality, runs current detectors at
    finalization, and writes a portable artifact directory.
    """

    def __init__(
        self,
        *,
        output_path: Path,
        artifact_id: str | None = None,
        workload_id: str | None = None,
        name: str | None = None,
        expected_task_count: int | None = None,
        framework: str | None = None,
        agent_name: str | None = None,
        backend: str | None = None,
        model: str | None = None,
        environment: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        recorder: TraceRecorder | None = None,
        mean_score_tolerance: float | None = None,
        pass_rate_tolerance: float | None = None,
    ) -> None:
        self.output_path = output_path
        self.artifact_id = artifact_id or f"artifact-{uuid4().hex}"
        self.workload_id = workload_id or self.artifact_id
        self.expected_task_count = expected_task_count
        self.framework = framework
        self.agent_name = agent_name or name
        self.backend = backend
        self.model = model
        self.environment = environment or {}
        self.metadata = metadata or {}
        self.mean_score_tolerance = mean_score_tolerance
        self.pass_rate_tolerance = pass_rate_tolerance
        self.recorder = recorder or TraceRecorder(
            agent_run_id=self.workload_id,
            name=name,
            metadata={
                "workload_id": self.workload_id,
                "framework": framework,
                "backend": backend,
                "model": model,
                **self.metadata,
            },
        )
        self._task_results: list[TaskResult] = []
        self._started_at = time.perf_counter()
        self._finished = False
        self._recording_context: Any | None = None
        self._status = "PARTIAL"

    def __enter__(self) -> ExperimentSession:
        self._recording_context = self.recorder.as_current()
        self._recording_context.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._recording_context is not None:
            self._recording_context.__exit__(exc_type, exc, traceback)
            self._recording_context = None
        self.finalize(status="FAILED" if exc is not None else None)
        return None

    def run_task(
        self,
        task_id: str,
        task_input: T,
        func: Callable[[T], R],
        *,
        evaluator: Evaluator[T, R] | None = None,
        execution_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        reraise: bool = True,
    ) -> R | None:
        started = time.perf_counter()
        try:
            result = func(task_input)
        except Exception as exc:
            self.record_task_result(
                task_id=task_id,
                execution_id=execution_id,
                passed=False,
                duration_ms=_elapsed_ms(started),
                client_latency_ms=_elapsed_ms(started),
                error=f"{type(exc).__name__}: {exc}",
                status="FAILED",
                metadata=metadata,
            )
            if reraise:
                raise
            return None
        quality = evaluator(task_input, result) if evaluator else None
        self.record_task_result(
            task_id=task_id,
            execution_id=execution_id,
            passed=quality.passed if quality else None,
            quality_score=quality.score if quality else None,
            quality_metrics=quality.metrics if quality else None,
            evaluator=_evaluator_label(quality),
            duration_ms=_elapsed_ms(started),
            client_latency_ms=_elapsed_ms(started),
            status="COMPLETE",
            metadata={**(metadata or {}), **(quality.metadata if quality else {})},
        )
        return result

    def record_task_result(
        self,
        *,
        task_id: str,
        execution_id: str | None = None,
        passed: bool | None = None,
        quality_score: float | None = None,
        quality_metrics: list[QualityMetric] | None = None,
        evaluator: str | None = None,
        duration_ms: float | None = None,
        client_latency_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskResult:
        result = TaskResult(
            task_id=task_id,
            execution_id=execution_id,
            passed=passed,
            quality_score=quality_score,
            evaluator=evaluator,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            client_latency_ms=client_latency_ms,
            error=error,
            status=status,
            agent_run_ids=[self.recorder.agent_run_id],
            quality_metrics=quality_metrics or [],
            metadata=metadata or {},
        )
        self._task_results.append(result)
        return result

    def finalize(self, *, status: str | None = None) -> ExperimentArtifact:
        if self._finished:
            return load_artifact(self.output_path)
        run = self.recorder.finish()
        report = analyze_run(run)
        resolved_status = status or self._infer_status()
        if resolved_status not in {"COMPLETE", "PARTIAL", "FAILED"}:
            raise ValueError("experiment status must be COMPLETE, PARTIAL, or FAILED")
        quality_metrics = self._aggregate_quality_metrics()
        environment = {
            **_safe_environment_metadata(),
            **self.environment,
        }
        summary = {
            "workload_id": self.workload_id,
            "status": resolved_status,
            "expected_task_count": self.expected_task_count,
            "recorded_task_count": len(self._task_results),
            "llm_calls": len(run.llm_calls),
            "tool_calls": len(run.tool_calls),
            "input_tokens": sum(call.input_tokens or 0 for call in run.llm_calls),
            "output_tokens": sum(call.output_tokens or 0 for call in run.llm_calls),
            "duration_ms": _elapsed_ms(self._started_at),
            "findings": [finding.id for finding in report.findings],
        }
        artifact = ExperimentArtifact.from_analysis(
            report,
            artifact_id=self.artifact_id,
            workload_id=self.workload_id,
            task_results=self._task_results,
            task_count=self.expected_task_count or len(self._task_results),
            quality_metrics=quality_metrics,
            environment=environment,
            summary=summary,
            framework=self.framework,
            agent_name=self.agent_name,
            backend=self.backend,
            model=self.model,
            serving_telemetry=bool(run.serving_requests),
            metadata={
                **self.metadata,
                "status": resolved_status,
                "experiment_session": True,
            },
        )
        artifact = replace(
            artifact,
            manifest=replace(
                artifact.manifest,
                status=cast(ArtifactStatus, resolved_status),
            ),
        )
        _atomic_save(artifact, self.output_path)
        self._status = resolved_status
        self._finished = True
        return artifact

    def _infer_status(self) -> str:
        if any(task.error for task in self._task_results):
            return "FAILED"
        if (
            self.expected_task_count is not None
            and len(self._task_results) < self.expected_task_count
        ):
            return "PARTIAL"
        return "COMPLETE"

    def _aggregate_quality_metrics(self) -> list[QualityMetric]:
        metrics: list[QualityMetric] = []
        scores = [
            task.quality_score for task in self._task_results if task.quality_score is not None
        ]
        passed = [task.passed for task in self._task_results if task.passed is not None]
        if scores:
            metrics.append(
                QualityMetric(
                    name="mean_score",
                    value=sum(scores) / len(scores),
                    aggregation="mean",
                    tolerance=self.mean_score_tolerance,
                )
            )
        if passed:
            metrics.append(
                QualityMetric(
                    name="pass_rate",
                    value=sum(1 for item in passed if item) / len(passed),
                    aggregation="rate",
                    tolerance=self.pass_rate_tolerance,
                )
            )
        metric_totals: dict[str, list[float]] = {}
        for task in self._task_results:
            for metric in task.quality_metrics:
                if isinstance(metric.value, int | float):
                    metric_totals.setdefault(metric.name, []).append(float(metric.value))
        for name, values in sorted(metric_totals.items()):
            if name in {"mean_score", "pass_rate"}:
                continue
            metrics.append(QualityMetric(name=name, value=sum(values) / len(values)))
        return metrics


def _evaluator_label(quality: QualityResult | None) -> str | None:
    if quality is None:
        return None
    if quality.evaluator_name and quality.evaluator_version:
        return f"{quality.evaluator_name}@{quality.evaluator_version}"
    return quality.evaluator_name


def _safe_environment_metadata() -> dict[str, Any]:
    return {
        "agentperf_version": _agentperf_version(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "git_commit": _git_commit(),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _agentperf_version() -> str:
    try:
        return version("agentperf")
    except PackageNotFoundError:
        return "0+unknown"


def _atomic_save(artifact: ExperimentArtifact, output_path: Path) -> None:
    tmp_path = output_path.with_name(f".{output_path.name}.tmp-{uuid4().hex}")
    artifact.save(tmp_path)
    load_artifact(tmp_path)
    if output_path.exists():
        shutil.rmtree(output_path)
    tmp_path.rename(output_path)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
