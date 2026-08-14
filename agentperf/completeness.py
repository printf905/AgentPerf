from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from agentperf.analyzer import AnalysisReport, analyze_path, analyze_run
from agentperf.artifacts import ArtifactError, is_artifact_path, load_artifact
from agentperf.schema.artifacts import ArtifactManifest, TaskResult
from agentperf.schema.trace import LLMCall, TraceParseError

ReadinessStatus = Literal["READY", "PARTIAL", "NOT_READY", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class CoverageMetric:
    name: str
    observed: int
    eligible: int
    covered: int
    status: ReadinessStatus
    detail: str

    @property
    def ratio(self) -> float | None:
        if self.eligible <= 0:
            return None
        return self.covered / self.eligible


@dataclass(frozen=True)
class CompletenessReport:
    artifact_valid: bool
    source_type: str
    source_path: str
    artifact_id: str | None
    workload_id: str | None
    artifact_status: str | None
    expected_tasks: int | None
    tasks_observed: int
    tasks_with_outcomes: int
    tasks_with_quality: int
    runs_observed: int
    llm_calls_observed: int
    tool_calls_observed: int
    serving_requests_observed: int
    llm_calls_with_timing: int
    llm_calls_with_provider_usage: int
    llm_calls_with_component_attribution: int
    llm_calls_with_request_ids: int
    eligible_serving_correlations: int
    exact_serving_correlations: int
    agent_profiling_readiness: ReadinessStatus
    cross_layer_readiness: ReadinessStatus
    metrics: list[CoverageMetric] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "metrics": [
                {
                    **asdict(metric),
                    "ratio": metric.ratio,
                }
                for metric in self.metrics
            ],
        }


def assess_path(path: Path) -> CompletenessReport:
    try:
        if is_artifact_path(path):
            artifact = load_artifact(path)
            reports = [analyze_run(run) for run in artifact.runs_for_comparison()]
            return assess_runs(
                reports,
                task_results=artifact.task_results,
                manifest=artifact.manifest,
                source_type="artifact",
                source_path=str(path),
            )
        return assess_runs(
            [analyze_path(path)],
            task_results=[],
            manifest=None,
            source_type="raw_trace",
            source_path=str(path),
        )
    except (OSError, ArtifactError, TraceParseError, json.JSONDecodeError, ValueError) as exc:
        return CompletenessReport(
            artifact_valid=False,
            source_type="unknown",
            source_path=str(path),
            artifact_id=None,
            workload_id=None,
            artifact_status=None,
            expected_tasks=None,
            tasks_observed=0,
            tasks_with_outcomes=0,
            tasks_with_quality=0,
            runs_observed=0,
            llm_calls_observed=0,
            tool_calls_observed=0,
            serving_requests_observed=0,
            llm_calls_with_timing=0,
            llm_calls_with_provider_usage=0,
            llm_calls_with_component_attribution=0,
            llm_calls_with_request_ids=0,
            eligible_serving_correlations=0,
            exact_serving_correlations=0,
            agent_profiling_readiness="NOT_READY",
            cross_layer_readiness="NOT_APPLICABLE",
            errors=[str(exc)],
        )


def assess_report(
    report: AnalysisReport,
    *,
    task_results: list[TaskResult] | None = None,
    manifest: ArtifactManifest | None = None,
    source_type: str = "analysis",
    source_path: str = "",
) -> CompletenessReport:
    return assess_runs(
        [report],
        task_results=task_results or [],
        manifest=manifest,
        source_type=source_type,
        source_path=source_path,
    )


