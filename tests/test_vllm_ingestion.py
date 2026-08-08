from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from agentperf.analyzer import analyze_run
from agentperf.backends.vllm import VLLMTelemetryProvider
from agentperf.cli import main
from agentperf.reporters.terminal import render_report
from agentperf.schema.trace import parse_agentperf_trace
from agentperf.tokenization import ApproximateTokenizerProvider, ExactTokenIdsProvider

ROOT = Path(__file__).resolve().parents[1]


def load_fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            (
                ROOT / "examples/recorded_telemetry/vllm_openai_response_fixture.json"
            ).read_text(encoding="utf-8")
        ),
    )


def test_vllm_recording_converts_to_normalized_trace() -> None:
    run = VLLMTelemetryProvider().build_run(load_fixture())

    assert run.synthetic is False
    assert run.metadata["backend"] == "vllm"
    assert len(run.llm_calls) == 1
    assert len(run.serving_requests) == 1
    call = run.llm_calls[0]
    serving = run.serving_requests[0]
    assert call.llm_request_id == "agentperf-fixture-0"
    assert call.serving_request_id == "chatcmpl-agentperf-fixture-0"
    assert serving.serving_request_id == "chatcmpl-agentperf-fixture-0"
    assert serving.llm_request_id == "agentperf-fixture-0"
    assert call.tokenization_mode == "EXACT"
    assert serving.tokenization_mode == "EXACT"
    assert call.prompt_token_ids == list(range(1, 23))
    assert call.output_token_ids == [501, 502, 503]


def test_vllm_adapter_preserves_units_and_derived_fields() -> None:
    run = VLLMTelemetryProvider().build_run(load_fixture())
    serving = run.serving_requests[0]

    assert serving.queue_latency_ms == 5.0
    assert serving.ttft_ms == 80.0
    assert serving.prefill_latency_ms is None
    assert serving.prefill_path_latency_ms == 80.0
    assert serving.decode_latency_ms == 24.0
    assert serving.tpot_ms == 12.0
    assert serving.prefix_cache_hit_tokens == 2
    assert serving.prefix_cache_miss_tokens == 20
    assert (
        serving.metadata["metric_reliability"]["measurement_semantics"][
            "time_to_first_token_ms"
        ]
        == "scheduled_to_first_token"
    )


def test_vllm_adapter_handles_missing_optional_telemetry() -> None:
    data = {
        "agent_run_id": "missing-vllm-fields",
        "model": "fixture-model",
        "records": [
            {
                "client_request_id": "req-1",
                "llm_call_id": "llm-1",
                "prompt_components": {"system": "stable", "user": "task"},
                "response": {"id": "chatcmpl-req-1", "usage": {"prompt_tokens": 4}},
            }
        ],
    }

    run = VLLMTelemetryProvider().build_run(data)
    serving = run.serving_requests[0]
    assert serving.queue_latency_ms is None
    assert serving.prefill_latency_ms is None
    assert serving.prefill_path_latency_ms is None
    assert serving.prefix_cache_hit_tokens is None
    assert serving.tokenization_mode == "UNKNOWN"
    assert run.llm_calls[0].tokenization_mode == "APPROXIMATE"


def test_vllm_seconds_fallback_is_converted_to_milliseconds() -> None:
    data = load_fixture()
    records = cast(list[dict[str, Any]], data["records"])
    response = cast(dict[str, Any], records[0]["response"])
    response["metrics"] = {
        "queue_time": 0.006,
        "time_to_first_token": 0.09,
        "generation_time": 0.03,
        "mean_itl": 0.015,
    }

    serving = VLLMTelemetryProvider().build_run(data).serving_requests[0]

    assert serving.queue_latency_ms == 6.0
    assert serving.ttft_ms == 90.0
    assert serving.prefill_path_latency_ms == 90.0
    assert serving.decode_latency_ms == 30.0
    assert serving.tpot_ms == 15.0


def test_tokenizer_providers_label_exact_and_approximate_modes() -> None:
    approximate = ApproximateTokenizerProvider().tokenize("hello, world")
    exact = ExactTokenIdsProvider({"hello, world": [10, 11, 12]}).tokenize("hello, world")
    fallback = ExactTokenIdsProvider({}).tokenize("hello, world")

    assert approximate.mode == "APPROXIMATE"
    assert exact.mode == "EXACT"
    assert exact.token_ids == [10, 11, 12]
    assert fallback.mode == "APPROXIMATE"


def test_normalized_parser_accepts_tokenization_mode_and_token_ids() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "tokenized-run",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "prompt_token_ids": [1, 2],
                                "output_token_ids": [3],
                                "tokenization_mode": "EXACT",
                            }
                        ],
                    }
                ],
            },
            "serving_requests": [
                {
                    "serving_request_id": "srv-1",
                    "tokenization_mode": "EXACT",
                }
            ],
        }
    )

    assert run.llm_calls[0].prompt_token_ids == [1, 2]
    assert run.llm_calls[0].tokenization_mode == "EXACT"
    assert run.serving_requests[0].tokenization_mode == "EXACT"


def test_finding_provenance_reaches_terminal_debug_output() -> None:
    data = {
        "agent_run_id": "realish-vllm-prefix",
        "model": "fixture-model",
        "records": [
            _record("llm-1", "req-1", "chatcmpl-req-1", cached=10),
            _record("llm-2", "req-2", "chatcmpl-req-2", cached=10),
        ],
    }
    report = analyze_run(VLLMTelemetryProvider().build_run(data))
    output = render_report(report, show_provenance=True)

    assert "PREFIX_CACHE_OPPORTUNITY" in output
    assert "Provenance:" in output
    assert "llm request ids" in output
    assert "req-1" in output
    assert "serving request ids" in output
    assert "chatcmpl-req-1" in output


def test_vllm_report_labels_prefill_path_proxy() -> None:
    report = analyze_run(VLLMTelemetryProvider().build_run(load_fixture()))
    output = render_report(report)

    assert "Prefill path proxy" in output
    assert "Prefill                            " not in output


def test_cli_analyze_vllm_recording_success(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(
        [
            "analyze-vllm-recording",
            str(ROOT / "examples/recorded_telemetry/vllm_openai_response_fixture.json"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "AgentPerf Report" in captured.out


def _record(
    call_id: str,
    client_request_id: str,
    serving_request_id: str,
    *,
    cached: int,
) -> dict[str, object]:
    shared = " ".join(f"stable{i}" for i in range(80))
    prompt_token_ids = list(range(100))
    return {
        "client_request_id": client_request_id,
        "request_id": serving_request_id,
        "llm_call_id": call_id,
        "prompt_components": {
            "system": shared,
            "user": f"unique task {call_id}",
        },
        "response": {
            "id": serving_request_id,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 4,
                "prompt_tokens_details": {"cached_tokens": cached},
            },
            "prompt_token_ids": prompt_token_ids,
            "choices": [{"token_ids": [1, 2, 3, 4]}],
            "metrics": {
                "queue_time_ms": 10,
                "time_to_first_token_ms": 800,
                "generation_time_ms": 80,
                "mean_itl_ms": 20,
            },
        },
    }
