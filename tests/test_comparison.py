from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentperf.cli import main
from agentperf.comparison import compare_paths, compare_workloads, comparison_to_dict
from agentperf.schema.comparison import RunComparison
from agentperf.schema.trace import AgentRun, parse_agentperf_trace


def test_compare_accepts_quality_constrained_token_and_latency_improvement(tmp_path: Path) -> None:
    baseline = _trace("base-task-1", task_id="task-1", score=0.933, passed=True)
    candidate = _trace(
        "candidate-task-1",
        task_id="task-1",
        score=0.908,
        passed=True,
        tool_reinjections=0,
        client_latency_ms=700,
        serving_ttft_ms=120,
    )
    baseline_path = _write(tmp_path / "baseline.json", baseline)
    candidate_path = _write(tmp_path / "candidate.json", candidate)

    comparison = compare_paths(
        baseline_path,
        candidate_path,
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )

    assert comparison.matched_tasks == ["task-1"]
    assert comparison.acceptance_result.verdict == "ACCEPT"
    assert comparison.token_deltas.input_tokens.percent_delta is not None
    assert comparison.token_deltas.input_tokens.percent_delta < -0.5
    assert comparison.token_deltas.component_processed_tokens["tool_result"].candidate == 0
    assert comparison.quality_deltas.passed is True
    assert any(
        change.finding_id == "TOOL_OUTPUT_BLOAT" and change.lifecycle == "RESOLVED"
        for change in comparison.finding_changes
    )


def test_compare_rejects_quality_regression_even_when_tokens_drop(tmp_path: Path) -> None:
    baseline_path = _write(
        tmp_path / "baseline.json",
        _trace("base-task-1", task_id="task-1", score=0.93, passed=True),
    )
    candidate_path = _write(
        tmp_path / "candidate.json",
        _trace(
            "candidate-task-1",
            task_id="task-1",
            score=0.70,
            passed=False,
            tool_reinjections=0,
            client_latency_ms=400,
        ),
    )

    comparison = compare_paths(
        baseline_path,
        candidate_path,
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )

    assert comparison.acceptance_result.verdict == "REJECT_QUALITY_REGRESSION"
    assert comparison.acceptance_result.performance_improved is True
    assert comparison.quality_deltas.passed is False


def test_compare_reports_inconclusive_without_quality_signal(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path / "baseline.json", _trace("base-task-1", task_id="task-1"))
    candidate_path = _write(
        tmp_path / "candidate.json",
        _trace("candidate-task-1", task_id="task-1", tool_reinjections=0),
    )

    comparison = compare_paths(baseline_path, candidate_path)

    assert comparison.acceptance_result.verdict == "INCONCLUSIVE"
    assert "PERFORMANCE_IMPROVEMENT_UNVERIFIED_FOR_QUALITY" in comparison.warnings


def test_compare_reports_no_material_change() -> None:
    baseline = _run(
        _trace(
            "base-task-1",
            task_id="task-1",
            score=1.0,
            passed=True,
            tool_reinjections=0,
        )
    )
    candidate = _run(
        _trace(
            "candidate-task-1",
            task_id="task-1",
            score=1.0,
            passed=True,
            tool_reinjections=0,
            client_latency_ms=991,
            serving_ttft_ms=99,
        )
    )

    comparison = compare_workloads(
        [baseline],
        [candidate],
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )

    assert comparison.acceptance_result.verdict == "NO_MATERIAL_CHANGE"


def test_compare_reports_regression() -> None:
    baseline = _run(
        _trace("base-task-1", task_id="task-1", score=1.0, passed=True, tool_reinjections=0)
    )
    candidate = _run(
        _trace(
            "candidate-task-1",
            task_id="task-1",
            score=1.0,
            passed=True,
            tool_reinjections=0,
            extra_other_tokens=1000,
            client_latency_ms=1400,
        )
    )

    comparison = compare_workloads(
        [baseline],
        [candidate],
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )

    assert comparison.acceptance_result.verdict == "REGRESSION"


def test_compare_handles_unmatched_tasks_conservatively() -> None:
    comparison = compare_workloads(
        [_run(_trace("base-task-1", task_id="task-1", score=1.0))],
        [_run(_trace("candidate-task-2", task_id="task-2", score=1.0))],
    )

    assert comparison.matched_tasks == []
    assert comparison.unmatched_baseline_tasks == ["task-1"]
    assert comparison.unmatched_candidate_tasks == ["task-2"]
    assert comparison.acceptance_result.verdict == "INCONCLUSIVE"


def test_compare_single_run_without_shared_id_warns_but_compares() -> None:
    comparison = compare_workloads(
        [_run(_trace("base-one", score=1.0, passed=True, tool_reinjections=0))],
        [_run(_trace("candidate-one", score=1.0, passed=True, tool_reinjections=0))],
        mean_score_tolerance=0.0,
        pass_rate_tolerance=0.0,
    )

    assert comparison.matched_tasks == ["single-run"]
    assert any("file cardinality" in warning for warning in comparison.warnings)


