from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from agentperf.analyzer import AnalysisReport, analyze_run
from agentperf.schema.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactLocation,
    ArtifactManifest,
    MetricDirection,
    QualityMetric,
    TaskResult,
)
from agentperf.schema.findings import (
    ExpectedMetricChange,
    Finding,
    FindingProvenance,
    RecommendationContract,
)
from agentperf.schema.trace import AgentRun, TraceParseError, parse_agentperf_trace


class ArtifactError(ValueError):
    """Raised when an AgentPerf artifact bundle is invalid or unsupported."""


@dataclass(frozen=True)
class ExperimentArtifact:
    manifest: ArtifactManifest
    runs: list[AgentRun]
    task_results: list[TaskResult]
    quality_metrics: list[QualityMetric]
    findings: list[Finding]
    environment: dict[str, Any]
    summary: dict[str, Any]

    @classmethod
    def from_run(
        cls,
        run: AgentRun,
        *,
        artifact_id: str | None = None,
        workload_id: str | None = None,
        task_results: list[TaskResult] | None = None,
        task_count: int | None = None,
        quality_metrics: list[QualityMetric] | None = None,
        findings: list[Finding] | None = None,
        environment: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
        framework: str | None = None,
        agent_name: str | None = None,
        backend: str | None = None,
        model: str | None = None,
        serving_telemetry: bool | None = None,
        created_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExperimentArtifact:
        resolved_workload_id = workload_id or _metadata_str(run, "workload_id") or run.agent_run_id
        resolved_artifact_id = artifact_id or resolved_workload_id
        manifest = ArtifactManifest(
            artifact_schema_version=ARTIFACT_SCHEMA_VERSION,
            artifact_id=resolved_artifact_id,
            created_at=created_at or datetime.now(UTC).isoformat(),
            agentperf_version=_agentperf_version(),
            workload_id=resolved_workload_id,
            framework=framework or _metadata_str(run, "framework"),
            agent_name=agent_name or run.name,
            backend=backend or _metadata_str(run, "backend"),
            model=model or _metadata_str(run, "model"),
            task_count=task_count if task_count is not None else len(task_results or []),
            serving_telemetry=(
                bool(run.serving_requests) if serving_telemetry is None else serving_telemetry
            ),
            status="COMPLETE",
            metadata=metadata or {},
        )
        return cls(
            manifest=manifest,
            runs=[run],
            task_results=task_results or [],
            quality_metrics=quality_metrics or [],
            findings=findings or [],
            environment=environment or {},
            summary=summary or {},
        )

    @classmethod
    def from_analysis(
        cls,
        report: AnalysisReport,
        **kwargs: Any,
    ) -> ExperimentArtifact:
        return cls.from_run(report.run, findings=report.findings, **kwargs)

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        locations = self.manifest.locations
        _write_json(path / "manifest.json", _manifest_to_dict(self.manifest))
        _write_json(path / locations.trace, _runs_to_trace_payload(self.runs))
        _write_json(path / locations.tasks, {"tasks": [asdict(task) for task in self.task_results]})
        _write_json(
            path / locations.quality,
            {"metrics": [asdict(metric) for metric in self.quality_metrics]},
        )
        _write_json(
            path / locations.findings,
            {"findings": [_finding_to_dict(f) for f in self.findings]},
        )
        _write_json(path / locations.environment, self.environment)
        _write_json(path / locations.summary, self.summary)

    def runs_for_comparison(self) -> list[AgentRun]:
        return [_with_artifact_quality(run, self) for run in self.runs]


def is_artifact_path(path: Path) -> bool:
    return path.is_dir() and (
        (path / "manifest.json").is_file() or _latest_checkpoint_path(path) is not None
    )


def load_artifact(path: Path) -> ExperimentArtifact:
    if not path.is_dir():
        raise ArtifactError(f"artifact path is not a directory: {path}")
    if not (path / "manifest.json").is_file():
        checkpoint_path = _latest_checkpoint_path(path)
        if checkpoint_path is None:
            raise ArtifactError("missing artifact file: manifest.json")
        return _mark_recovered_checkpoint(load_artifact(checkpoint_path), checkpoint_path)
    manifest = _parse_manifest(_read_json(path / "manifest.json"))
    _check_schema_version(manifest.artifact_schema_version)
    base = path.resolve()
    locations = manifest.locations
    trace_path = _safe_child(base, locations.trace)
    tasks_path = _safe_child(base, locations.tasks)
    quality_path = _safe_child(base, locations.quality)
    findings_path = _safe_child(base, locations.findings)
    environment_path = _safe_child(base, locations.environment)
    summary_path = _safe_child(base, locations.summary)
    runs = _load_runs(trace_path)
    return ExperimentArtifact(
        manifest=manifest,
        runs=runs,
        task_results=_parse_tasks(_read_optional_json(tasks_path, {"tasks": []})),
        quality_metrics=_parse_quality_metrics(_read_optional_json(quality_path, {"metrics": []})),
        findings=_parse_findings(_read_optional_json(findings_path, {"findings": []})),
        environment=_dict(_read_optional_json(environment_path, {}), "environment"),
        summary=_dict(_read_optional_json(summary_path, {}), "summary"),
    )


def analyze_artifact(path: Path) -> list[AnalysisReport]:
    artifact = load_artifact(path)
    return [analyze_run(run) for run in artifact.runs_for_comparison()]


def inspect_artifact(path: Path) -> str:
    artifact = load_artifact(path)
    manifest = artifact.manifest
    lines = [
        "AgentPerf Artifact",
        "=" * 50,
        f"Artifact ID: {manifest.artifact_id}",
        f"Schema: {manifest.artifact_schema_version}",
        f"Created: {manifest.created_at}",
        f"Workload: {manifest.workload_id or 'unknown'}",
        f"AgentPerf: {manifest.agentperf_version}",
        f"Framework: {manifest.framework or 'unknown'}",
        f"Agent: {manifest.agent_name or 'unknown'}",
        f"Backend: {manifest.backend or 'none'}",
        f"Model: {manifest.model or 'unknown'}",
        f"Serving telemetry: {'yes' if manifest.serving_telemetry else 'no'}",
        f"Status: {manifest.status}",
        f"Runs: {len(artifact.runs)}",
        f"Tasks: {len(artifact.task_results) or manifest.task_count or 0}",
        "",
        "Quality Metrics",
        "-" * 50,
    ]
    if artifact.quality_metrics:
        for metric in artifact.quality_metrics:
            suffix = f" tolerance={metric.tolerance}" if metric.tolerance is not None else ""
            lines.append(f"{metric.name}: {metric.value} ({metric.aggregation}){suffix}")
    else:
        lines.append("none")
    lines.extend(["", "Stored Findings", "-" * 50])
    if artifact.findings:
        for finding in artifact.findings:
            lines.append(f"[{finding.severity}] {finding.id}: {finding.title}")
    else:
        lines.append("none")
    return "\n".join(lines)


def _agentperf_version() -> str:
    try:
        return version("agentperf")
    except PackageNotFoundError:
        return "0+unknown"


def _metadata_str(run: AgentRun, key: str) -> str | None:
    value = run.metadata.get(key)
    return str(value) if value is not None else None


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArtifactError(f"missing artifact file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"invalid JSON in {path.name}: {exc}") from exc


def _read_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return _read_json(path)


def _latest_checkpoint_path(path: Path) -> Path | None:
    root = path / ".agentperf_checkpoints"
    latest_path = root / "latest.json"
    if not latest_path.is_file():
        return None
    try:
        latest = _dict(_read_json(latest_path), "checkpoint latest")
        checkpoint = _required_str(latest, "checkpoint", "checkpoint latest")
        child = _safe_child(root.resolve(), checkpoint)
    except ArtifactError:
        return None
    if not (child / "manifest.json").is_file():
        return None
    return child


def _mark_recovered_checkpoint(
    artifact: ExperimentArtifact,
    checkpoint_path: Path,
) -> ExperimentArtifact:
    metadata = {
        **artifact.manifest.metadata,
        "capture_state": "RECOVERED_FROM_CHECKPOINT",
        "checkpoint_path": checkpoint_path.name,
    }
    summary = {
        **artifact.summary,
        "capture_state": "RECOVERED_FROM_CHECKPOINT",
        "checkpoint_path": checkpoint_path.name,
    }
    return replace(
        artifact,
        manifest=replace(artifact.manifest, metadata=metadata),
        summary=summary,
    )


def _safe_child(base: Path, relative: str) -> Path:
    child = (base / relative).resolve()
    if base != child and base not in child.parents:
        raise ArtifactError(f"artifact location escapes bundle directory: {relative}")
    return child


def _check_schema_version(schema_version: int) -> None:
    if schema_version != ARTIFACT_SCHEMA_VERSION:
        raise ArtifactError(
            f"unsupported artifact schema version {schema_version}; "
            f"this AgentPerf version supports {ARTIFACT_SCHEMA_VERSION}"
        )


def _manifest_to_dict(manifest: ArtifactManifest) -> dict[str, Any]:
    data = asdict(manifest)
    data["schema_version"] = data.pop("artifact_schema_version")
    return data


def _parse_manifest(data: Any) -> ArtifactManifest:
    root = _dict(data, "manifest")
    version_value = root.get("schema_version", root.get("artifact_schema_version"))
    if not isinstance(version_value, int):
        raise ArtifactError("manifest schema_version must be an integer")
    locations = _parse_locations(root.get("locations"))
    return ArtifactManifest(
        artifact_schema_version=version_value,
        artifact_id=_required_str(root, "artifact_id", "manifest"),
        created_at=_required_str(root, "created_at", "manifest"),
        agentperf_version=_required_str(root, "agentperf_version", "manifest"),
        workload_id=_optional_str(root, "workload_id"),
        framework=_optional_str(root, "framework"),
        agent_name=_optional_str(root, "agent_name"),
        backend=_optional_str(root, "backend"),
        model=_optional_str(root, "model"),
        task_count=_optional_int(root, "task_count"),
        serving_telemetry=bool(root.get("serving_telemetry", False)),
        status=_artifact_status(root.get("status", "COMPLETE")),
        locations=locations,
        metadata=_dict(root.get("metadata", {}), "manifest.metadata"),
    )


def _parse_locations(data: Any) -> ArtifactLocation:
    if data is None:
        return ArtifactLocation()
    root = _dict(data, "manifest.locations")
    return ArtifactLocation(
        trace=_optional_str(root, "trace") or "trace.json",
        tasks=_optional_str(root, "tasks") or "tasks.json",
        quality=_optional_str(root, "quality") or "quality.json",
        findings=_optional_str(root, "findings") or "findings.json",
        environment=_optional_str(root, "environment") or "environment.json",
        summary=_optional_str(root, "summary") or "summary.json",
    )


def _runs_to_trace_payload(runs: list[AgentRun]) -> dict[str, Any]:
    if len(runs) == 1:
        return _run_to_trace_payload(runs[0])
    return {"runs": [_run_to_trace_payload(run) for run in runs]}


def _run_to_trace_payload(run: AgentRun) -> dict[str, Any]:
    return {
        "schema_version": run.schema_version,
        "synthetic": run.synthetic,
        "agent_run": {
            "agent_run_id": run.agent_run_id,
            "trace_id": run.trace_id,
            "span_id": run.span_id,
            "parent_span_id": run.parent_span_id,
            "name": run.name,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "metadata": run.metadata,
            "steps": [_step_to_dict(step) for step in run.steps],
        },
        "serving_requests": [asdict(request) for request in run.serving_requests],
    }


def _step_to_dict(step: Any) -> dict[str, Any]:
    return {
        "agent_step_id": step.agent_step_id,
        "trace_id": step.trace_id,
        "span_id": step.span_id,
        "parent_span_id": step.parent_span_id,
        "started_at": step.started_at,
        "ended_at": step.ended_at,
        "metadata": step.metadata,
        "llm_calls": [_llm_call_to_dict(call) for call in step.llm_calls],
        "tool_calls": [asdict(tool_call) for tool_call in step.tool_calls],
    }


def _llm_call_to_dict(call: Any) -> dict[str, Any]:
    data = asdict(call)
    data["prompt"] = data.pop("prompt_components")
    return data


def _load_runs(path: Path) -> list[AgentRun]:
    data = _read_json(path)
    try:
        if isinstance(data, dict) and "runs" in data:
            raw_runs = data["runs"]
            if not isinstance(raw_runs, list):
                raise TraceParseError("artifact trace runs must be a list")
            return [parse_agentperf_trace(item) for item in raw_runs]
        if isinstance(data, list):
            return [parse_agentperf_trace(item) for item in data]
        if isinstance(data, dict):
            return [parse_agentperf_trace(data)]
    except TraceParseError as exc:
        raise ArtifactError(str(exc)) from exc
    raise ArtifactError("artifact trace must be a trace object, run list, or workload object")


def _parse_tasks(data: Any) -> list[TaskResult]:
    root = _dict(data, "tasks")
    raw_tasks = root.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise ArtifactError("tasks must be a list")
    return [_parse_task(item) for item in raw_tasks]


def _parse_task(data: Any) -> TaskResult:
    root = _dict(data, "task")
    quality_score = root.get("quality_score")
    return TaskResult(
        task_id=_required_str(root, "task_id", "task"),
        execution_id=_optional_str(root, "execution_id"),
        passed=_optional_bool(root, "passed"),
        quality_score=float(quality_score) if isinstance(quality_score, int | float) else None,
        evaluator=_optional_str(root, "evaluator"),
        input_tokens=_optional_int(root, "input_tokens"),
        output_tokens=_optional_int(root, "output_tokens"),
        duration_ms=_optional_float(root, "duration_ms"),
        client_latency_ms=_optional_float(root, "client_latency_ms"),
        error=_optional_str(root, "error"),
        status=_optional_str(root, "status"),
        agent_run_ids=_str_list(root.get("agent_run_ids", []), "agent_run_ids"),
        quality_metrics=_parse_metric_list(root.get("quality_metrics", [])),
        metadata=_dict(root.get("metadata", {}), "task.metadata"),
    )


def _parse_quality_metrics(data: Any) -> list[QualityMetric]:
    root = _dict(data, "quality")
    return _parse_metric_list(root.get("metrics", []))


def _parse_metric_list(data: Any) -> list[QualityMetric]:
    if not isinstance(data, list):
        raise ArtifactError("quality metrics must be a list")
    return [_parse_quality_metric(item) for item in data]


def _parse_quality_metric(data: Any) -> QualityMetric:
    root = _dict(data, "quality metric")
    direction = str(root.get("direction", "higher_is_better"))
    if direction not in {"higher_is_better", "lower_is_better", "neutral"}:
        raise ArtifactError("quality metric direction is invalid")
    value = root.get("value")
    if not isinstance(value, int | float | bool | str):
        raise ArtifactError("quality metric value must be numeric, boolean, or string")
    return QualityMetric(
        name=_required_str(root, "name", "quality metric"),
        value=value,
        direction=cast(MetricDirection, direction),
        aggregation=_optional_str(root, "aggregation") or "mean",
        tolerance=_optional_float(root, "tolerance"),
        metadata=_dict(root.get("metadata", {}), "quality metric.metadata"),
    )


def _parse_findings(data: Any) -> list[Finding]:
    root = _dict(data, "findings")
    raw_findings = root.get("findings", [])
    if not isinstance(raw_findings, list):
        raise ArtifactError("findings must be a list")
    return [_parse_finding(item) for item in raw_findings]


def _parse_finding(data: Any) -> Finding:
    root = _dict(data, "finding")
    provenance = _dict(root.get("provenance", {}), "finding.provenance")
    return Finding(
        id=_required_str(root, "id", "finding"),
        severity=_severity(root.get("severity")),
        title=_required_str(root, "title", "finding"),
        summary=_required_str(root, "summary", "finding"),
        evidence=_dict(root.get("evidence", {}), "finding.evidence"),
        affected_spans=_str_list(root.get("affected_spans", []), "affected_spans"),
        recommendation=_required_str(root, "recommendation", "finding"),
        confidence=_confidence(root.get("confidence")),
        validation_plan=_str_list(root.get("validation_plan", []), "validation_plan"),
        provenance=FindingProvenance(
            agent_span_ids=_str_list(provenance.get("agent_span_ids", []), "agent_span_ids"),
            llm_call_ids=_str_list(provenance.get("llm_call_ids", []), "llm_call_ids"),
            llm_request_ids=_str_list(provenance.get("llm_request_ids", []), "llm_request_ids"),
            serving_request_ids=_str_list(
                provenance.get("serving_request_ids", []),
                "serving_request_ids",
            ),
            raw_metrics=_dict(provenance.get("raw_metrics", {}), "raw_metrics"),
            derived_metrics=_dict(provenance.get("derived_metrics", {}), "derived_metrics"),
            notes=_str_list(provenance.get("notes", []), "notes"),
        ),
        recommendation_contract=_parse_recommendation_contract(
            root.get("recommendation_contract")
        ),
    )


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    return asdict(finding)


def _parse_recommendation_contract(data: Any) -> RecommendationContract | None:
    if data is None:
        return None
    root = _dict(data, "finding.recommendation_contract")
    evidence_level = root.get("evidence_level")
    return RecommendationContract(
        objective=_required_str(root, "objective", "recommendation_contract"),
        applicability=_recommendation_applicability(root.get("applicability")),
        interventions=_str_list(root.get("interventions", []), "interventions"),
        expected_metric_changes=[
            _parse_expected_metric_change(item)
            for item in _list(root.get("expected_metric_changes", []), "expected_metric_changes")
        ],
        risks=_str_list(root.get("risks", []), "risks"),
        verification_requirements=_str_list(
            root.get("verification_requirements", []),
            "verification_requirements",
        ),
        quality_requirement=(
            None
            if root.get("quality_requirement") is None
            else _optional_str(root, "quality_requirement")
        )
        if "quality_requirement" in root
        else "within_configured_tolerance",
        evidence_level=(
            _confidence(evidence_level) if evidence_level is not None else None
        ),
        schema_version=_optional_int(root, "schema_version") or 1,
    )


def _parse_expected_metric_change(data: Any) -> ExpectedMetricChange:
    root = _dict(data, "expected_metric_change")
    return ExpectedMetricChange(
        metric=_required_str(root, "metric", "expected_metric_change"),
        direction=_expected_metric_direction(root.get("direction")),
        required=bool(root.get("required", True)),
        rationale=_optional_str(root, "rationale") or "",
    )


def _with_artifact_quality(run: AgentRun, artifact: ExperimentArtifact) -> AgentRun:
    metadata = dict(run.metadata)
    metadata.setdefault("workload_id", artifact.manifest.workload_id)
    metadata.setdefault("framework", artifact.manifest.framework)
    metadata.setdefault("backend", artifact.manifest.backend)
    metadata.setdefault("model", artifact.manifest.model)
    if artifact.manifest.workload_id:
        metadata.setdefault("workload_item_id", artifact.manifest.workload_id)
    task = _task_for_run(run, artifact.task_results)
    if task is not None:
        metadata.setdefault("task_id", task.task_id)
        metadata.setdefault("execution_id", task.execution_id)
        if task.quality_score is not None or task.passed is not None:
            metadata.setdefault(
                "quality",
                {
                    "score": task.quality_score,
                    "passed": task.passed,
                    "evaluator": task.evaluator,
                },
            )
    aggregate_quality = _aggregate_quality_metadata(artifact.quality_metrics)
    if aggregate_quality:
        metadata.setdefault("quality", aggregate_quality)
    cleaned_metadata = {key: value for key, value in metadata.items() if value is not None}
    return replace(run, metadata=cleaned_metadata)


def _task_for_run(run: AgentRun, tasks: list[TaskResult]) -> TaskResult | None:
    for task in tasks:
        if run.agent_run_id in task.agent_run_ids:
            return task
    if len(tasks) == 1 and not tasks[0].agent_run_ids:
        return tasks[0]
    return None


def _aggregate_quality_metadata(metrics: list[QualityMetric]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for metric in metrics:
        if metric.name in {"mean_score", "score", "quality_score", "rule_score"}:
            result["mean_score"] = metric.value
        if metric.name in {"pass_rate", "task_success_rate"}:
            result["pass_rate"] = metric.value
    return result


def _required_str(data: dict[str, Any], key: str, owner: str) -> str:
    value = data.get(key)
    if value is None or str(value) == "":
        raise ArtifactError(f"{owner} missing required field: {key}")
    return str(value)


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return str(value) if value is not None else None


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ArtifactError(f"{key} must be an integer")
    return value


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ArtifactError(f"{key} must be numeric")
    return float(value)


def _optional_bool(data: dict[str, Any], key: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ArtifactError(f"{key} must be a boolean")
    return value


def _dict(data: Any, name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ArtifactError(f"{name} must be an object")
    return data


def _str_list(data: Any, name: str) -> list[str]:
    if not isinstance(data, list):
        raise ArtifactError(f"{name} must be a list")
    return [str(item) for item in data]


def _list(data: Any, name: str) -> list[Any]:
    if not isinstance(data, list):
        raise ArtifactError(f"{name} must be a list")
    return data


def _severity(value: Any) -> Any:
    text = str(value)
    if text not in {"LOW", "MEDIUM", "HIGH"}:
        raise ArtifactError("finding severity must be LOW, MEDIUM, or HIGH")
    return text


def _confidence(value: Any) -> Any:
    text = str(value)
    if text not in {"LOW", "MEDIUM", "HIGH"}:
        raise ArtifactError("finding confidence must be LOW, MEDIUM, or HIGH")
    return text


def _recommendation_applicability(value: Any) -> Any:
    text = str(value)
    if text not in {"OBSERVATION_ONLY", "CONDITIONAL", "INVESTIGATE", "ACTIONABLE"}:
        raise ArtifactError("recommendation applicability is invalid")
    return text


def _expected_metric_direction(value: Any) -> Any:
    text = str(value)
    if text not in {
        "DECREASE",
        "INCREASE",
        "NO_REGRESSION",
        "RESOLVE_OR_IMPROVE_FINDING",
    }:
        raise ArtifactError("expected metric direction is invalid")
    return text


def _artifact_status(value: Any) -> Any:
    text = str(value)
    if text not in {"COMPLETE", "PARTIAL", "FAILED"}:
        raise ArtifactError("artifact status must be COMPLETE, PARTIAL, or FAILED")
    return text
