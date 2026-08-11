from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from agentperf.analyzer import analyze_run
from agentperf.artifacts import load_artifact
from agentperf.backends.sglang import SGLangTelemetryProvider
from agentperf.cli import main
from agentperf.correlation.correlator import TraceCorrelator
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.openai_compatible import build_sglang_recording_from_agent_run
from agentperf.reporters.html import load_html_report_input, render_html_report
from agentperf.reporters.terminal import render_report
from agentperf.schema.trace import AgentStep

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/recorded_telemetry/sglang_openai_response_fixture.json"
M17_ARTIFACT = ROOT / "examples/artifacts/m17_sglang_support_triage"


def load_fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_sglang_recording_converts_to_normalized_trace() -> None:
    run = SGLangTelemetryProvider().build_run(load_fixture())

    assert run.synthetic is False
    assert run.metadata["backend"] == "sglang"
    assert len(run.llm_calls) == 1
    assert len(run.tool_calls) == 1
    assert len(run.serving_requests) == 1

    call = run.llm_calls[0]
    serving = run.serving_requests[0]
    assert call.llm_request_id == "agentperf-sglang-fixture-0"
    assert call.serving_request_id == "chatcmpl-sglang-fixture-0"
    assert serving.serving_request_id == "chatcmpl-sglang-fixture-0"
    assert serving.llm_request_id == "agentperf-sglang-fixture-0"
    assert serving.backend == "sglang"
    assert call.output_token_ids == [901, 902, 903, 904, 905]


def test_sglang_exact_correlation_uses_request_ids() -> None:
    run = SGLangTelemetryProvider().build_run(load_fixture())
    correlation = TraceCorrelator().correlate(run)

    assert correlation.unresolved_llm_calls == []
    assert correlation.unresolved_serving_requests == []
    assert (
        correlation.llm_to_serving["llm-sglang-0"].serving_request_id
        == "chatcmpl-sglang-fixture-0"
    )


def test_build_sglang_recording_from_agent_run_joins_by_explicit_id() -> None:
    recorder = TraceRecorder(agent_run_id="run-sglang", name="fixture")
    with recorder.step("task-1"):
        recorder.record_llm_call(
            llm_call_id="llm-1",
            llm_request_id="req-1",
            prompt_components={"system": "classify", "user": "ticket"},
            model="fixture-model",
        )
    agent_run = recorder.finish()
    recording = build_sglang_recording_from_agent_run(
        agent_run=agent_run,
        captured_records=[
            {
                "client_request_id": "req-1",
                "request_id": "chatcmpl-req-1",
                "response": {
                    "id": "chatcmpl-req-1",
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                },
            }
        ],
        model="fixture-model",
        environment={"backend": "sglang"},
    )

    run = SGLangTelemetryProvider().build_run(recording)

    assert recording["environment"]["backend"] == "sglang"
    assert run.serving_requests[0].llm_request_id == "req-1"
    assert run.serving_requests[0].serving_request_id == "chatcmpl-req-1"


def test_sglang_missing_correlation_remains_unresolved() -> None:
    data = load_fixture()
    record = cast(list[dict[str, Any]], data["records"])[0]
    record["serving_request_id"] = "server-only-id"
    response = cast(dict[str, Any], record["response"])
    response["id"] = None

    run = SGLangTelemetryProvider().build_run(data)
    call = replace(
        run.llm_calls[0],
        llm_request_id="client-only-id",
        serving_request_id="client-only-serving-id",
    )
    run = replace(
        run,
        steps=[
            AgentStep(
                agent_step_id=run.steps[0].agent_step_id,
                llm_calls=[call],
                tool_calls=run.steps[0].tool_calls,
            )
        ],
        serving_requests=[
            replace(run.serving_requests[0], llm_request_id="different-server-id")
        ],
    )

    correlation = TraceCorrelator().correlate(run)

    assert correlation.llm_to_serving == {}
    assert [call.llm_call_id for call in correlation.unresolved_llm_calls] == [
        "llm-sglang-0"
    ]


def test_sglang_client_ttft_does_not_become_prefill_path_proxy() -> None:
    serving = SGLangTelemetryProvider().build_run(load_fixture()).serving_requests[0]

    assert serving.ttft_ms == 42.0
    assert serving.prefill_latency_ms is None
    assert serving.prefill_path_latency_ms is None
    assert serving.decode_latency_ms == 78.0
    assert serving.tpot_ms == 19.5
    reliability = serving.metadata["metric_reliability"]
    assert reliability["measurement_semantics"]["ttft_ms"] == "client_time_to_first_token"
    assert reliability["prefill_path_latency_ms"] == "unavailable"


