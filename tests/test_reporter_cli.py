from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentperf.analyzer import analyze_path
from agentperf.artifacts import ExperimentArtifact
from agentperf.cli import main
from agentperf.reporters.terminal import render_report
from agentperf.schema.artifacts import QualityMetric, TaskResult
from agentperf.schema.trace import parse_agentperf_trace

ROOT = Path(__file__).resolve().parents[1]


def test_terminal_report_includes_synthetic_label_and_findings() -> None:
    report = analyze_path(ROOT / "examples/traces/multi_problem_agent.json")
    output = render_report(report)

    assert "Data: synthetic trace fixture, not benchmark results" in output
    assert "[LOW] CACHEABILITY_HEADROOM" in output
    assert "Validation:" in output
    assert "Agent trace input tokens" in output
    assert "agent trace average input tokens" in output
    assert "serving request input p95 tokens" in output
    assert "serving uncached input p95 tokens" in output
    assert "serving latency semantics" in output
    assert "true prefill stage" in output
    assert "materiality ttft p95 threshold met" in output
    assert "yes" in output
    assert "materiality serving uncached input threshold met" in output
    assert "no" in output
    assert "Metric Provenance" in output
    assert "serving request input p95 tokens" in output
    assert "serving_backend" in output
    assert "Investigations" in output
    assert "Repeated static context and cacheability" in output
    assert "Materiality evaluation:" in output
    assert "TTFT gate" in output
    assert "Serving uncached prompt-volume gate" in output


def test_cli_analyze_success(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["analyze", str(ROOT / "examples/traces/healthy_agent.json")])

    captured = capsys.readouterr()
    assert code == 0
    assert "AgentPerf Report" in captured.out
    assert "No high-confidence MVP findings." in captured.out


def test_cli_reports_malformed_trace(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    trace = tmp_path / "bad.json"
    trace.write_text('{"agent_run": {"steps": []}}', encoding="utf-8")

    code = main(["analyze", str(trace)])

    captured = capsys.readouterr()
    assert code == 2
    assert "missing required field" in captured.err


def test_m13_suite_markdown_prioritizes_component_improvement(tmp_path: Path) -> None:
    output = tmp_path / "m13.md"

    code = main(
        [
            "suite",
            "check",
            str(ROOT / "benchmarks/openai-agents-support-triage"),
            str(ROOT / "examples/dogfooding/openai_agents_support_triage_compact"),
            "--format",
            "markdown",
            "--output",
            str(output),
        ]
    )
    text = output.read_text(encoding="utf-8")

    assert code == 0
    assert "### Summary" in text
    assert "**Result:** PASS" in text
    assert "component.system.processed_tokens" in text
    assert "680 -> 520" in text
    assert "provider-reported usage is unchanged" in text


def test_m3_regression_summary_surfaces_tool_result_reduction(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(
        [
            "check",
            str(ROOT / "examples/artifacts/m3_raw_full"),
            str(ROOT / "examples/artifacts/m3_dedup_only"),
            "--policy",
            str(ROOT / "examples/policies/m3-context-regression.yaml"),
        ]
    )
    text = capsys.readouterr().out

    assert code == 0
    assert "Summary" in text
    assert "component.tool_result.processed_tokens" in text
    assert "112287 -> 78566" in text
    assert "Biggest regressions: none above configured thresholds" in text


def test_quality_failure_is_prominent_even_with_token_improvement(
    tmp_path: Path,
    capsys: Any,
) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
quality:
  mean_score:
    max_drop: 0.05
performance:
  input_tokens:
    max_increase_percent: 15
""",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps(_trace("baseline", score=1.0, tokens=1000)), encoding="utf-8")
    candidate.write_text(json.dumps(_trace("candidate", score=0.5, tokens=200)), encoding="utf-8")

    code = main(["check", str(baseline), str(candidate), "--policy", str(policy)])
    text = capsys.readouterr().out

    assert code == 1
    assert "Result                             FAIL" in text
    assert text.index("QUALITY REGRESSION") < text.index("Biggest improvements")
    assert "input_tokens: 1000 -> 200" in text


def test_task_level_regression_triage_from_artifacts(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _write_quality_artifact(
        baseline,
        artifact_id="baseline",
        scores={"task-1": 1.0, "task-2": 1.0},
    )
    _write_quality_artifact(
        candidate,
        artifact_id="candidate",
        scores={"task-1": 1.0, "task-2": 0.2},
    )
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
quality:
  mean_score:
    max_drop: 0.05
  pass_rate:
    max_drop: 0.10
task_coverage:
  require_same_tasks: true
""",
        encoding="utf-8",
    )

    code = main(["check", str(baseline), str(candidate), "--policy", str(policy)])
    text = capsys.readouterr().out

    assert code == 1
    assert "Task regressions:" in text
    assert "task-2" in text


def test_check_json_output_remains_structured(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    policy = tmp_path / "policy.yaml"
    policy.write_text("quality:\n  mean_score:\n    max_drop: 0.05\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps(_trace("baseline", score=1.0, tokens=100)), encoding="utf-8")
    candidate.write_text(json.dumps(_trace("candidate", score=1.0, tokens=100)), encoding="utf-8")

    code = main(
        [
            "check",
            str(baseline),
            str(candidate),
            "--policy",
            str(policy),
            "--format",
            "json",
        ]
    )
    data = json.loads(capsys.readouterr().out)

    assert code == 0
    assert data["status"] == "PASS"
    assert isinstance(data["checks"], list)
    assert "Summary" not in data


def _trace(run_id: str, *, score: float, tokens: int) -> dict[str, object]:
    return {
        "schema_version": "agentperf.trace.v1",
        "agent_run": {
            "agent_run_id": run_id,
            "metadata": {"task_id": "task-1", "quality": {"score": score, "passed": score >= 0.8}},
            "steps": [
                {
                    "agent_step_id": "step-1",
                    "llm_calls": [
                        {
                            "llm_call_id": "llm-1",
                            "model": "fixture",
                            "input_tokens": tokens,
                            "output_tokens": 10,
                            "prompt": [{"name": "user", "text": "token " * tokens}],
                        }
                    ],
                }
            ],
        },
    }


def _write_quality_artifact(
    path: Path,
    *,
    artifact_id: str,
    scores: dict[str, float],
) -> None:
    mean_score = sum(scores.values()) / len(scores)
    pass_rate = sum(1 for score in scores.values() if score >= 0.8) / len(scores)
    run = parse_agentperf_trace(_trace(artifact_id, score=mean_score, tokens=100))
    artifact = ExperimentArtifact.from_run(
        run,
        artifact_id=artifact_id,
        workload_id="quality-fixture",
        task_count=len(scores),
        task_results=[
            TaskResult(
                task_id=task_id,
                passed=score >= 0.8,
                quality_score=score,
                status="COMPLETE",
            )
            for task_id, score in scores.items()
        ],
        quality_metrics=[
            QualityMetric(name="mean_score", value=mean_score),
            QualityMetric(name="pass_rate", value=pass_rate),
        ],
    )
    artifact.save(path)
