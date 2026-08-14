from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool
from agentperf.completeness import assess_path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/m20_generalization_report.py"
SPEC = importlib.util.spec_from_file_location("m20_generalization_report", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
ReviewDataError = MODULE.ReviewDataError
aggregate_reviews = MODULE.aggregate_reviews
load_review_data = MODULE.load_review_data
render_summary = MODULE.render_summary
validate_review_data = MODULE.validate_review_data


def test_m20_review_dataset_validates_and_aggregates() -> None:
    data = load_review_data(ROOT / "docs/m20_finding_reviews.json")

    aggregate = aggregate_reviews(data)

    assert aggregate["workloads"] == 3
    assert aggregate["tasks"] == 19
    assert aggregate["findings_reviewed"] == 3
    assert aggregate["counts"]["ACTIONABLE"] == 1
    assert aggregate["counts"]["EXPECTED_STRUCTURAL"] == 1
    assert aggregate["counts"]["VALID_NON_ACTIONABLE"] == 1
    assert aggregate["counts"]["FALSE_POSITIVE"] == 0


def test_m20_summary_renders_matrix_and_review_counts() -> None:
    data = load_review_data(ROOT / "docs/m20_finding_reviews.json")

    output = render_summary(data)

    assert "AgentPerf M20 Generalization Summary" in output
    assert "coding_agent_mini_swe" in output
    assert "tool_heavy_research_support" in output
    assert "openai_agents_support_triage" in output
    assert "ACTIONABLE                       1" in output
    assert "FALSE_POSITIVE                   0" in output


def test_m20_review_rejects_unknown_classification() -> None:
    data = _minimal_review_data()
    data["workloads"][0]["reviews"][0]["classification"] = "INTERESTING"

    try:
        validate_review_data(data)
    except ReviewDataError as exc:
        assert "unsupported classification" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected invalid classification to fail")


def test_m20_review_rejects_unknown_task_or_finding_reference() -> None:
    data = _minimal_review_data()
    data["workloads"][0]["reviews"][0]["task_id"] = "missing-task"

    try:
        validate_review_data(data)
    except ReviewDataError as exc:
        assert "unknown task_id" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected invalid task reference to fail")

    data = _minimal_review_data()
    data["workloads"][0]["reviews"][0]["finding_id"] = "MISSING_FINDING"
    try:
        validate_review_data(data)
    except ReviewDataError as exc:
        assert "unknown finding_id" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected invalid finding reference to fail")


def test_m20_zero_finding_workload_does_not_break_aggregation() -> None:
    data = _minimal_review_data()
    workload = data["workloads"][0]
    workload["finding_ids"] = []
    workload["reviews"] = []

    validate_review_data(data)
    aggregate = aggregate_reviews(data)

    assert aggregate["findings_reviewed"] == 0
    assert "no findings reviewed" in render_summary(data)


def test_variable_execution_shapes_preserve_completeness_denominators(tmp_path: Path) -> None:
    output = tmp_path / "artifact"
    with ExperimentSession(
        output_path=output,
        artifact_id="m20-variable-shapes",
        workload_id="m20-variable-shapes",
        expected_task_count=2,
        framework="framework-free",
        backend="deterministic-local",
        model="fake-model",
    ) as experiment:
        with trace_run(task_id="short-task"), trace_llm(
            model="fake-model",
            components={"user": "short"},
        ) as call:
            call.record_response(output="done", input_tokens=1, output_tokens=1)
        experiment.record_task_result(
            task_id="short-task",
            passed=True,
            quality_score=1.0,
            status="COMPLETE",
        )

        with trace_run(task_id="long-task"):
            for index in range(3):
                with trace_tool(f"lookup-{index}") as tool:
                    tool.record_output(f"tool output {index}")
                with trace_llm(
                    model="fake-model",
                    components={"user": f"long {index}", "tool_result": f"tool output {index}"},
                ) as call:
                    call.record_response(output="done", input_tokens=4, output_tokens=1)
        experiment.record_task_result(
            task_id="long-task",
            passed=False,
            quality_score=0.0,
            status="FAILED",
        )

    report = assess_path(output)

    assert report.artifact_valid is True
    assert report.tasks_observed == 2
    assert report.tasks_with_outcomes == 2
    assert report.tasks_with_quality == 2
    assert report.llm_calls_observed == 4
    assert report.tool_calls_observed == 3
    assert report.agent_profiling_readiness == "READY"
    assert report.cross_layer_readiness == "NOT_APPLICABLE"


def _minimal_review_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "taxonomy": [
            "ACTIONABLE",
            "VALID_NON_ACTIONABLE",
            "EXPECTED_STRUCTURAL",
            "INSUFFICIENT_EVIDENCE",
            "FALSE_POSITIVE",
        ],
        "workloads": [
            {
                "workload_id": "sample",
                "workload_class": "sample class",
                "artifact": "/tmp/sample",
                "tasks": 1,
                "runs": 1,
                "llm_calls": 1,
                "tool_calls": 0,
                "task_ids": ["task-1"],
                "finding_ids": ["CONTEXT_DUPLICATION"],
                "capabilities": {
                    "tasks_captured": "YES",
                    "run_structure": "YES",
                    "llm_timing": "FULL",
                    "tool_timing": "FULL",
                    "provider_usage": "FULL",
                    "component_attribution": "FULL",
                    "task_quality": "YES",
                    "serving_correlation": "NOT_APPLICABLE",
                    "context_findings": "YES",
                    "replay_validation": "NO",
                },
                "readiness": {
                    "agent": "READY",
                    "cross_layer": "NOT_APPLICABLE",
                },
                "reviews": [
                    {
                        "finding_id": "CONTEXT_DUPLICATION",
                        "task_id": "task-1",
                        "classification": "VALID_NON_ACTIONABLE",
                        "rationale": "Correct but not useful for this tiny sample.",
                        "reviewer": "engineering_review",
                    }
                ],
            }
        ],
    }
