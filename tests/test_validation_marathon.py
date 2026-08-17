from __future__ import annotations

import html
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact, load_artifact
from agentperf.cli import main
from agentperf.comparison import compare_paths, comparison_to_dict
from agentperf.completeness import assess_path
from agentperf.regression import (
    evaluate_regression_policy,
    load_regression_policy,
    regression_result_to_dict,
)
from agentperf.reporters.comparison_html import (
    build_comparison_html_input,
    render_comparison_html,
)
from agentperf.reporters.html import _call_scope_index, load_html_report_input, render_html_report
from agentperf.schema.artifacts import ArtifactStatus, QualityMetric, TaskResult
from agentperf.schema.trace import AgentRun, parse_agentperf_trace

ROOT = Path(__file__).resolve().parents[1]


def test_api_cli_json_terminal_and_html_comparison_semantics_agree(
    tmp_path: Path,
    capsys: Any,
) -> None:
    baseline = ROOT / "examples/artifacts/m3_raw_full"
    candidate = ROOT / "examples/artifacts/m3_dedup_only"
    html_output = tmp_path / "comparison with spaces.html"

    api = compare_paths(baseline, candidate)
    api_data = comparison_to_dict(api)

    json_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--format",
            "json",
        ]
    )
    cli_json = json.loads(capsys.readouterr().out)
    terminal_code = main(["compare", str(baseline), str(candidate)])
    terminal = capsys.readouterr().out
    html_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--format",
            "html",
            "--output",
            str(html_output),
        ]
    )
    embedded = _comparison_html_payload(html_output.read_text(encoding="utf-8"))

    assert json_code == terminal_code == html_code == 0
    assert cli_json["acceptance_result"] == api_data["acceptance_result"]
    assert cli_json["matched_tasks"] == api_data["matched_tasks"]
    assert cli_json["token_deltas"] == api_data["token_deltas"]
    assert cli_json["quality_deltas"] == api_data["quality_deltas"]
    assert cli_json["finding_changes"] == api_data["finding_changes"]
    assert embedded["comparison"]["acceptance_result"] == api_data["acceptance_result"]
    assert "Result                             ACCEPT" in terminal
    assert "Quality                            PASS" in terminal


def test_check_json_markdown_terminal_and_api_policy_semantics_agree(
    tmp_path: Path,
    capsys: Any,
) -> None:
    baseline = ROOT / "examples/artifacts/m3_raw_full"
    candidate = ROOT / "examples/artifacts/m3_dedup_only"
    policy_path = ROOT / "examples/policies/m3-context-regression.yaml"
    policy = load_regression_policy(policy_path)
    comparison = compare_paths(
        baseline,
        candidate,
        mean_score_tolerance=policy.quality["mean_score"].max_drop,
        pass_rate_tolerance=policy.quality["pass_rate"].max_drop,
    )
    api_result = regression_result_to_dict(evaluate_regression_policy(comparison, policy))
    markdown_path = tmp_path / "check.md"

    json_code = main(
        [
            "check",
            str(baseline),
            str(candidate),
            "--policy",
            str(policy_path),
            "--format",
            "json",
        ]
    )
    json_result = json.loads(capsys.readouterr().out)
    terminal_code = main(["check", str(baseline), str(candidate), "--policy", str(policy_path)])
    terminal = capsys.readouterr().out
    markdown_code = main(
        [
            "check",
            str(baseline),
            str(candidate),
            "--policy",
            str(policy_path),
            "--format",
            "markdown",
            "--output",
            str(markdown_path),
        ]
    )
    markdown = markdown_path.read_text(encoding="utf-8")

    assert json_code == terminal_code == markdown_code == 0
    assert json_result["status"] == api_result["status"] == "PASS"
    assert json_result["checks"] == api_result["checks"]
    assert "Final Result" in terminal
    assert "PASS" in markdown


def test_cli_exit_code_matrix_for_success_failure_inconclusive_and_user_errors(
    tmp_path: Path,
    capsys: Any,
) -> None:
    passing_baseline = _artifact(
        tmp_path / "passing baseline",
        status="COMPLETE",
        scores={"task-1": 1.0},
        tokens=1000,
    )
    passing_candidate = _artifact(
        tmp_path / "passing candidate",
        status="COMPLETE",
        scores={"task-1": 1.0},
        tokens=800,
    )
    quality_candidate = _artifact(
        tmp_path / "quality candidate",
        status="COMPLETE",
        scores={"task-1": 0.2},
        tokens=100,
    )
    partial_candidate = _artifact(
        tmp_path / "partial candidate",
        status="PARTIAL",
        scores={"task-1": 1.0},
        tokens=800,
    )
    malformed_policy = tmp_path / "malformed-policy.yaml"
    malformed_policy.write_text("quality: [", encoding="utf-8")
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
quality:
  mean_score:
    max_drop: 0.05
