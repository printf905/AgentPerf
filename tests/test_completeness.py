from __future__ import annotations

import json
from pathlib import Path

from agentperf.completeness import assess_path
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import trace_llm, trace_run


def test_completeness_ready_for_framework_free_artifact(tmp_path: Path) -> None:
    output = tmp_path / "ready"
    with ExperimentSession(
        output_path=output,
        artifact_id="ready",
        workload_id="ready-workload",
        expected_task_count=1,
    ) as experiment, trace_run(task_id="task-1"):
        with trace_llm(components={"user": "hello"}, model="fixture") as call:
            call.record_response(
                output="ok",
                input_tokens=1,
                output_tokens=1,
                request_id="req-1",
            )
        experiment.record_task_result(
            task_id="task-1",
            passed=True,
            quality_score=1.0,
            status="COMPLETE",
        )

    report = assess_path(output)

    assert report.artifact_valid is True
    assert report.agent_profiling_readiness == "READY"
    assert report.cross_layer_readiness == "NOT_APPLICABLE"
    assert report.llm_calls_with_provider_usage == 1
    assert report.llm_calls_with_component_attribution == 1
    assert report.tasks_with_quality == 1


def test_completeness_partial_when_usage_and_components_missing(tmp_path: Path) -> None:
    trace = tmp_path / "partial.json"
    trace.write_text(
        """
{
  "agent_run": {
    "agent_run_id": "partial",
    "steps": [
      {
        "agent_step_id": "step-1",
        "llm_calls": [
          {
            "llm_call_id": "llm-1",
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": "2026-01-01T00:00:01+00:00"
          }
        ]
      }
    ]
  }
}
""",
        encoding="utf-8",
    )

    report = assess_path(trace)

    assert report.agent_profiling_readiness == "PARTIAL"
    assert report.cross_layer_readiness == "NOT_APPLICABLE"
    assert "LLM calls lack both provider usage and component attribution" in report.limitations


def test_completeness_partial_cross_layer_when_request_id_missing(tmp_path: Path) -> None:
    trace_path = tmp_path / "cross-layer.json"
    trace_path.write_text(
        json.dumps(
            {
                "agent_run": {
                    "agent_run_id": "cross-layer",
                    "steps": [
                        {
                            "agent_step_id": "step-1",
                            "llm_calls": [
                                {
                                    "llm_call_id": "llm-1",
                                    "prompt": {"user": "hello"},
                                    "input_tokens": 1,
                                    "started_at": "2026-01-01T00:00:00+00:00",
                                    "ended_at": "2026-01-01T00:00:01+00:00",
                                },
                                {
                                    "llm_call_id": "llm-2",
                                    "llm_request_id": "req-2",
                                    "prompt": {"user": "hello"},
                                    "input_tokens": 1,
                                    "started_at": "2026-01-01T00:00:00+00:00",
                                    "ended_at": "2026-01-01T00:00:01+00:00",
                                },
                            ],
                        }
                    ],
                },
                "serving_requests": [
                    {
                        "serving_request_id": "srv-2",
                        "llm_request_id": "req-2",
                        "input_tokens": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = assess_path(trace_path)

    assert report.agent_profiling_readiness == "READY"
    assert report.cross_layer_readiness == "PARTIAL"
    assert report.eligible_serving_correlations == 1
    assert report.exact_serving_correlations == 1
    assert "1 LLM calls lack stable request IDs" in report.limitations


def test_duplicate_task_results_fail_fast(tmp_path: Path) -> None:
    with ExperimentSession(output_path=tmp_path / "dup") as experiment:
        experiment.record_task_result(task_id="task-1", passed=True)
        try:
            experiment.record_task_result(task_id="task-1", passed=True)
        except ValueError as exc:
            assert "duplicate task result" in str(exc)
        else:  # pragma: no cover - assertion clarity
            raise AssertionError("duplicate task result should fail")
