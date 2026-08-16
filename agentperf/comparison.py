from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentperf.analyzer import AnalysisReport, analyze_run
from agentperf.artifacts import ArtifactError, ExperimentArtifact, is_artifact_path, load_artifact
from agentperf.metrics.attribution import ContextGrowthRow
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import percentile, prefill_or_path_latency_ms
from agentperf.metrics.tokens import call_input_tokens, call_output_tokens
from agentperf.recommendations import (
    recommendation_verification_to_dict,
    recommendation_verifications,
)
from agentperf.schema.comparison import (
    AcceptanceResult,
    CacheDelta,
    ComponentAccountingSummary,
    ContextGrowthDelta,
    FindingChange,
    FindingLifecycleStatus,
    LatencyDelta,
    MetricDelta,
    QualityDelta,
    RunComparison,
    TokenDelta,
)
from agentperf.schema.findings import Finding
from agentperf.schema.trace import AgentRun, TraceParseError, parse_agentperf_trace


class ComparisonError(ValueError):
    """Raised when replay comparison inputs cannot be loaded."""


@dataclass(frozen=True)
class LoadedWorkload:
    runs: list[AgentRun]
    artifact: ExperimentArtifact | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComponentAccountingSide:
    total_processed: int | None
    total_unique: int | None
    other_processed: int | None
    coverage: float | None
    confidence: str


def compare_paths(
    baseline_path: Path,
    candidate_path: Path,
    *,
    mean_score_tolerance: float | None = None,
    pass_rate_tolerance: float | None = None,
    min_material_improvement: float = 0.05,
) -> RunComparison:
    baseline = load_workload(baseline_path)
    candidate = load_workload(candidate_path)
    return _compare_loaded_workloads(
        baseline,
        candidate,
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
        min_material_improvement=min_material_improvement,
    )


def load_workload(path: Path) -> LoadedWorkload:
    if is_artifact_path(path):
        try:
            artifact = load_artifact(path)
        except ArtifactError as exc:
            raise ComparisonError(str(exc)) from exc
        return LoadedWorkload(runs=artifact.runs_for_comparison(), artifact=artifact)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"invalid JSON: {exc}") from exc
    try:
        return LoadedWorkload(runs=_parse_workload_data(data))
    except TraceParseError as exc:
        raise ComparisonError(str(exc)) from exc


def compare_workloads(
    baseline_runs: list[AgentRun],
    candidate_runs: list[AgentRun],
    *,
    mean_score_tolerance: float | None = None,
    pass_rate_tolerance: float | None = None,
    min_material_improvement: float = 0.05,
) -> RunComparison:
    return _compare_loaded_workloads(
        LoadedWorkload(runs=baseline_runs),
        LoadedWorkload(runs=candidate_runs),
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
        min_material_improvement=min_material_improvement,
    )