def assess_runs(
    reports: list[AnalysisReport],
    *,
    task_results: list[TaskResult],
    manifest: ArtifactManifest | None,
    source_type: str,
    source_path: str,
) -> CompletenessReport:
    runs = [report.run for report in reports]
    all_llm_calls = [call for run in runs for call in run.llm_calls]
    all_tool_calls = [call for run in runs for call in run.tool_calls]
    serving_requests = [request for run in runs for request in run.serving_requests]
    llm_count = len(all_llm_calls)
    timing_count = sum(1 for call in all_llm_calls if _has_llm_timing(call))
    provider_usage_count = sum(
        1
        for call in all_llm_calls
        if call.input_tokens is not None or call.output_tokens is not None
    )
    component_count = sum(1 for call in all_llm_calls if call.prompt_components)
    request_id_count = sum(
        1 for call in all_llm_calls if call.llm_request_id or call.serving_request_id
    )
    exact_correlations = sum(len(report.correlation.llm_to_serving) for report in reports)
    eligible_correlations = request_id_count if serving_requests else 0
    task_count = len(task_results)
    expected_tasks = (
        manifest.task_count
        if manifest and manifest.task_count is not None
        else task_count
    )
    tasks_with_outcomes = sum(1 for task in task_results if _has_task_outcome(task))
    tasks_with_quality = sum(1 for task in task_results if _has_task_quality(task))
    agent_status, agent_limitations = _agent_readiness(
        manifest=manifest,
        llm_count=llm_count,
        timing_count=timing_count,
        provider_usage_count=provider_usage_count,
        component_count=component_count,
        expected_tasks=expected_tasks,
        tasks_observed=task_count,
        tasks_with_outcomes=tasks_with_outcomes,
    )
    cross_status, cross_limitations = _cross_layer_readiness(
        manifest=manifest,
        serving_requests=len(serving_requests),
        llm_count=llm_count,
        request_id_count=request_id_count,
        eligible_correlations=eligible_correlations,
        exact_correlations=exact_correlations,
    )
    metrics = [
        CoverageMetric(
            name="tasks_with_outcomes",
            observed=task_count,
            eligible=expected_tasks or task_count,
            covered=tasks_with_outcomes,
            status=_coverage_status(tasks_with_outcomes, expected_tasks or task_count),
            detail="Task rows with pass/status/error/quality outcome evidence.",
        ),
        CoverageMetric(
            name="tasks_with_quality",
            observed=task_count,
            eligible=task_count,
            covered=tasks_with_quality,
            status=_coverage_status(tasks_with_quality, task_count),
            detail="Task rows with quality score, pass flag, or named quality metric.",
        ),
        CoverageMetric(
            name="llm_calls_with_timing",
            observed=llm_count,
            eligible=llm_count,
            covered=timing_count,
            status=_coverage_status(timing_count, llm_count),
            detail="LLM calls with start/end timestamps or recorded latency.",
        ),
        CoverageMetric(
            name="llm_calls_with_provider_usage",
            observed=llm_count,
            eligible=llm_count,
            covered=provider_usage_count,
            status=_coverage_status(provider_usage_count, llm_count),
            detail="LLM calls with provider input/output token usage.",
        ),
        CoverageMetric(
            name="llm_calls_with_component_attribution",
            observed=llm_count,
            eligible=llm_count,
            covered=component_count,
            status=_coverage_status(component_count, llm_count),
            detail="LLM calls with prompt component boundaries.",
        ),
        CoverageMetric(
            name="llm_calls_with_request_ids",
            observed=llm_count,
            eligible=llm_count if serving_requests else 0,
            covered=request_id_count,
            status=(
                _coverage_status(request_id_count, llm_count)
                if serving_requests
                else "NOT_APPLICABLE"
            ),
            detail="LLM calls with stable request IDs for serving correlation.",
        ),
        CoverageMetric(
            name="exact_serving_correlations",
            observed=len(serving_requests),
            eligible=eligible_correlations,
            covered=exact_correlations,
            status=(
                _coverage_status(exact_correlations, eligible_correlations)
                if serving_requests
                else "NOT_APPLICABLE"
            ),
            detail="Eligible request-ID-bearing LLM calls exactly joined to serving telemetry.",
        ),
    ]
    return CompletenessReport(
        artifact_valid=True,
        source_type=source_type,
        source_path=source_path,
        artifact_id=manifest.artifact_id if manifest else None,
        workload_id=manifest.workload_id if manifest else None,
        artifact_status=manifest.status if manifest else None,
        expected_tasks=expected_tasks,
        tasks_observed=task_count,
        tasks_with_outcomes=tasks_with_outcomes,
        tasks_with_quality=tasks_with_quality,
        runs_observed=len(runs),
        llm_calls_observed=llm_count,
        tool_calls_observed=len(all_tool_calls),
        serving_requests_observed=len(serving_requests),
        llm_calls_with_timing=timing_count,
        llm_calls_with_provider_usage=provider_usage_count,
        llm_calls_with_component_attribution=component_count,
        llm_calls_with_request_ids=request_id_count,
        eligible_serving_correlations=eligible_correlations,
        exact_serving_correlations=exact_correlations,
        agent_profiling_readiness=agent_status,
        cross_layer_readiness=cross_status,
        metrics=metrics,
        limitations=agent_limitations + cross_limitations,
    )


