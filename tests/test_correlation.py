from __future__ import annotations

from agentperf.correlation.correlator import TraceCorrelator
from agentperf.schema.trace import parse_agentperf_trace


def test_correlates_by_serving_request_id() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "run-1",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [{"llm_call_id": "llm-1", "serving_request_id": "srv-1"}],
                    }
                ],
            },
            "serving_requests": [{"serving_request_id": "srv-1"}],
        }
    )

    result = TraceCorrelator().correlate(run)

    assert result.llm_to_serving["llm-1"].serving_request_id == "srv-1"
    assert result.unresolved_llm_calls == []


def test_correlates_by_llm_request_id_fallback() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "run-1",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [{"llm_call_id": "llm-1", "llm_request_id": "req-1"}],
                    }
                ],
            },
            "serving_requests": [{"serving_request_id": "srv-1", "llm_request_id": "req-1"}],
        }
    )

    result = TraceCorrelator().correlate(run)

    assert result.llm_to_serving["llm-1"].serving_request_id == "srv-1"


def test_unmatched_spans_remain_unresolved() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "run-1",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [{"llm_call_id": "llm-1", "llm_request_id": "req-a"}],
                    }
                ],
            },
            "serving_requests": [{"serving_request_id": "srv-1", "llm_request_id": "req-b"}],
        }
    )

    result = TraceCorrelator().correlate(run)

    assert result.llm_to_serving == {}
    assert [call.llm_call_id for call in result.unresolved_llm_calls] == ["llm-1"]
    assert [request.serving_request_id for request in result.unresolved_serving_requests] == [
        "srv-1"
    ]