def _compare_loaded_workloads(
    baseline: LoadedWorkload,
    candidate: LoadedWorkload,
    *,
    mean_score_tolerance: float | None = None,
    pass_rate_tolerance: float | None = None,
    min_material_improvement: float = 0.05,
) -> RunComparison:
    baseline_runs = baseline.runs
    candidate_runs = candidate.runs
    if not baseline_runs:
        raise ComparisonError("baseline contains no AgentRun entries")
    if not candidate_runs:
        raise ComparisonError("candidate contains no AgentRun entries")

    warnings: list[str] = [
        *baseline.warnings,
        *candidate.warnings,
        *_artifact_warnings("baseline", baseline.artifact),
        *_artifact_warnings("candidate", candidate.artifact),
    ]
    if baseline.artifact and candidate.artifact:
        baseline_tasks = _artifact_task_ids(baseline.artifact)
        candidate_tasks = _artifact_task_ids(candidate.artifact)
        if baseline_tasks and candidate_tasks:
            missing_candidate = sorted(baseline_tasks - candidate_tasks)
            missing_baseline = sorted(candidate_tasks - baseline_tasks)
            if missing_candidate or missing_baseline:
                warnings.append(
                    "Artifact task coverage differs; compare task-level success before "
                    "accepting the replay."
                )
    artifact_incomplete = _artifact_incomplete(baseline.artifact) or _artifact_incomplete(
        candidate.artifact
    )
    mean_score_tolerance = (
        mean_score_tolerance
        if mean_score_tolerance is not None
        else _artifact_tolerance(baseline.artifact, "mean_score")
    )
    pass_rate_tolerance = (
        pass_rate_tolerance
        if pass_rate_tolerance is not None
        else _artifact_tolerance(baseline.artifact, "pass_rate")
    )
    baseline_by_task = _runs_by_task_id(baseline_runs)
    candidate_by_task = _runs_by_task_id(candidate_runs)
    matched_run_keys = sorted(set(baseline_by_task) & set(candidate_by_task))

    if (
        not matched_run_keys
        and len(baseline_runs) == 1
        and len(candidate_runs) == 1
        and not _has_explicit_task_id(baseline_runs[0])
        and not _has_explicit_task_id(candidate_runs[0])
    ):
        baseline_key = next(iter(baseline_by_task))
        candidate_key = next(iter(candidate_by_task))
        matched_run_keys = ["single-run"]
        baseline_by_task = {"single-run": baseline_by_task[baseline_key]}
        candidate_by_task = {"single-run": candidate_by_task[candidate_key]}
        warnings.append(
            "Matched one baseline run to one candidate run by file cardinality; "
            "provide task_id/workload_item_id metadata for stronger matching."
        )

    unmatched_baseline_runs = sorted(set(baseline_by_task) - set(matched_run_keys))
    unmatched_candidate_runs = sorted(set(candidate_by_task) - set(matched_run_keys))
    if unmatched_baseline_runs or unmatched_candidate_runs:
        warnings.append("Some tasks could not be matched and were excluded from deltas.")
    if not matched_run_keys:
        warnings.append("No confidently matched tasks; comparison is inconclusive.")

    baseline_reports = [analyze_run(baseline_by_task[key]) for key in matched_run_keys]
    candidate_reports = [analyze_run(candidate_by_task[key]) for key in matched_run_keys]
    coverage_matched_tasks = matched_run_keys
    coverage_unmatched_baseline = unmatched_baseline_runs
    coverage_unmatched_candidate = unmatched_candidate_runs
    if baseline.artifact and candidate.artifact:
        baseline_task_ids = _artifact_task_ids(baseline.artifact)
        candidate_task_ids = _artifact_task_ids(candidate.artifact)
        if baseline_task_ids and candidate_task_ids:
            coverage_matched_tasks = sorted(baseline_task_ids & candidate_task_ids)
            coverage_unmatched_baseline = sorted(baseline_task_ids - candidate_task_ids)
            coverage_unmatched_candidate = sorted(candidate_task_ids - baseline_task_ids)

    token_deltas = _token_deltas(baseline_reports, candidate_reports)
    context_delta = _context_growth_delta(baseline_reports, candidate_reports)
    latency_deltas = _latency_deltas(baseline_reports, candidate_reports, baseline, candidate)
    cache_deltas = _cache_deltas(baseline_reports, candidate_reports)
    quality_deltas = _quality_deltas(
        baseline,
        candidate,
        [baseline_by_task[key] for key in matched_run_keys],
        [candidate_by_task[key] for key in matched_run_keys],
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
    )
    if quality_deltas.passed is None:
        warnings.append("PERFORMANCE_IMPROVEMENT_UNVERIFIED_FOR_QUALITY")
    finding_changes = _finding_changes(baseline_reports, candidate_reports)
    acceptance = _acceptance(
        token_deltas,
        latency_deltas,
        quality_deltas,
        matched_tasks=matched_run_keys,
        unmatched_baseline=unmatched_baseline_runs,
        unmatched_candidate=unmatched_candidate_runs,
        min_material_improvement=min_material_improvement,
    )
    if artifact_incomplete and acceptance.verdict == "ACCEPT":
        acceptance = AcceptanceResult(
            verdict="INCONCLUSIVE",
            reason=(
                "Artifact status or task coverage is incomplete; "
                "replay acceptance is inconclusive."
            ),
            performance_improved=acceptance.performance_improved,
            quality_passed=acceptance.quality_passed,
            material_regression=acceptance.material_regression,
        )

    return RunComparison(
        baseline_id=_workload_id(baseline_runs, baseline.artifact),
        candidate_id=_workload_id(candidate_runs, candidate.artifact),
        matched_tasks=coverage_matched_tasks,
        unmatched_baseline_tasks=coverage_unmatched_baseline,
        unmatched_candidate_tasks=coverage_unmatched_candidate,
        token_deltas=token_deltas,
        context_growth_delta=context_delta,
        latency_deltas=latency_deltas,
        cache_deltas=cache_deltas,
        quality_deltas=quality_deltas,
        finding_changes=finding_changes,
        acceptance_result=acceptance,
        warnings=warnings,
        metadata={
            "baseline_runs": len(baseline_runs),
            "candidate_runs": len(candidate_runs),
            "matched_run_keys": matched_run_keys,
            "unmatched_baseline_run_keys": unmatched_baseline_runs,
            "unmatched_candidate_run_keys": unmatched_candidate_runs,
            "min_material_improvement": min_material_improvement,
            "baseline_artifact": baseline.artifact.manifest.artifact_id
            if baseline.artifact
            else None,
            "candidate_artifact": candidate.artifact.manifest.artifact_id
            if candidate.artifact
            else None,
            "baseline_artifact_status": baseline.artifact.manifest.status
            if baseline.artifact
            else None,
            "candidate_artifact_status": candidate.artifact.manifest.status
            if candidate.artifact
            else None,
            "baseline_artifact_task_count": baseline.artifact.manifest.task_count
            if baseline.artifact
            else None,
            "candidate_artifact_task_count": candidate.artifact.manifest.task_count
            if candidate.artifact
            else None,
            "baseline_task_results": len(baseline.artifact.task_results)
            if baseline.artifact
            else None,
            "candidate_task_results": len(candidate.artifact.task_results)
            if candidate.artifact
            else None,
            "task_quality_changes": _artifact_task_quality_changes(
                baseline.artifact,
                candidate.artifact,
            ),
        },
    )