def test_sglang_aggregate_cache_is_not_per_request_cache() -> None:
    serving = SGLangTelemetryProvider().build_run(load_fixture()).serving_requests[0]

    assert serving.prefix_cache_hit_tokens is None
    assert serving.prefix_cache_miss_tokens is None
    assert serving.metadata["aggregate_server_metrics"]["sglang:cache_hit_rate"] == 0.72
    assert serving.metadata["metric_reliability"]["cache_aggregate"] == (
        "available_in_aggregate_server_metrics"
    )


def test_sglang_optional_per_request_cached_tokens_are_preserved() -> None:
    data = load_fixture()
    record = cast(list[dict[str, Any]], data["records"])[0]
    response = cast(dict[str, Any], record["response"])
    usage = cast(dict[str, Any], response["usage"])
    usage["prompt_tokens_details"] = {"cached_tokens": 7}

    serving = SGLangTelemetryProvider().build_run(data).serving_requests[0]

    assert serving.input_tokens == 19
    assert serving.prefix_cache_hit_tokens == 7
    assert serving.prefix_cache_miss_tokens == 12
    assert serving.metadata["metric_reliability"]["cache_per_request"] == (
        "direct_from_usage.prompt_tokens_details.cached_tokens"
    )


def test_sglang_analysis_degrades_without_cache_or_prefill_metrics() -> None:
    report = analyze_run(SGLangTelemetryProvider().build_run(load_fixture()))
    rendered = render_report(report)

    assert "AgentPerf Report" in rendered
    assert "Requests" in rendered
    assert "First-token path evidence" in rendered
    assert "First-token path evidence          n/a" in rendered
    assert all(finding.id != "MATERIAL_PREFIX_CACHE_OPPORTUNITY" for finding in report.findings)


def test_html_report_renders_sglang_backend_and_client_ttft(tmp_path: Path) -> None:
    run = SGLangTelemetryProvider().build_run(load_fixture())
    trace = {
        "agent_run": {
            "agent_run_id": run.agent_run_id,
            "name": run.name,
            "steps": [
                {
                    "agent_step_id": step.agent_step_id,
                    "llm_calls": [
                        {
                            "llm_call_id": call.llm_call_id,
                            "llm_request_id": call.llm_request_id,
                            "serving_request_id": call.serving_request_id,
                            "model": call.model,
                            "backend": call.backend,
                            "input_tokens": call.input_tokens,
                            "output_tokens": call.output_tokens,
                            "prompt_components": [
                                {
                                    "name": component.name,
                                    "text": component.text,
                                    "metadata": component.metadata,
                                }
                                for component in call.prompt_components
                            ],
                        }
                        for call in step.llm_calls
                    ],
                    "tool_calls": [
                        {
                            "tool_call_id": tool.tool_call_id,
                            "name": tool.name,
                            "latency_ms": tool.latency_ms,
                            "output": tool.output,
                        }
                        for tool in step.tool_calls
                    ],
                }
                for step in run.steps
            ],
        },
        "serving_requests": [
            {
                "serving_request_id": request.serving_request_id,
                "llm_request_id": request.llm_request_id,
                "backend": request.backend,
                "model": request.model,
                "ttft_ms": request.ttft_ms,
                "decode_latency_ms": request.decode_latency_ms,
                "input_tokens": request.input_tokens,
                "output_tokens": request.output_tokens,
                "metadata": request.metadata,
            }
            for request in run.serving_requests
        ],
    }
    trace_path = tmp_path / "sglang-trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    html = render_html_report(load_html_report_input(trace_path))

    assert "sglang" in html
    assert "Client TTFT" in html
    assert "First-token evidence" in html
    assert "Serving Telemetry" in html


def test_cli_analyze_sglang_recording_success(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["analyze-sglang-recording", str(FIXTURE)])

    captured = capsys.readouterr()
    assert code == 0
    assert "AgentPerf Report" in captured.out


def test_m17_sglang_artifact_loads_with_exact_correlation_summary() -> None:
    artifact = load_artifact(M17_ARTIFACT)
    run = artifact.runs_for_comparison()[0]

    assert artifact.manifest.backend == "sglang"
    assert artifact.manifest.status == "COMPLETE"
    assert artifact.summary["correlation_success_rate"] == 1.0
    assert artifact.summary["correlated_serving_requests"] == 10
    assert artifact.summary["serving_timing"]["client_ttft_ms"] is None
    assert artifact.summary["serving_timing"]["cached_prompt_tokens"] == 1980
    assert len(run.llm_calls) == 10
    assert len(run.serving_requests) == 10
    assert sum(task.input_tokens or 0 for task in artifact.task_results) == 3561
    assert all(request.backend == "sglang" for request in run.serving_requests)