def render_doctor_report(report: CompletenessReport) -> str:
    lines = [
        "AgentPerf Integration Check",
        "=" * 60,
        "",
        "Artifact",
        "-" * 60,
        _status_line(report.artifact_valid, "artifact loads successfully"),
        _detail("source", f"{report.source_type}: {report.source_path}"),
    ]
    if report.artifact_id:
        lines.append(_detail("artifact id", report.artifact_id))
    if report.workload_id:
        lines.append(_detail("workload", report.workload_id))
    if report.artifact_status:
        lines.append(_detail("status", report.artifact_status))
    lines.extend(
        [
            "",
            "Tasks",
            "-" * 60,
            _coverage_line("tasks observed", report.tasks_observed, report.expected_tasks),
            _coverage_line(
                "tasks with outcomes",
                report.tasks_with_outcomes,
                report.expected_tasks,
            ),
            _coverage_line(
                "tasks with quality",
                report.tasks_with_quality,
                report.tasks_observed,
            ),
            "",
            "Agent tracing",
            "-" * 60,
            _detail("runs observed", str(report.runs_observed)),
            _detail("LLM calls observed", str(report.llm_calls_observed)),
            _coverage_line(
                "LLM calls with timing",
                report.llm_calls_with_timing,
                report.llm_calls_observed,
            ),
            _coverage_line(
                "LLM calls with component attribution",
                report.llm_calls_with_component_attribution,
                report.llm_calls_observed,
            ),
            _detail("tool calls observed", str(report.tool_calls_observed)),
            "",
            "Provider usage",
            "-" * 60,
            _coverage_line(
                "LLM calls with provider usage",
                report.llm_calls_with_provider_usage,
                report.llm_calls_observed,
            ),
            "",
            "Serving correlation",
            "-" * 60,
            _coverage_line(
                "stable request IDs",
                report.llm_calls_with_request_ids,
                report.llm_calls_observed
                if report.serving_requests_observed
                else None,
            ),
            _coverage_line(
                "exact serving correlations",
                report.exact_serving_correlations,
                report.eligible_serving_correlations
                if report.serving_requests_observed
                else None,
            ),
            _detail("serving requests observed", str(report.serving_requests_observed)),
            "",
            "Readiness",
            "-" * 60,
            _detail("Agent-level profiling", report.agent_profiling_readiness),
            _detail("Cross-layer profiling", report.cross_layer_readiness),
        ]
    )
    if report.limitations or report.errors:
        lines.extend(["", "Limitations", "-" * 60])
        for error in report.errors:
            lines.append(f"- {error}")
        for limitation in report.limitations:
            lines.append(f"- {limitation}")
    return "\n".join(lines)


def doctor_exit_code(report: CompletenessReport) -> int:
    if not report.artifact_valid:
        return 1
    return 1 if report.agent_profiling_readiness == "NOT_READY" else 0