def comparison_to_dict(comparison: RunComparison) -> dict[str, Any]:
    data = asdict(comparison)
    data["recommendation_verifications"] = [
        recommendation_verification_to_dict(verification)
        for verification in recommendation_verifications(comparison)
    ]
    return data


def comparison_to_json(comparison: RunComparison) -> str:
    return json.dumps(comparison_to_dict(comparison), indent=2, sort_keys=True)


def _parse_workload_data(data: Any) -> list[AgentRun]:
    if isinstance(data, list):
        return [_parse_trace_entry(item) for item in data]
    if not isinstance(data, dict):
        raise TraceParseError("comparison input must be a trace object, workload object, or list")
    if "runs" in data:
        raw_runs = data["runs"]
        if not isinstance(raw_runs, list):
            raise TraceParseError("workload runs must be a list")
        return [_parse_trace_entry(item) for item in raw_runs]
    if "agent_runs" in data:
        raw_runs = data["agent_runs"]
        if not isinstance(raw_runs, list):
            raise TraceParseError("workload agent_runs must be a list")
        return [_parse_trace_entry({"agent_run": item}) for item in raw_runs]
    return [_parse_trace_entry(data)]


def _parse_trace_entry(item: Any) -> AgentRun:
    if not isinstance(item, dict):
        raise TraceParseError("workload entries must be objects")
    if "agent_run" in item or "serving_requests" in item:
        return parse_agentperf_trace(item)
    return parse_agentperf_trace({"agent_run": item})


def _runs_by_task_id(runs: list[AgentRun]) -> dict[str, AgentRun]:
    result: dict[str, AgentRun] = {}
    counts: defaultdict[str, int] = defaultdict(int)
    for run in runs:
        raw_key = _task_id(run)
        counts[raw_key] += 1
        key = raw_key if counts[raw_key] == 1 else f"{raw_key}#{counts[raw_key]}"
        result[key] = run
    return result


def _task_id(run: AgentRun) -> str:
    for key in ("workload_item_id", "task_id", "execution_id", "run_id"):
        value = run.metadata.get(key)
        if value is not None:
            return str(value)
    return run.agent_run_id


def _has_explicit_task_id(run: AgentRun) -> bool:
    return any(
        run.metadata.get(key) is not None
        for key in ("workload_item_id", "task_id", "execution_id", "run_id")
    )


def _workload_id(runs: list[AgentRun], artifact: ExperimentArtifact | None = None) -> str:
    if artifact and artifact.manifest.workload_id:
        return artifact.manifest.workload_id
    if artifact:
        return artifact.manifest.artifact_id
    if len(runs) == 1:
        return runs[0].agent_run_id
    return f"workload:{len(runs)}"


def _token_deltas(
    baseline_reports: list[AnalysisReport],
    candidate_reports: list[AnalysisReport],
) -> TokenDelta:
    baseline_input = sum(_input_tokens(report) for report in baseline_reports)
    candidate_input = sum(_input_tokens(report) for report in candidate_reports)
    baseline_output = sum(_output_tokens(report) for report in baseline_reports)
    candidate_output = sum(_output_tokens(report) for report in candidate_reports)
    baseline_components = _component_totals(baseline_reports)
    candidate_components = _component_totals(candidate_reports)
    components = {
        component: _delta(
            baseline_components.get(component, 0),
            candidate_components.get(component, 0),
        )
        for component in sorted(set(baseline_components) | set(candidate_components))
    }
    return TokenDelta(
        input_tokens=_delta(baseline_input, candidate_input),
        output_tokens=_delta(baseline_output, candidate_output),
        component_processed_tokens=components,
        component_accounting=_component_accounting_summary(
            baseline_reports,
            candidate_reports,
        ),
    )