task_coverage:
  require_same_tasks: true
""",
        encoding="utf-8",
    )
    malformed_artifact = tmp_path / "bad.json"
    malformed_artifact.write_text("{", encoding="utf-8")

    assert (
        main(["check", str(passing_baseline), str(passing_candidate), "--policy", str(policy)])
        == 0
    )
    assert (
        main(["check", str(passing_baseline), str(quality_candidate), "--policy", str(policy)])
        == 1
    )
    assert (
        main(["check", str(passing_baseline), str(partial_candidate), "--policy", str(policy)])
        == 3
    )
    assert (
        main(
            [
                "check",
                str(passing_baseline),
                str(passing_candidate),
                "--policy",
                str(malformed_policy),
            ]
        )
        == 2
    )
    assert main(["compare", str(malformed_artifact), str(passing_candidate)]) == 2
    assert main(["doctor", str(malformed_artifact)]) == 1
    assert main(["report", str(malformed_artifact), "--output", str(tmp_path / "bad.html")]) == 2
    assert "invalid JSON" in capsys.readouterr().err or capsys.readouterr().out


def test_filesystem_outputs_handle_spaces_unicode_symlink_and_existing_demo_dir(
    tmp_path: Path,
    capsys: Any,
) -> None:
    artifact = _artifact(
        tmp_path / "artifact unicode",
        status="COMPLETE",
        scores={"task-1": 1.0},
        tokens=100,
    )
    output_dir = tmp_path / "nested dir" / "unicode-output"
    output_dir.mkdir(parents=True)
    html_path = output_dir / "report cafe.html"

    assert main(["report", str(artifact), "--output", str(html_path)]) == 0
    assert html_path.exists()

    symlink_path = tmp_path / "linked report.html"
    os.symlink(html_path, symlink_path)
    assert main(["report", str(artifact), "--output", str(symlink_path)]) == 0
    assert "AgentPerf" in html_path.read_text(encoding="utf-8")

    demo_dir = tmp_path / "existing-demo"
    demo_dir.mkdir()
    assert main(["demo", "--output", str(demo_dir)]) == 0
    assert main(["demo", "--output", str(demo_dir)]) == 2
    assert main(["demo", "--output", str(demo_dir), "--force"]) == 0
    captured = capsys.readouterr()
    assert "already exists" in captured.err


def test_sigterm_after_checkpoint_recovers_latest_completed_evidence(tmp_path: Path) -> None:
    output = tmp_path / "sigterm-artifact"
    ready = tmp_path / "checkpoint-ready"
    script = f"""
import signal
import time
from pathlib import Path
from agentperf import ExperimentSession, trace_llm, trace_run

out = Path({str(output)!r})
ready = Path({str(ready)!r})
session = ExperimentSession(
    output_path=out,
    artifact_id="sigterm",
    workload_id="sigterm",
    expected_task_count=20,
)
session.__enter__()
for index in range(12):
    task_id = f"task-{{index}}"
    with trace_run(task_id=task_id):
        with trace_llm(components={{"user": task_id}}, llm_call_id=f"{{task_id}}-llm") as call:
            call.record_response(input_tokens=4, output_tokens=1)
    session.record_task_result(task_id=task_id, passed=True, quality_score=1.0)
