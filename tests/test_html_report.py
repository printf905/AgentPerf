from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

from agentperf.artifacts import ExperimentArtifact
from agentperf.cli import main
from agentperf.reporters.html import load_html_report_input, render_html_report
from agentperf.schema.artifacts import ArtifactStatus, QualityMetric, TaskResult
from agentperf.schema.findings import Finding, FindingProvenance
from agentperf.schema.trace import parse_agentperf_trace

ROOT = Path(__file__).resolve().parents[1]


def test_html_report_from_artifact_includes_profiler_sections(tmp_path: Path) -> None:
    artifact_path = _artifact(tmp_path / "artifact")
    report_input = load_html_report_input(artifact_path)

    html = render_html_report(report_input)

    assert "<!doctype html>" in html
    assert "AgentPerf Local Profiler Report" in html
    assert "Execution Timeline" in html
    assert "Instrumentation Completeness" in html
    assert "Agent profiling" in html
    assert "Token Attribution" in html
    assert "Context Growth" in html
    assert "Tool-Output Carry-Forward" in html
    assert "Findings" in html
    assert "Serving Telemetry" in html
    assert "mean_score=1.000" in html
    assert "tool_result" in html
    assert "TOOL_OUTPUT_BLOAT" in html


def test_html_report_from_raw_trace_degrades_without_artifact_metadata(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(_trace(serving=False)), encoding="utf-8")

    html = render_html_report(load_html_report_input(trace_path))

    assert "Source: raw trace" in html
    assert "No task-level results recorded." in html
    assert "No serving telemetry recorded." in html
    assert "fixture-run" in html


def test_html_report_escapes_html_and_redacts_sensitive_metadata(tmp_path: Path) -> None:
    trace = _trace(secret_metadata=True)
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    html = render_html_report(load_html_report_input(trace_path))

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "super-secret" not in html
    assert "sk-test-secret" not in html
    assert "Authorization: Bearer fake-secret" not in html
    assert "RUNPOD_API_KEY=fake" not in html
    assert "/user/private/path" not in html
    assert "[redacted]" in html


def test_html_report_shows_cross_layer_correlation() -> None:
    html = render_html_report(load_html_report_input(ROOT / "examples/traces/replay_baseline.json"))

    assert "Serving Correlation" in html
    assert "Serving request" in html
    assert "Scheduled-&gt;first" in html
    assert "not pure GPU prefill kernel time" in html


def test_html_report_shows_metric_provenance_materiality_and_investigation() -> None:
    html = render_html_report(
        load_html_report_input(ROOT / "examples/traces/multi_problem_agent.json")
    )

    assert "Metric Provenance" in html
    assert "serving request input p95 tokens" in html
    assert "serving_backend" in html
    assert "Investigations" in html
    assert "Repeated static context and cacheability" in html
    assert "not a causal proof" in html
    assert "Materiality evaluation" in html
    assert "TTFT gate" in html
    assert "Serving uncached prompt-volume gate" in html
    assert "NOT_EXCEEDED" in html


def test_html_report_handles_partial_artifact_and_failed_task(tmp_path: Path) -> None:
    artifact_path = _artifact(tmp_path / "partial", status="PARTIAL", passed=False)
    html = render_html_report(load_html_report_input(artifact_path))

    assert "PARTIAL" in html
    assert '<span class="badge fail">fail</span>' in html


def test_html_report_output_is_deterministic(tmp_path: Path) -> None:
    artifact_path = _artifact(tmp_path / "artifact")
    report_input = load_html_report_input(artifact_path)

    assert render_html_report(report_input) == render_html_report(report_input)