def _input_tokens(report: AnalysisReport) -> int:
    return sum(call_input_tokens(call) for call in report.run.llm_calls)


def _output_tokens(report: AnalysisReport) -> int:
    return sum(call_output_tokens(call) for call in report.run.llm_calls)


def _component_totals(reports: list[AnalysisReport]) -> dict[str, int]:
    totals: defaultdict[str, int] = defaultdict(int)
    for report in reports:
        if report.token_attribution is None:
            continue
        for component, tokens in report.token_attribution.processed_tokens_by_component.items():
            totals[component] += tokens
    return dict(totals)


def _component_accounting_summary(
    baseline_reports: list[AnalysisReport],
    candidate_reports: list[AnalysisReport],
) -> ComponentAccountingSummary:
    baseline = _component_accounting_side(baseline_reports)
    candidate = _component_accounting_side(candidate_reports)
    return ComponentAccountingSummary(
        total_processed_tokens=_delta(
            baseline.total_processed,
            candidate.total_processed,
        ),
        total_unique_tokens=_delta(
            baseline.total_unique,
            candidate.total_unique,
        ),
        other_processed_tokens=_delta(
            baseline.other_processed,
            candidate.other_processed,
        ),
        attribution_coverage_ratio=_delta(
            baseline.coverage,
            candidate.coverage,
        ),
        baseline_confidence=baseline.confidence,
        candidate_confidence=candidate.confidence,
    )


def _component_accounting_side(reports: list[AnalysisReport]) -> ComponentAccountingSide:
    attributions = [
        report.token_attribution for report in reports if report.token_attribution is not None
    ]
    if not attributions:
        return ComponentAccountingSide(
            total_processed=None,
            total_unique=None,
            other_processed=None,
            coverage=None,
            confidence="UNAVAILABLE",
        )
    total_processed = sum(item.total_processed_tokens for item in attributions)
    total_unique = sum(item.total_unique_tokens for item in attributions)
    other_processed = sum(
        item.processed_tokens_by_component.get("other", 0) for item in attributions
    )
    coverage = (
        (total_processed - other_processed) / total_processed
        if total_processed
        else None
    )
    confidence = "APPROXIMATE" if any(item.approximate for item in attributions) else "STRUCTURED"
    return ComponentAccountingSide(
        total_processed=total_processed,
        total_unique=total_unique,
        other_processed=other_processed,
        coverage=coverage,
        confidence=confidence,
    )


def _context_growth_delta(
    baseline_reports: list[AnalysisReport],
    candidate_reports: list[AnalysisReport],
) -> ContextGrowthDelta:
    baseline_rows = [row for report in baseline_reports for row in report.context_growth]
    candidate_rows = [row for report in candidate_reports for row in report.context_growth]
    return ContextGrowthDelta(
        final_step_input_tokens=_delta(
            _avg_final_input(baseline_reports),
            _avg_final_input(candidate_reports),
        ),
        max_step_input_tokens=_delta(
            _max_input(baseline_rows),
            _max_input(candidate_rows),
        ),
        growth_slope_tokens_per_step=_delta(
            _avg_growth_slope(baseline_reports),
            _avg_growth_slope(candidate_reports),
        ),
        baseline_steps=len(baseline_rows),
        candidate_steps=len(candidate_rows),
    )


def _avg_final_input(reports: list[AnalysisReport]) -> float | None:
    finals = [report.context_growth[-1].input_tokens for report in reports if report.context_growth]
    return _mean(finals)


def _max_input(rows: list[ContextGrowthRow]) -> int | None:
    values = [row.input_tokens for row in rows]
    return max(values) if values else None


def _avg_growth_slope(reports: list[AnalysisReport]) -> float | None:
    slopes: list[float] = []
    for report in reports:
        rows = report.context_growth
        if len(rows) < 2:
            continue
        slopes.append((rows[-1].input_tokens - rows[0].input_tokens) / (len(rows) - 1))
    return _mean(slopes)