def test_compare_finding_lifecycle_improved_persistent_regressed_and_new() -> None:
    high = _run(_trace("base", task_id="task", score=1.0, tool_reinjections=5))
    medium = _run(
        _trace(
            "candidate",
            task_id="task",
            score=1.0,
            tool_reinjections=3,
            extra_other_tokens=10_000,
        )
    )
    no_finding = _run(_trace("empty", task_id="task", score=1.0, tool_reinjections=0))

    improved = compare_workloads([high], [medium])
    persistent = compare_workloads([high], [high])
    regressed = compare_workloads([medium], [high])
    new = compare_workloads([no_finding], [high])

    assert _lifecycle(improved, "TOOL_OUTPUT_BLOAT") == "IMPROVED"
    assert _lifecycle(persistent, "TOOL_OUTPUT_BLOAT") == "PERSISTENT"
    assert _lifecycle(regressed, "TOOL_OUTPUT_BLOAT") == "REGRESSED"
    assert _lifecycle(new, "TOOL_OUTPUT_BLOAT") == "NEW"


def test_compare_cache_and_latency_deltas_handle_missing_serving_telemetry() -> None:
    baseline = _run(
        _trace("base", task_id="task", score=1.0, cached_tokens=10, cache_miss_tokens=90)
    )
    candidate = _run(
        _trace("candidate", task_id="task", score=1.0, cached_tokens=60, cache_miss_tokens=40)
    )
    no_serving = _run(_trace("no-serving", task_id="task", score=1.0, serving=False))

    cache_comparison = compare_workloads([baseline], [candidate])
    missing_comparison = compare_workloads([no_serving], [no_serving])

    assert cache_comparison.cache_deltas.cached_token_ratio.candidate == 0.6
    assert missing_comparison.cache_deltas.cached_token_ratio.candidate is None
    assert missing_comparison.latency_deltas.scheduled_to_first_p95_ms.candidate is None


def test_compare_context_growth_and_framework_independence() -> None:
    baseline = _run(
        _trace("base", task_id="task", score=1.0, framework="mini-swe-agent", tool_reinjections=5)
    )
    candidate = _run(
        _trace(
            "candidate",
            task_id="task",
            score=1.0,
            framework="openai-agents-python",
            tool_reinjections=0,
        )
    )

    comparison = compare_workloads([baseline], [candidate])

    assert comparison.context_growth_delta.baseline_steps == 5
    assert comparison.context_growth_delta.candidate_steps == 1
    assert comparison.context_growth_delta.max_step_input_tokens.delta is not None
    assert comparison.context_growth_delta.max_step_input_tokens.delta < 0


def test_comparison_json_serialization(tmp_path: Path) -> None:
    comparison = compare_workloads(
        [_run(_trace("base", task_id="task", score=1.0, passed=True, tool_reinjections=0))],
        [_run(_trace("candidate", task_id="task", score=1.0, passed=True, tool_reinjections=0))],
    )
    data = comparison_to_dict(comparison)

    assert data["baseline_id"] == "base"
    assert data["token_deltas"]["input_tokens"]["baseline"] is not None
    assert json.loads(json.dumps(data))["matched_tasks"] == ["task"]


def test_cli_compare_terminal_and_json(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    baseline_path = _write(
        tmp_path / "baseline.json",
        _trace("base-task-1", task_id="task-1", score=0.95, passed=True),
    )
    candidate_path = _write(
        tmp_path / "candidate.json",
        _trace(
            "candidate-task-1",
            task_id="task-1",
            score=0.94,
            passed=True,
            tool_reinjections=0,
        ),
    )
    output_path = tmp_path / "comparison.json"

    terminal_code = main(
        [
            "compare",
            str(baseline_path),
            str(candidate_path),
            "--quality-tolerance",
            "0.05",
            "--pass-rate-tolerance",
            "0.10",
        ]
    )
    terminal = capsys.readouterr()
    json_code = main(
        [
            "compare",
            str(baseline_path),
            str(candidate_path),
            "--quality-tolerance",
            "0.05",
            "--format",
            "json",
            "--output",
            str(output_path),
        ]
    )

    assert terminal_code == 0
    assert "AgentPerf Replay Comparison" in terminal.out
    assert "ACCEPT" in terminal.out
    assert json_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["acceptance_result"][
        "verdict"
    ] == "ACCEPT"


def test_cli_compare_fail_on_quality_regression(tmp_path: Path) -> None:
    baseline_path = _write(
        tmp_path / "baseline.json",
        _trace("base", task_id="task", score=1.0, passed=True),
    )
    candidate_path = _write(
        tmp_path / "candidate.json",
        _trace("candidate", task_id="task", score=0.1, passed=False, tool_reinjections=0),
    )

    code = main(
        [
            "compare",
            str(baseline_path),
            str(candidate_path),
            "--quality-tolerance",
            "0.05",
            "--pass-rate-tolerance",
            "0.10",
            "--fail-on-quality-regression",
        ]
    )

    assert code == 1


def _lifecycle(comparison: RunComparison, finding_id: str) -> str:
    for change in comparison.finding_changes:
        if change.finding_id == finding_id:
            return change.lifecycle
    raise AssertionError(f"missing lifecycle for {finding_id}")


def _write(path: Path, data: dict[str, object]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run(data: dict[str, object]) -> AgentRun:
    return parse_agentperf_trace(data)


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
    steps: list[dict[str, Any]] = []
    llm_call_count = max(1, tool_reinjections)
    for index in range(llm_call_count):
        prompt: list[dict[str, Any]] = [
            {"name": "system", "text": "You are a careful agent."},
        ]
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
        step: dict[str, Any] = {
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
    serving_requests = []
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