def test_cli_report_writes_html(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "agentperf-report.html"

    code = main(
        [
            "report",
            str(ROOT / "examples/dogfooding/openai_agents_support_triage_compact"),
            "--output",
            str(output),
            "--title",
            "Support triage report",
        ]
    )
    captured = capsys.readouterr()
    html = output.read_text(encoding="utf-8")

    assert code == 0
    assert "Wrote AgentPerf HTML report" in captured.out
    assert "Support triage report" in html
    assert "system" in html
    assert "520" in html


def _artifact(
    path: Path,
    *,
    status: str = "COMPLETE",
    passed: bool = True,
) -> Path:
    run = parse_agentperf_trace(_trace())
    manifest_status = cast(ArtifactStatus, "COMPLETE" if status == "COMPLETE" else status)
    artifact = ExperimentArtifact.from_run(
        run,
        artifact_id="html-fixture",
        workload_id="html-fixture",
        task_results=[
            TaskResult(
                task_id="task-1",
                passed=passed,
                quality_score=1.0 if passed else 0.0,
                client_latency_ms=123.0,
                agent_run_ids=["fixture-run"],
                status=status,
            )
        ],
        quality_metrics=[
            QualityMetric(name="mean_score", value=1.0 if passed else 0.0),
            QualityMetric(name="pass_rate", value=1.0 if passed else 0.0),
        ],
        findings=[
            Finding(
                id="TOOL_OUTPUT_BLOAT",
                severity="HIGH",
                title="Tool output is repeatedly processed",
                summary="A tool result is carried into downstream LLM calls.",
                evidence={"materiality": "ACTIONABLE", "scope": "AgentRun fixture-run"},
                affected_spans=["llm-2"],
                recommendation="Inspect repeated tool-result carry-forward.",
                confidence="HIGH",
                validation_plan=["Reduce duplicate downstream tool-result processing."],
                provenance=FindingProvenance(llm_call_ids=["llm-2"]),
            )
        ],
        environment={"python": "3.11", "api_key": "super-secret"},
        framework="fixture-framework",
        agent_name="fixture-agent",
        backend="vllm",
        model="fixture-model",
        serving_telemetry=True,
    )
    artifact = replace(artifact, manifest=replace(artifact.manifest, status=manifest_status))
    artifact.save(path)
    return path


def _trace(*, serving: bool = True, secret_metadata: bool = False) -> dict[str, object]:
    tool_output = " ".join(f"evidence{i}" for i in range(120))
    metadata = {
        "source_tool_call_ids": ["tool-1"],
        "note": "<script>alert(1)</script>" if secret_metadata else "safe",
    }
    if secret_metadata:
        metadata["api_token"] = "super-secret"
        metadata["authorization_header"] = "Authorization: Bearer fake-secret"
        metadata["note_with_key"] = "OPENAI_API_KEY=sk-test-secret"
        metadata["runpod_hint"] = "RUNPOD_API_KEY=fake"
        metadata["private_path"] = "/user/private/path"
    trace: dict[str, object] = {
        "schema_version": "agentperf.trace.v1",
        "agent_run": {
            "agent_run_id": "fixture-run",
            "name": "fixture agent",
            "metadata": {"framework": "fixture-framework"},
            "steps": [
                {
                    "agent_step_id": "step-1",
                    "llm_calls": [
                        {
                            "llm_call_id": "llm-1",
                            "llm_request_id": "req-1",
                            "model": "fixture-model",
                            "input_tokens": 180,
                            "output_tokens": 12,
                            "tokenization_mode": "EXACT",
                            "prompt": [
                                {"name": "system", "text": "You are a compact agent."},
                                {"name": "user", "text": "Fix the issue."},
                            ],
                        }
                    ],
                    "tool_calls": [
                        {
                            "tool_call_id": "tool-1",
                            "name": "lookup",
                            "latency_ms": 17.0,
                            "output": tool_output,
                            "metadata": {"private_key": "super-secret"},
                        }
                    ],
                },
                {
                    "agent_step_id": "step-2",
                    "llm_calls": [
                        {
                            "llm_call_id": "llm-2",
                            "llm_request_id": "req-2",
                            "model": "fixture-model",
                            "input_tokens": 260,
                            "output_tokens": 20,
                            "tokenization_mode": "EXACT",
                            "prompt": [
                                {"name": "system", "text": "You are a compact agent."},
                                {
                                    "name": "tool_result",
                                    "text": tool_output,
                                    "metadata": metadata,
                                },
                            ],
                        }
                    ],
                },
            ],
        },
    }
    if serving:
        trace["serving_requests"] = [
            {
                "serving_request_id": "srv-1",
                "llm_request_id": "req-1",
                "backend": "vllm",
                "model": "fixture-model",
                "queue_latency_ms": 2.0,
                "prefill_path_latency_ms": 30.0,
                "decode_latency_ms": 11.0,
                "input_tokens": 180,
                "output_tokens": 12,
                "prefix_cache_hit_tokens": 10,
                "prefix_cache_miss_tokens": 170,
            },
            {
                "serving_request_id": "srv-2",
                "llm_request_id": "req-2",
                "backend": "vllm",
                "model": "fixture-model",
                "queue_latency_ms": 3.0,
                "prefill_path_latency_ms": 35.0,
                "decode_latency_ms": 14.0,
                "input_tokens": 260,
                "output_tokens": 20,
                "prefix_cache_hit_tokens": 30,
                "prefix_cache_miss_tokens": 230,
            },
        ]
    return trace