def _latency_deltas(
    baseline_reports: list[AnalysisReport],
    candidate_reports: list[AnalysisReport],
    baseline_workload: LoadedWorkload | None = None,
    candidate_workload: LoadedWorkload | None = None,
) -> LatencyDelta:
    baseline = _latency_summary(
        baseline_reports,
        baseline_workload.artifact if baseline_workload else None,
    )
    candidate = _latency_summary(
        candidate_reports,
        candidate_workload.artifact if candidate_workload else None,
    )
    return LatencyDelta(
        tool_latency_ms=_delta(baseline["tool_total"], candidate["tool_total"]),
        queue_p50_ms=_delta(baseline["queue_p50"], candidate["queue_p50"]),
        queue_p95_ms=_delta(baseline["queue_p95"], candidate["queue_p95"]),
        scheduled_to_first_p50_ms=_delta(baseline["first_p50"], candidate["first_p50"], "PROXY"),
        scheduled_to_first_p95_ms=_delta(baseline["first_p95"], candidate["first_p95"], "PROXY"),
        generation_p50_ms=_delta(baseline["generation_p50"], candidate["generation_p50"]),
        generation_p95_ms=_delta(baseline["generation_p95"], candidate["generation_p95"]),
        client_p50_ms=_delta(baseline["client_p50"], candidate["client_p50"]),
        client_p95_ms=_delta(baseline["client_p95"], candidate["client_p95"]),
    )


def _latency_summary(
    reports: list[AnalysisReport],
    artifact: ExperimentArtifact | None = None,
) -> dict[str, float | None]:
    queue = [
        request.queue_latency_ms
        for report in reports
        for request in report.run.serving_requests
        if request.queue_latency_ms is not None
    ]
    first = [
        request.ttft_ms if request.ttft_ms is not None else prefill_or_path_latency_ms(request)
        for report in reports
        for request in report.run.serving_requests
    ]
    generation = [
        request.decode_latency_ms
        for report in reports
        for request in report.run.serving_requests
        if request.decode_latency_ms is not None
    ]
    client = [
        float(call.metadata["latency_ms"])
        for report in reports
        for call in report.run.llm_calls
        if isinstance(call.metadata.get("latency_ms"), int | float)
    ]
    if artifact is not None:
        client.extend(
            float(task.client_latency_ms)
            for task in artifact.task_results
            if task.client_latency_ms is not None
        )
    return {
        "tool_total": sum(
            tool.latency_ms or 0
            for report in reports
            for tool in report.run.tool_calls
        ),
        "queue_p50": percentile([float(value) for value in queue], 0.50),
        "queue_p95": percentile([float(value) for value in queue], 0.95),
        "first_p50": percentile([float(value) for value in first if value is not None], 0.50),
        "first_p95": percentile([float(value) for value in first if value is not None], 0.95),
        "generation_p50": percentile([float(value) for value in generation], 0.50),
        "generation_p95": percentile([float(value) for value in generation], 0.95),
        "client_p50": percentile(client, 0.50),
        "client_p95": percentile(client, 0.95),
    }


def _artifact_warnings(prefix: str, artifact: ExperimentArtifact | None) -> list[str]:
    if artifact is None:
        return []
    warnings: list[str] = []
    if artifact.manifest.status != "COMPLETE":
        warnings.append(f"{prefix} artifact status is {artifact.manifest.status}.")
    if (
        artifact.manifest.task_count is not None
        and artifact.task_results
        and len(artifact.task_results) < artifact.manifest.task_count
    ):
        warnings.append(
            f"{prefix} artifact has {len(artifact.task_results)} of "
            f"{artifact.manifest.task_count} expected task results."
        )
    return warnings


def _artifact_task_ids(artifact: ExperimentArtifact) -> set[str]:
    return {task.task_id for task in artifact.task_results}


def _artifact_task_quality_changes(
    baseline: ExperimentArtifact | None,
    candidate: ExperimentArtifact | None,
) -> list[dict[str, Any]]:
    if baseline is None or candidate is None:
        return []
    baseline_tasks = {task.task_id: task for task in baseline.task_results}
    candidate_tasks = {task.task_id: task for task in candidate.task_results}
    changes: list[dict[str, Any]] = []
    for task_id in sorted(set(baseline_tasks) & set(candidate_tasks)):
        base = baseline_tasks[task_id]
        cand = candidate_tasks[task_id]
        passed_changed = (
            base.passed is not None
            and cand.passed is not None
            and base.passed != cand.passed
        )
        score_changed = (
            base.quality_score is not None
            and cand.quality_score is not None
            and abs(float(cand.quality_score) - float(base.quality_score)) > 1e-12
        )
        if not passed_changed and not score_changed:
            continue
        changes.append(
            {
                "task_id": task_id,
                "baseline_passed": base.passed,
                "candidate_passed": cand.passed,
                "baseline_score": base.quality_score,
                "candidate_score": cand.quality_score,
            }
        )
    return changes