def completeness_to_json(report: CompletenessReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def _agent_readiness(
    *,
    manifest: ArtifactManifest | None,
    llm_count: int,
    timing_count: int,
    provider_usage_count: int,
    component_count: int,
    expected_tasks: int | None,
    tasks_observed: int,
    tasks_with_outcomes: int,
) -> tuple[ReadinessStatus, list[str]]:
    limitations: list[str] = []
    if manifest and manifest.status == "FAILED":
        limitations.append("artifact status is FAILED")
        return "NOT_READY", limitations
    if llm_count == 0:
        limitations.append("no LLM calls were captured")
        return "NOT_READY", limitations
    status: ReadinessStatus = "READY"
    if manifest and manifest.status == "PARTIAL":
        limitations.append("artifact status is PARTIAL")
        status = "PARTIAL"
    if expected_tasks and tasks_observed < expected_tasks:
        limitations.append(f"only {tasks_observed}/{expected_tasks} expected task rows recorded")
        status = "PARTIAL"
    if expected_tasks and tasks_with_outcomes < expected_tasks:
        limitations.append(
            f"only {tasks_with_outcomes}/{expected_tasks} expected tasks have outcomes"
        )
        status = "PARTIAL"
    if timing_count < llm_count:
        limitations.append(f"{llm_count - timing_count} LLM calls lack timing evidence")
        status = "PARTIAL"
    if component_count == 0 and provider_usage_count == 0:
        limitations.append("LLM calls lack both provider usage and component attribution")
        status = "PARTIAL"
    elif component_count < llm_count:
        limitations.append(
            f"{llm_count - component_count} LLM calls lack component attribution"
        )
    if provider_usage_count < llm_count:
        limitations.append(f"{llm_count - provider_usage_count} LLM calls lack provider usage")
    return status, limitations


def _cross_layer_readiness(
    *,
    manifest: ArtifactManifest | None,
    serving_requests: int,
    llm_count: int,
    request_id_count: int,
    eligible_correlations: int,
    exact_correlations: int,
) -> tuple[ReadinessStatus, list[str]]:
    limitations: list[str] = []
    if serving_requests == 0:
        if manifest and manifest.serving_telemetry:
            limitations.append("manifest expects serving telemetry, but no serving requests loaded")
            return "PARTIAL", limitations
        return "NOT_APPLICABLE", limitations
    if request_id_count == 0:
        limitations.append("serving telemetry exists, but no LLM calls have stable request IDs")
        return "NOT_READY", limitations
    if exact_correlations < eligible_correlations:
        limitations.append(
            f"{eligible_correlations - exact_correlations} request-ID-bearing LLM calls "
            "did not correlate to serving telemetry"
        )
        return "PARTIAL", limitations
    if request_id_count < llm_count:
        limitations.append(f"{llm_count - request_id_count} LLM calls lack stable request IDs")
        return "PARTIAL", limitations
    return "READY", limitations


def _coverage_status(covered: int, eligible: int) -> ReadinessStatus:
    if eligible <= 0:
        return "NOT_APPLICABLE"
    if covered == eligible:
        return "READY"
    if covered > 0:
        return "PARTIAL"
    return "NOT_READY"


def _has_llm_timing(call: LLMCall) -> bool:
    return bool(
        (call.started_at and call.ended_at)
        or call.metadata.get("latency_ms") is not None
        or call.ttft_ms is not None
    )


def _has_task_outcome(task: TaskResult) -> bool:
    return (
        task.passed is not None
        or task.quality_score is not None
        or task.status is not None
        or task.error is not None
    )


def _has_task_quality(task: TaskResult) -> bool:
    return task.quality_score is not None or task.passed is not None or bool(task.quality_metrics)


def _status_line(ok: bool, text: str) -> str:
    return f"{'OK' if ok else 'FAIL'} {text}"


def _detail(label: str, value: str) -> str:
    return f"{label:<36} {value}"


def _coverage_line(label: str, covered: int, eligible: int | None) -> str:
    if eligible is None or eligible <= 0:
        return f"{label:<36} {covered} / n/a"
    marker = "OK" if covered == eligible else ("PARTIAL" if covered else "MISSING")
    return f"{marker} {label:<34} {covered} / {eligible}"
