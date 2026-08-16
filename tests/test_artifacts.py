from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from agentperf.analyzer import analyze_run
from agentperf.artifacts import (
    ArtifactError,
    ExperimentArtifact,
    load_artifact,
)
from agentperf.cli import main
from agentperf.comparison import compare_paths
from agentperf.schema.artifacts import QualityMetric, TaskResult
from agentperf.schema.trace import AgentRun, parse_agentperf_trace


def test_artifact_save_load_preserves_manifest_quality_environment_and_findings(
    tmp_path: Path,
) -> None:
    run = _run("baseline", task_id="task-1")
    report = analyze_run(run)
    artifact = ExperimentArtifact.from_analysis(
        report,
        artifact_id="artifact-baseline",
        workload_id="workload-baseline",
        task_results=[
            TaskResult(
                task_id="task-1",
                execution_id="exec-1",
                passed=True,
                quality_score=0.95,
                agent_run_ids=["baseline"],
                input_tokens=3500,
            )
        ],
        quality_metrics=[
            QualityMetric(
                name="mean_score",
                value=0.95,
                aggregation="mean",
                tolerance=0.05,
            ),
            QualityMetric(
                name="pass_rate",
                value=1.0,
                aggregation="rate",
                tolerance=0.10,
            ),
        ],
        environment={"backend": "none", "model": "fixture-model"},
        summary={"input_tokens": 3500},
        framework="fixture-framework",
        agent_name="fixture-agent",
        backend="none",
        model="fixture-model",
        serving_telemetry=False,
    )
    path = tmp_path / "artifact"

    artifact.save(path)
    loaded = load_artifact(path)

    assert loaded.manifest.artifact_schema_version == 1
    assert loaded.manifest.artifact_id == "artifact-baseline"
    assert loaded.manifest.framework == "fixture-framework"
    assert loaded.environment["model"] == "fixture-model"
    assert loaded.summary["input_tokens"] == 3500
    assert loaded.task_results[0].quality_score == 0.95
    assert loaded.quality_metrics[0].tolerance == 0.05
    assert any(finding.id == "TOOL_OUTPUT_BLOAT" for finding in loaded.findings)
    assert any(
        finding.recommendation_contract is not None
        and finding.recommendation_contract.applicability == "ACTIONABLE"
        for finding in loaded.findings
    )
    assert loaded.runs_for_comparison()[0].metadata["quality"]["score"] == 0.95


def test_artifact_compare_uses_bundle_quality_for_accept_verdict(tmp_path: Path) -> None:
    baseline_path = _artifact_path(
        tmp_path / "baseline",
        run_id="raw_full",
        mean_score=0.933,
        pass_rate=0.80,
        task_count=10,
        tool_reinjections=5,
    )
    candidate_path = _artifact_path(
        tmp_path / "candidate",
        run_id="dedup_only",
        mean_score=0.908,
        pass_rate=0.70,
        task_count=10,
        tool_reinjections=2,
        client_latency_ms=700,
        serving_ttft_ms=120,
    )

    comparison = compare_paths(baseline_path, candidate_path)

    assert comparison.baseline_id == "shared-workload"
    assert comparison.candidate_id == "shared-workload"
    assert comparison.quality_deltas.baseline_tasks_with_quality == 10
    assert comparison.quality_deltas.passed is True
    assert comparison.acceptance_result.verdict == "ACCEPT"


def test_artifact_compare_rejects_quality_regression(tmp_path: Path) -> None:
    baseline_path = _artifact_path(
        tmp_path / "baseline",
        run_id="baseline",
        mean_score=0.93,
        pass_rate=0.80,
        task_count=10,
    )
    candidate_path = _artifact_path(
        tmp_path / "candidate",
        run_id="candidate",
        mean_score=0.70,
        pass_rate=0.40,
        task_count=10,
        tool_reinjections=1,
    )

    comparison = compare_paths(baseline_path, candidate_path)

    assert comparison.acceptance_result.verdict == "REJECT_QUALITY_REGRESSION"