def _artifact_incomplete(artifact: ExperimentArtifact | None) -> bool:
    if artifact is None:
        return False
    if artifact.manifest.status != "COMPLETE":
        return True
    return (
        artifact.manifest.task_count is not None
        and bool(artifact.task_results)
        and len(artifact.task_results) < artifact.manifest.task_count
    )


def _cache_deltas(
    baseline_reports: list[AnalysisReport],
    candidate_reports: list[AnalysisReport],
) -> CacheDelta:
    baseline = _cache_summary(baseline_reports)
    candidate = _cache_summary(candidate_reports)
    return CacheDelta(
        cached_tokens=_delta(baseline["cached"], candidate["cached"]),
        cache_miss_tokens=_delta(baseline["miss"], candidate["miss"]),
        cached_token_ratio=_delta(baseline["ratio"], candidate["ratio"]),
    )


def _cache_summary(reports: list[AnalysisReport]) -> dict[str, float | int | None]:
    requests = [request for report in reports for request in report.run.serving_requests]
    cached_values = [request.prefix_cache_hit_tokens for request in requests]
    miss_values = [request.prefix_cache_miss_tokens for request in requests]
    cached = sum(value for value in cached_values if value is not None)
    miss = sum(value for value in miss_values if value is not None)
    has_cache = any(value is not None for value in cached_values + miss_values)
    return {
        "cached": cached if has_cache else None,
        "miss": miss if has_cache else None,
        "ratio": prefix_cache_hit_ratio(requests),
    }


def _quality_deltas(
    baseline: LoadedWorkload,
    candidate: LoadedWorkload,
    baseline_runs: list[AgentRun],
    candidate_runs: list[AgentRun],
    *,
    mean_score_tolerance: float | None,
    pass_rate_tolerance: float | None,
) -> QualityDelta:
    artifact_quality = _artifact_quality_deltas(
        baseline,
        candidate,
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
    )
    if artifact_quality is not None:
        return artifact_quality
    baseline_scores = [_quality_score(run) for run in baseline_runs]
    candidate_scores = [_quality_score(run) for run in candidate_runs]
    baseline_passed = [_task_passed(run) for run in baseline_runs]
    candidate_passed = [_task_passed(run) for run in candidate_runs]
    baseline_score_values = [value for value in baseline_scores if value is not None]
    candidate_score_values = [value for value in candidate_scores if value is not None]
    baseline_pass_values = [value for value in baseline_passed if value is not None]
    candidate_pass_values = [value for value in candidate_passed if value is not None]
    mean_delta = _delta(_mean(baseline_score_values), _mean(candidate_score_values))
    pass_delta = _delta(_pass_rate(baseline_pass_values), _pass_rate(candidate_pass_values))
    passed: bool | None = None
    if mean_delta.baseline is not None and mean_delta.candidate is not None:
        mean_ok = _within_drop_tolerance(
            float(mean_delta.baseline),
            float(mean_delta.candidate),
            mean_score_tolerance,
        )
        pass_ok = True
        if pass_delta.baseline is not None and pass_delta.candidate is not None:
            pass_ok = _within_drop_tolerance(
                float(pass_delta.baseline),
                float(pass_delta.candidate),
                pass_rate_tolerance,
            )
        passed = mean_ok and pass_ok
    return QualityDelta(
        mean_score=mean_delta,
        pass_rate=pass_delta,
        baseline_tasks_with_quality=len(baseline_score_values),
        candidate_tasks_with_quality=len(candidate_score_values),
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
        passed=passed,
    )


def _artifact_quality_deltas(
    baseline: LoadedWorkload,
    candidate: LoadedWorkload,
    *,
    mean_score_tolerance: float | None,
    pass_rate_tolerance: float | None,
) -> QualityDelta | None:
    if baseline.artifact is None or candidate.artifact is None:
        return None
    baseline_mean = _artifact_metric_value(baseline.artifact, "mean_score")
    candidate_mean = _artifact_metric_value(candidate.artifact, "mean_score")
    baseline_pass = _artifact_metric_value(baseline.artifact, "pass_rate")
    candidate_pass = _artifact_metric_value(candidate.artifact, "pass_rate")
    if (
        baseline_mean is None
        and candidate_mean is None
        and baseline_pass is None
        and candidate_pass is None
    ):
        return None
    mean_delta = _delta(baseline_mean, candidate_mean)
    pass_delta = _delta(baseline_pass, candidate_pass)
    passed: bool | None = None
    if mean_delta.baseline is not None and mean_delta.candidate is not None:
        mean_ok = _within_drop_tolerance(
            float(mean_delta.baseline),
            float(mean_delta.candidate),
            mean_score_tolerance,
        )
        pass_ok = True
        if pass_delta.baseline is not None and pass_delta.candidate is not None:
            pass_ok = _within_drop_tolerance(
                float(pass_delta.baseline),
                float(pass_delta.candidate),
                pass_rate_tolerance,
            )
        passed = mean_ok and pass_ok
    return QualityDelta(
        mean_score=mean_delta,
        pass_rate=pass_delta,
        baseline_tasks_with_quality=_artifact_task_count(baseline.artifact),
        candidate_tasks_with_quality=_artifact_task_count(candidate.artifact),
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
        passed=passed,
    )