session.flush()
ready.write_text("ready", encoding="utf-8")
while True:
    time.sleep(0.1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 10
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()

    artifact = load_artifact(output)
    assert artifact.manifest.status == "PARTIAL"
    assert artifact.manifest.metadata["capture_state"] == "RECOVERED_FROM_CHECKPOINT"
    assert len(artifact.task_results) == 12
    assert len(artifact.runs[0].llm_calls) == 12
    assert all(call.ended_at is not None for call in artifact.runs[0].llm_calls)


def test_html_semantic_corpus_preserves_unavailable_quality_partial_and_security(
    tmp_path: Path,
) -> None:
    partial = _artifact(
        tmp_path / "partial",
        status="PARTIAL",
        scores={"task-1": None},
        tokens=100,
        metadata={"agent_id": "<script>alert(1)</script>", "OPENAI_API_KEY": "sk-test-secret"},
    )
    complete = _artifact(
        tmp_path / "complete",
        status="COMPLETE",
        scores={"task-1": 1.0},
        tokens=100,
    )

    single_html = render_html_report(load_html_report_input(partial))
    comparison = compare_paths(complete, partial)
    comparison_html = render_comparison_html(
        build_comparison_html_input(comparison, complete, partial)
    )
    payload = _comparison_html_payload(comparison_html)

    assert "PARTIAL" in single_html
    assert "Quality verification unavailable" in comparison_html
    assert payload["comparison"]["acceptance_result"]["verdict"] != "ACCEPT"
    assert "sk-test-secret" not in single_html
    assert "<script>alert(1)</script>" not in single_html
    assert "sk-test-secret" not in comparison_html


def test_html_scope_index_preserves_agent_and_branch_call_scope() -> None:
    run = _run(
        "scoped",
        task_id="task-1",
        score=1.0,
        tokens=100,
        metadata={"agent_id": "researcher", "branch_id": "search-a"},
    )

    assert _call_scope_index([run]) == {"llm-1": "agent:researcher branch:search-a"}


def test_relevant_json_fixture_corpus_uses_public_loaders() -> None:
    trace_files = [
        ROOT / "examples/traces/healthy_agent.json",
        ROOT / "examples/traces/multi_problem_agent.json",
        ROOT / "examples/recorded_telemetry/vllm_openai_response_fixture.json",
        ROOT / "examples/recorded_telemetry/sglang_openai_response_fixture.json",
    ]
    artifact_dirs = [
        ROOT / "examples/artifacts/m3_raw_full",
        ROOT / "examples/artifacts/m3_dedup_only",
        ROOT / "docs/data/m25_phase_b/strong_control/agentperf_artifact",
        ROOT / "docs/data/m25_phase_b/mixed_evidence_backed/agentperf_artifact",
    ]

    for trace_file in trace_files[:2]:
        data = json.loads(trace_file.read_text(encoding="utf-8"))
        run = parse_agentperf_trace(data)
        report = analyze_run(run)
        assert report.run.agent_run_id
        assert len(report.run.llm_calls) >= 0

    for artifact_dir in artifact_dirs:
        artifact = load_artifact(artifact_dir)
        assert artifact.manifest.artifact_schema_version == 1
        assert artifact.runs_for_comparison()
        assert assess_path(artifact_dir).artifact_valid is True

    for telemetry_file in trace_files[2:]:
        assert json.loads(telemetry_file.read_text(encoding="utf-8"))


def _comparison_html_payload(text: str) -> dict[str, Any]:
    marker = '<script type="application/json" id="agentperf-comparison-data">'
    start = text.index(marker) + len(marker)
    end = text.index("</script>", start)
    return cast(dict[str, Any], json.loads(html.unescape(text[start:end])))


def _artifact(
    path: Path,
    *,
    status: ArtifactStatus,
    scores: dict[str, float | None],
    tokens: int,
    metadata: dict[str, object] | None = None,
) -> Path:
    task_id, score = next(iter(scores.items()))
    run = _run(
        f"run-{task_id}",
        task_id=task_id,
        score=score,
        tokens=tokens,
        metadata=metadata,
    )
    artifact = ExperimentArtifact.from_analysis(
        analyze_run(run),
        artifact_id=path.name,
        workload_id="validation-marathon",
        task_count=len(scores),
        task_results=[
            TaskResult(
                task_id=task_id,
                passed=(score is not None and score >= 0.8),
                quality_score=score,
                status="COMPLETE" if score is not None else "UNKNOWN",
                agent_run_ids=[f"run-{task_id}"],
            )
            for task_id, score in scores.items()
        ],
        quality_metrics=[
            QualityMetric(
                name="mean_score",
                value=sum(score or 0 for score in scores.values()) / len(scores),
                tolerance=0.05,
            )
        ]
        if all(score is not None for score in scores.values())
        else [],
        summary={"fixture": "validation-marathon"},
    )
    artifact = replace(artifact, manifest=replace(artifact.manifest, status=status))
    artifact.save(path)
    return path


def _run(
    run_id: str,
    *,
    task_id: str,
    score: float | None,
    tokens: int,
    metadata: dict[str, object] | None = None,
) -> AgentRun:
    run_metadata: dict[str, object] = {"task_id": task_id, **(metadata or {})}
    if score is not None:
        run_metadata["quality"] = {"score": score, "passed": score >= 0.8}
    return parse_agentperf_trace(
        {
            "schema_version": "agentperf.trace.v1",
            "agent_run": {
                "agent_run_id": run_id,
                "metadata": run_metadata,
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "llm_request_id": "req-1",
                                "model": "fixture",
                                "prompt": [{"name": "user", "text": "x " * tokens}],
                                "input_tokens": tokens,
                                "output_tokens": 5,
                                "metadata": {"latency_ms": 10.0},
                            }
                        ],
                    }
                ],
            },
            "serving_requests": [],
        }
    )