def test_unknown_artifact_schema_version_fails_clearly(tmp_path: Path) -> None:
    path = _artifact_path(tmp_path / "artifact")
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        load_artifact(path)
    except ArtifactError as exc:
        assert "unsupported artifact schema version" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ArtifactError")


def test_artifact_rejects_absolute_or_escaping_locations(tmp_path: Path) -> None:
    path = _artifact_path(tmp_path / "artifact")
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["locations"]["trace"] = "../trace.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        load_artifact(path)
    except ArtifactError as exc:
        assert "escapes bundle directory" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ArtifactError")


def test_artifact_bundle_is_portable_after_copy(tmp_path: Path) -> None:
    source = _artifact_path(tmp_path / "source")
    copied = tmp_path / "copied" / "bundle"
    shutil.copytree(source, copied)

    loaded = load_artifact(copied)

    assert loaded.manifest.artifact_id == "artifact-source"
    assert loaded.runs_for_comparison()[0].agent_run_id == "source"


def test_cli_analyze_inspect_and_compare_artifacts(
    tmp_path: Path,
    capsys: Any,
) -> None:
    baseline = _artifact_path(tmp_path / "baseline", mean_score=1.0, pass_rate=1.0)
    candidate = _artifact_path(
        tmp_path / "candidate",
        mean_score=1.0,
        pass_rate=1.0,
        tool_reinjections=1,
    )

    inspect_code = main(["inspect", str(baseline)])
    inspect_output = capsys.readouterr()
    analyze_code = main(["analyze", str(baseline)])
    analyze_output = capsys.readouterr()
    compare_code = main(["compare", str(baseline), str(candidate)])
    compare_output = capsys.readouterr()

    assert inspect_code == 0
    assert "AgentPerf Artifact" in inspect_output.out
    assert analyze_code == 0
    assert "AgentPerf Report" in analyze_output.out
    assert compare_code == 0
    assert "ACCEPT" in compare_output.out


def test_compare_artifacts_reports_task_result_coverage_for_single_run_workloads(
    tmp_path: Path,
) -> None:
    baseline = _artifact_path(tmp_path / "baseline", task_count=3)
    candidate = _artifact_path(tmp_path / "candidate", task_count=3, tool_reinjections=1)

    comparison = compare_paths(baseline, candidate)

    assert comparison.matched_tasks == ["task-1", "task-2", "task-3"]
    assert comparison.unmatched_baseline_tasks == []
    assert comparison.unmatched_candidate_tasks == []
    assert comparison.metadata["matched_run_keys"] == ["shared-workload"]


def test_raw_trace_compare_backward_compatibility(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps(_trace("baseline", task_id="task", score=1.0)), encoding="utf-8")
    candidate.write_text(
        json.dumps(_trace("candidate", task_id="task", score=1.0, tool_reinjections=1)),
        encoding="utf-8",
    )

    comparison = compare_paths(baseline, candidate)

    assert comparison.matched_tasks == ["task"]
    assert comparison.acceptance_result.verdict == "ACCEPT"


def _artifact_path(
    path: Path,
    *,
    run_id: str | None = None,
    mean_score: float = 1.0,
    pass_rate: float = 1.0,
    task_count: int = 1,
    tool_reinjections: int = 5,
    client_latency_ms: float = 1000,
    serving_ttft_ms: float = 220,
) -> Path:
    resolved_run_id = run_id or path.name
    run = _run(
        resolved_run_id,
        task_id=None,
        tool_reinjections=tool_reinjections,
        client_latency_ms=client_latency_ms,
        serving_ttft_ms=serving_ttft_ms,
    )
    run = replace(run, metadata={**run.metadata, "workload_item_id": "shared-workload"})
    artifact = ExperimentArtifact.from_run(
        run,
        artifact_id=f"artifact-{resolved_run_id}",
        workload_id="shared-workload",
        task_results=[
            TaskResult(
                task_id=f"task-{index + 1}",
                passed=index < round(pass_rate * task_count),
                quality_score=mean_score,
                agent_run_ids=[resolved_run_id],
            )
            for index in range(task_count)
        ],
        quality_metrics=[
            QualityMetric(
                name="mean_score",
                value=mean_score,
                aggregation="mean",
                tolerance=0.05,
            ),
            QualityMetric(
                name="pass_rate",
                value=pass_rate,
                aggregation="rate",
                tolerance=0.10,
            ),
        ],
        framework="fixture",
        agent_name="fixture-agent",
        backend="vllm" if run.serving_requests else None,
        model="fixture-model",
        serving_telemetry=bool(run.serving_requests),
        summary={"task_count": task_count},
    )
    artifact.save(path)
    return path