def _artifact_metric_value(artifact: ExperimentArtifact, name: str) -> float | None:
    aliases = {
        "mean_score": {"mean_score", "score", "quality_score", "rule_score"},
        "pass_rate": {"pass_rate", "task_success_rate"},
    }[name]
    for metric in artifact.quality_metrics:
        if metric.name in aliases and isinstance(metric.value, int | float):
            return float(metric.value)
    return None


def _within_drop_tolerance(
    baseline: float,
    candidate: float,
    tolerance: float | None,
) -> bool:
    if tolerance is None:
        return True
    return candidate + 1e-12 >= baseline - tolerance


def _artifact_tolerance(artifact: ExperimentArtifact | None, name: str) -> float | None:
    if artifact is None:
        return None
    aliases = {
        "mean_score": {"mean_score", "score", "quality_score", "rule_score"},
        "pass_rate": {"pass_rate", "task_success_rate"},
    }[name]
    for metric in artifact.quality_metrics:
        if metric.name in aliases and metric.tolerance is not None:
            return metric.tolerance
    return None


def _artifact_task_count(artifact: ExperimentArtifact) -> int:
    if artifact.task_results:
        return len(artifact.task_results)
    if artifact.manifest.task_count is not None:
        return artifact.manifest.task_count
    return len(artifact.runs)


def _quality_score(run: AgentRun) -> float | None:
    quality = run.metadata.get("quality")
    if isinstance(quality, dict):
        for key in ("score", "mean_score", "quality", "rule_score"):
            value = quality.get(key)
            if isinstance(value, int | float):
                return float(value)
    for key in ("score", "mean_score", "quality_score", "rule_score"):
        value = run.metadata.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def _task_passed(run: AgentRun) -> bool | None:
    quality = run.metadata.get("quality")
    if isinstance(quality, dict):
        for key in ("passed", "success"):
            value = quality.get(key)
            if isinstance(value, bool):
                return value
        value = quality.get("pass_rate")
        if isinstance(value, int | float):
            return bool(float(value) >= 1.0)
    for key in ("passed", "success", "task_success"):
        value = run.metadata.get(key)
        if isinstance(value, bool):
            return value
    return None


def _finding_changes(
    baseline_reports: list[AnalysisReport],
    candidate_reports: list[AnalysisReport],
) -> list[FindingChange]:
    baseline = _findings_by_key(
        [finding for report in baseline_reports for finding in report.findings]
    )
    candidate = _findings_by_key(
        [finding for report in candidate_reports for finding in report.findings]
    )
    changes: list[FindingChange] = []
    for key in sorted(set(baseline) | set(candidate)):
        base = baseline.get(key)
        cand = candidate.get(key)
        lifecycle: FindingLifecycleStatus
        if base and not cand:
            lifecycle = "RESOLVED"
        elif cand and not base:
            lifecycle = "NEW"
        elif base and cand:
            base_rank = _severity_rank(base.severity)
            cand_rank = _severity_rank(cand.severity)
            if cand_rank < base_rank:
                lifecycle = "IMPROVED"
            elif cand_rank > base_rank:
                lifecycle = "REGRESSED"
            else:
                lifecycle = "PERSISTENT"
        else:  # pragma: no cover - defensive
            continue
        selected = base if base is not None else cand
        if selected is None:  # pragma: no cover - defensive
            continue
        changes.append(
            FindingChange(
                finding_id=selected.id,
                lifecycle=lifecycle,
                baseline_severity=base.severity if base else None,
                candidate_severity=cand.severity if cand else None,
                baseline_materiality=_finding_materiality(base) if base else None,
                candidate_materiality=_finding_materiality(cand) if cand else None,
                scope=_finding_scope(selected),
                baseline_summary=base.summary if base else None,
                candidate_summary=cand.summary if cand else None,
            )
        )
    return changes


def _findings_by_key(findings: list[Finding]) -> dict[tuple[str, str | None], Finding]:
    by_key: dict[tuple[str, str | None], Finding] = {}
    for finding in findings:
        key = (finding.id, _finding_scope(finding))
        existing = by_key.get(key)
        if existing is None or _severity_rank(finding.severity) > _severity_rank(existing.severity):
            by_key[key] = finding
    return by_key


