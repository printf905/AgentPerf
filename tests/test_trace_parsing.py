from __future__ import annotations

import pytest

from agentperf.schema.trace import TraceParseError, parse_agentperf_trace


def test_parse_agent_and_serving_trace() -> None:
    run = parse_agentperf_trace(
        {
            "schema_version": "0.1",
            "synthetic": True,
            "agent_run": {
                "agent_run_id": "run-1",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "llm_request_id": "req-1",
                                "serving_request_id": "srv-1",
                                "prompt": {"system": "stable", "user": "hello"},
                            }
                        ],
                        "tool_calls": [{"tool_call_id": "tool-1", "name": "search"}],
                    }
                ],
            },
            "serving_requests": [{"serving_request_id": "srv-1", "llm_request_id": "req-1"}],
        }
    )

    assert run.agent_run_id == "run-1"
    assert run.synthetic is True
    assert len(run.llm_calls) == 1
    assert len(run.tool_calls) == 1
    assert len(run.serving_requests) == 1
    assert run.llm_calls[0].prompt_text() == "stable\nhello"


def test_parse_serving_only_trace() -> None:
    run = parse_agentperf_trace(
        {
            "serving_requests": [
                {
                    "serving_request_id": "srv-1",
                    "prefill_latency_ms": 10,
                    "prefill_path_latency_ms": 12,
                }
            ]
        }
    )

    assert run.agent_run_id == "serving-only"
    assert run.llm_calls == []
    assert len(run.serving_requests) == 1
    assert run.serving_requests[0].prefill_path_latency_ms == 12


def test_malformed_trace_has_clear_error() -> None:
    with pytest.raises(TraceParseError, match="agent run missing required field"):
        parse_agentperf_trace({"agent_run": {"steps": []}})


def test_numeric_fields_are_validated() -> None:
    with pytest.raises(TraceParseError, match="prefill_latency_ms must be numeric"):
        parse_agentperf_trace(
            {"serving_requests": [{"serving_request_id": "srv-1", "prefill_latency_ms": "slow"}]}
        )