def _run(
    run_id: str,
    *,
    task_id: str | None = None,
    tool_reinjections: int = 5,
    client_latency_ms: float = 1000,
    serving_ttft_ms: float = 220,
) -> AgentRun:
    return parse_agentperf_trace(
        _trace(
            run_id,
            task_id=task_id,
            tool_reinjections=tool_reinjections,
            client_latency_ms=client_latency_ms,
            serving_ttft_ms=serving_ttft_ms,
        )
    )


def _trace(
    run_id: str,
    *,
    task_id: str | None = None,
    score: float | None = None,
    passed: bool | None = None,
    tool_reinjections: int = 5,
    extra_other_tokens: int = 0,
    client_latency_ms: float = 1000.0,
    serving_ttft_ms: float = 220.0,
    cached_tokens: int | None = 0,
    cache_miss_tokens: int | None = 800,
    serving: bool = True,
    framework: str = "fixture",
) -> dict[str, object]:
    tool_text = " ".join(f"evidence{i}" for i in range(650))
    other_text = " ".join(f"other{i}" for i in range(extra_other_tokens))
    metadata: dict[str, object] = {"framework": framework}
    if task_id is not None:
        metadata["task_id"] = task_id
    if score is not None:
        metadata["quality"] = {"score": score, "passed": bool(passed)}
    steps: list[dict[str, object]] = []
    llm_call_count = max(1, tool_reinjections)
    for index in range(llm_call_count):
        prompt: list[dict[str, object]] = [{"name": "system", "text": "You are a careful agent."}]
        if index < tool_reinjections:
            prompt.append(
                {
                    "name": "tool_result",
                    "text": tool_text,
                    "metadata": {"source_tool_call_ids": ["search-1"]},
                }
            )
        if other_text:
            prompt.append({"name": "other_context", "text": other_text})
        step: dict[str, object] = {
            "agent_step_id": f"step-{index + 1}",
            "llm_calls": [
                {
                    "llm_call_id": f"llm-{index + 1}",
                    "llm_request_id": f"req-{index + 1}",
                    "model": "fixture-model",
                    "prompt": prompt,
                    "input_tokens": (
                        (700 if index < tool_reinjections else 50) + extra_other_tokens
                    ),
                    "output_tokens": 10,
                    "tokenization_mode": "APPROXIMATE",
                    "metadata": {"latency_ms": client_latency_ms},
                }
            ],
        }
        if index == 0:
            step["tool_calls"] = [
                {
                    "tool_call_id": "search-1",
                    "name": "search",
                    "latency_ms": 25,
                    "output": tool_text,
                }
            ]
        steps.append(step)
    serving_requests: list[dict[str, object]] = []
    if serving:
        serving_requests = [
            {
                "serving_request_id": f"srv-{index + 1}",
                "llm_request_id": f"req-{index + 1}",
                "queue_latency_ms": 5,
                "prefill_path_latency_ms": serving_ttft_ms,
                "decode_latency_ms": 50,
                "ttft_ms": serving_ttft_ms,
                "input_tokens": 700 + extra_other_tokens,
                "output_tokens": 10,
                "prefix_cache_hit_tokens": cached_tokens,
                "prefix_cache_miss_tokens": cache_miss_tokens,
            }
            for index in range(llm_call_count)
        ]
    return {
        "schema_version": "agentperf.trace.v1",
        "agent_run": {
            "agent_run_id": run_id,
            "metadata": metadata,
            "steps": steps,
        },
        "serving_requests": serving_requests,
    }