def _finding_scope(finding: Finding) -> str | None:
    evidence = finding.evidence
    for key in ("tool_call_id", "scope", "role", "candidate_model"):
        value = evidence.get(key)
        if value is not None:
            return f"{key}:{value}"
    if finding.provenance.llm_call_ids:
        return "llm:" + ",".join(finding.provenance.llm_call_ids[:3])
    return None


def _finding_materiality(finding: Finding) -> str | None:
    value = finding.evidence.get("materiality")
    if value is not None:
        return str(value)
    value = finding.provenance.derived_metrics.get("materiality")
    if value is not None:
        return str(value)
    if finding.id == "TOOL_OUTPUT_BLOAT":
        return "MATERIAL"
    if finding.severity == "HIGH":
        return "MATERIAL"
    return None


def _severity_rank(value: str) -> int:
    return {"LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(value, 0)


def _acceptance(
    token_deltas: TokenDelta,
    latency_deltas: LatencyDelta,
    quality_deltas: QualityDelta,
    *,
    matched_tasks: list[str],
    unmatched_baseline: list[str],
    unmatched_candidate: list[str],
    min_material_improvement: float,
) -> AcceptanceResult:
    if not matched_tasks:
        return AcceptanceResult(
            verdict="INCONCLUSIVE",
            reason="No confidently matched tasks were available.",
            performance_improved=False,
            quality_passed=quality_deltas.passed,
            material_regression=False,
        )
    if unmatched_baseline or unmatched_candidate:
        return AcceptanceResult(
            verdict="INCONCLUSIVE",
            reason="Unmatched tasks prevent a strong replay verdict.",
            performance_improved=False,
            quality_passed=quality_deltas.passed,
            material_regression=False,
        )
    performance_improved = _material_decrease(
        token_deltas.input_tokens,
        min_material_improvement,
    ) or _material_decrease(latency_deltas.client_p95_ms, min_material_improvement)
    material_regression = _material_increase(
        token_deltas.input_tokens,
        min_material_improvement,
    ) or _material_increase(latency_deltas.client_p95_ms, min_material_improvement)
    if quality_deltas.passed is False:
        return AcceptanceResult(
            verdict="REJECT_QUALITY_REGRESSION",
            reason=(
                "Performance changes cannot be accepted because quality violated "
                "the configured constraint."
            ),
            performance_improved=performance_improved,
            quality_passed=False,
            material_regression=material_regression,
        )
    if material_regression and not performance_improved:
        return AcceptanceResult(
            verdict="REGRESSION",
            reason="Candidate is materially worse on tokens or client latency.",
            performance_improved=False,
            quality_passed=quality_deltas.passed,
            material_regression=True,
        )
    if performance_improved and quality_deltas.passed is True:
        return AcceptanceResult(
            verdict="ACCEPT",
            reason=(
                "Performance materially improved and quality stayed within the "
                "configured tolerance."
            ),
            performance_improved=True,
            quality_passed=True,
            material_regression=material_regression,
        )
    if performance_improved and quality_deltas.passed is None:
        return AcceptanceResult(
            verdict="INCONCLUSIVE",
            reason="Performance improved, but no task quality signal was available.",
            performance_improved=True,
            quality_passed=None,
            material_regression=material_regression,
        )
    return AcceptanceResult(
        verdict="NO_MATERIAL_CHANGE",
        reason="No material token or client-latency improvement was observed.",
        performance_improved=False,
        quality_passed=quality_deltas.passed,
        material_regression=material_regression,
    )


def _material_decrease(delta: MetricDelta, threshold: float) -> bool:
    return delta.percent_delta is not None and delta.percent_delta <= -threshold


def _material_increase(delta: MetricDelta, threshold: float) -> bool:
    return delta.percent_delta is not None and delta.percent_delta >= threshold


def _delta(
    baseline: float | int | None,
    candidate: float | int | None,
    measurement_quality: str = "DERIVED",
) -> MetricDelta:
    if baseline is None or candidate is None:
        return MetricDelta(
            baseline=baseline,
            candidate=candidate,
            delta=None,
            percent_delta=None,
            measurement_quality="UNAVAILABLE",
        )
    change = candidate - baseline
    percent = change / baseline if baseline else None
    return MetricDelta(
        baseline=baseline,
        candidate=candidate,
        delta=change,
        percent_delta=percent,
        measurement_quality=measurement_quality,
    )


def _mean(values: list[float] | list[int]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _pass_rate(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)
