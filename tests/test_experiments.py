from __future__ import annotations

from pathlib import Path

import pytest

from agentperf.artifacts import load_artifact
from agentperf.comparison import compare_paths
from agentperf.experiments import ExperimentSession, QualityResult
from agentperf.instrumentation import current_recorder
from agentperf.schema.artifacts import QualityMetric


def test_experiment_session_finalizes_complete_artifact_with_task_quality(
    tmp_path: Path,
) -> None:
    output = tmp_path / "complete"

    with ExperimentSession(
        output_path=output,
        artifact_id="complete-artifact",
        workload_id="fixture-workload",
        expected_task_count=2,
        framework="fixture",
        agent_name="fixture-agent",
        backend="none",
        model="fixture-model",
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    ) as experiment:
        for task_id in ("task-1", "task-2"):
            experiment.run_task(
                task_id,
                {"id": task_id},
                _successful_task,
                evaluator=_score_success,
            )

    artifact = load_artifact(output)

    assert artifact.manifest.status == "COMPLETE"
    assert artifact.manifest.task_count == 2
    assert len(artifact.task_results) == 2
    assert artifact.quality_metrics[0].name == "mean_score"
    assert artifact.quality_metrics[0].value == 1.0
    assert artifact.summary["llm_calls"] == 2
    component_accounting = artifact.summary["component_accounting"]
    assert component_accounting["total_processed_tokens"] > 0
    assert component_accounting["processed_tokens_by_component"]["user"] == (
        component_accounting["total_processed_tokens"]
    )
    assert artifact.findings == []
    assert artifact.environment["agentperf_version"]
    assert artifact.environment["python"]


def test_experiment_session_records_failed_task_without_corrupting_artifact(
    tmp_path: Path,
) -> None:
    output = tmp_path / "failed"

    with ExperimentSession(
        output_path=output,
        artifact_id="failed-artifact",
        workload_id="failed-workload",
        expected_task_count=1,
    ) as experiment:
        result = experiment.run_task(
            "task-fail",
            {"id": "task-fail"},
            _failing_task,
            reraise=False,
        )

    artifact = load_artifact(output)

    assert result is None
    assert artifact.manifest.status == "FAILED"
    assert artifact.task_results[0].passed is False
    assert artifact.task_results[0].error is not None


def test_experiment_session_marks_interrupted_or_short_run_partial(tmp_path: Path) -> None:
    output = tmp_path / "partial"

    with ExperimentSession(
        output_path=output,
        artifact_id="partial-artifact",
        workload_id="partial-workload",
        expected_task_count=2,
    ) as experiment:
        experiment.run_task("task-1", {"id": "task-1"}, _successful_task, evaluator=_score_success)

    artifact = load_artifact(output)

    assert artifact.manifest.status == "PARTIAL"
    assert artifact.summary["recorded_task_count"] == 1
    assert artifact.summary["expected_task_count"] == 2


def test_generated_artifacts_compare_accept_with_task_latency_and_quality(
    tmp_path: Path,
) -> None:
    baseline = _run_session_artifact(
        tmp_path / "baseline",
        artifact_id="baseline",
        task_scores=[1.0, 1.0],
        calls_per_task=3,
        input_tokens=1000,
        client_latency_ms=1000,
    )
    candidate = _run_session_artifact(
        tmp_path / "candidate",
        artifact_id="candidate",
        task_scores=[1.0, 0.95],
        calls_per_task=1,
        input_tokens=400,
        client_latency_ms=600,
    )

    comparison = compare_paths(baseline, candidate)

    assert comparison.acceptance_result.verdict == "ACCEPT"
    assert comparison.quality_deltas.passed is True
    assert comparison.latency_deltas.client_p95_ms.baseline is not None
    assert comparison.latency_deltas.client_p95_ms.candidate is not None
    assert comparison.latency_deltas.client_p95_ms.delta is not None
    assert comparison.latency_deltas.client_p95_ms.delta < 0


def test_generated_artifacts_compare_rejects_task_success_regression(
    tmp_path: Path,
) -> None:
    baseline = _run_session_artifact(
        tmp_path / "baseline",
        artifact_id="baseline",
        task_scores=[1.0, 1.0],
        calls_per_task=3,
        input_tokens=1000,
        client_latency_ms=1000,
    )
    candidate = _run_session_artifact(
        tmp_path / "candidate",
        artifact_id="candidate",
        task_scores=[1.0, 0.2],
        calls_per_task=1,
        input_tokens=300,
        client_latency_ms=400,
    )

    comparison = compare_paths(baseline, candidate)

    assert comparison.acceptance_result.verdict == "REJECT_QUALITY_REGRESSION"


def test_compare_warns_for_partial_artifact_task_coverage(tmp_path: Path) -> None:
    baseline = _run_session_artifact(
        tmp_path / "baseline",
        artifact_id="baseline",
        task_scores=[1.0, 1.0],
        expected_task_count=2,
    )
    candidate = _run_session_artifact(
        tmp_path / "candidate",
        artifact_id="candidate",
        task_scores=[1.0],
        expected_task_count=2,
        calls_per_task=1,
        input_tokens=200,
    )

    comparison = compare_paths(baseline, candidate)

    assert any("status is PARTIAL" in warning for warning in comparison.warnings)
    assert any("expected task results" in warning for warning in comparison.warnings)
    assert comparison.acceptance_result.verdict == "INCONCLUSIVE"


def test_finalization_failure_does_not_publish_incomplete_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "publish-target"
    session = ExperimentSession(
        output_path=output,
        artifact_id="publish-failure",
        workload_id="publish-failure",
        expected_task_count=1,
    )
    session.record_task_result(
        task_id="task-1",
        passed=True,
        quality_score=1.0,
        status="COMPLETE",
    )

    def fail_to_validate(path: Path) -> None:
        raise RuntimeError(f"cannot validate {path.name}")

    monkeypatch.setattr("agentperf.experiments.load_artifact", fail_to_validate)

    with pytest.raises(RuntimeError, match="cannot validate"):
        session.finalize()

    assert not output.exists()
    assert not session._finished
    tmp_dirs = list(tmp_path.glob(".publish-target.tmp-*"))
    assert len(tmp_dirs) == 1


def test_failed_replacement_leaves_existing_artifact_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _run_session_artifact(
        tmp_path / "existing",
        artifact_id="existing-good",
        task_scores=[1.0],
    )
    original = load_artifact(output)
    replacement = ExperimentSession(
        output_path=output,
        artifact_id="replacement",
        workload_id="replacement",
        expected_task_count=1,
    )
    replacement.record_task_result(
        task_id="task-1",
        passed=True,
        quality_score=1.0,
        status="COMPLETE",
    )

    def fail_to_validate(path: Path) -> None:
        raise RuntimeError(f"cannot validate {path.name}")

    monkeypatch.setattr("agentperf.experiments.load_artifact", fail_to_validate)

    with pytest.raises(RuntimeError, match="cannot validate"):
        replacement.finalize()

    preserved = load_artifact(output)
    assert preserved.manifest.artifact_id == original.manifest.artifact_id
    assert preserved.manifest.workload_id == original.manifest.workload_id


def _run_session_artifact(
    output_path: Path,
    *,
    artifact_id: str,
    task_scores: list[float],
    expected_task_count: int | None = None,
    calls_per_task: int = 2,
    input_tokens: int = 800,
    client_latency_ms: float = 500,
) -> Path:
    with ExperimentSession(
        output_path=output_path,
        artifact_id=artifact_id,
        workload_id="shared-session-workload",
        expected_task_count=expected_task_count or len(task_scores),
        framework="fixture",
        agent_name="fixture-agent",
        backend="none",
        model="fixture-model",
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    ) as experiment:
        for index, score in enumerate(task_scores, start=1):
            task_id = f"task-{index}"
            for call_index in range(calls_per_task):
                experiment.recorder.record_llm_call(
                    llm_call_id=f"{task_id}-llm-{call_index}",
                    prompt_components={"user": " ".join(["token"] * input_tokens)},
                    input_tokens=input_tokens,
                    output_tokens=10,
                )
            experiment.record_task_result(
                task_id=task_id,
                passed=score >= 0.8,
                quality_score=score,
                quality_metrics=[
                    QualityMetric(name="answer_score", value=score, aggregation="mean")
                ],
                evaluator="fixture-evaluator@1",
                client_latency_ms=client_latency_ms,
                status="COMPLETE",
            )
    return output_path


def _successful_task(task: dict[str, str]) -> str:
    recorder = current_recorder()
    assert recorder is not None
    recorder.record_llm_call(
        llm_call_id=f"{task['id']}-llm",
        prompt_components={"user": task["id"]},
        input_tokens=100,
        output_tokens=10,
    )
    return "ok"


def _failing_task(task: dict[str, str]) -> str:
    raise RuntimeError(f"failed {task['id']}")


def _score_success(task: dict[str, str], result: str) -> QualityResult:
    return QualityResult(
        score=1.0 if result == "ok" else 0.0,
        passed=result == "ok",
        evaluator_name="fixture-evaluator",
        evaluator_version="1",
        metrics=[QualityMetric(name="answer_score", value=1.0)],
    )
