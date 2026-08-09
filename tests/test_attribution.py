from __future__ import annotations

from agentperf.analyzer import analyze_run
from agentperf.metrics.attribution import (
    component_token_attribution,
    context_growth_rows,
    tool_reinjections,
)
from agentperf.schema.trace import AgentRun, parse_agentperf_trace


def test_component_attribution_distinguishes_processed_and_unique_tokens() -> None:
    run = _tool_bloat_run()
    attribution = component_token_attribution(run)

    assert attribution.processed_tokens_by_component["tool_result"] == 2400
    assert attribution.unique_tokens_by_component["tool_result"] == 1200
    assert attribution.processed_tokens_by_component["history"] > 0
    assert attribution.total_processed_tokens > attribution.total_unique_tokens


def test_tool_result_reinjection_accounting() -> None:
    run = _tool_bloat_run()
    reinjection = tool_reinjections(run)[0]

    assert reinjection.tool_call_id == "search-1"
    assert reinjection.raw_output_tokens == 1200
    assert reinjection.reinjected_calls == ["llm-2", "llm-3"]
    assert reinjection.cumulative_processed_tokens == 2400
    assert reinjection.share_of_run_input_tokens > 0.5


def test_tool_output_bloat_detector() -> None:
    report = analyze_run(_tool_bloat_run())
    finding = next(
        finding for finding in report.findings if finding.id == "TOOL_OUTPUT_BLOAT"
    )

    assert finding.evidence["tool_call_id"] == "search-1"
    assert finding.evidence["downstream_reinjections"] == 2
    assert finding.evidence["cumulative_downstream_processed_tokens"] == 2400


def test_context_growth_rows_include_history_and_tool_results() -> None:
    rows = context_growth_rows(_tool_bloat_run())

    assert [row.input_tokens for row in rows] == [50, 1300, 1450]
    assert rows[1].tool_result_tokens == 1200
    assert rows[2].history_tokens == 150
    assert rows[2].tool_result_tokens == 1200


def test_missing_component_metadata_is_safe() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "missing-metadata",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "prompt": {"tool_results": "raw result text"},
                                "input_tokens": 3,
                            }
                        ],
                    }
                ],
            }
        }
    )

    assert tool_reinjections(run) == []
    assert component_token_attribution(run).processed_tokens_by_component[
        "tool_result"
    ] == 3


def test_real_agent_trace_hierarchy_from_vllm_recording() -> None:
    from agentperf.backends.vllm import VLLMTelemetryProvider

    data = {
        "agent_run_id": "agent-recording",
        "model": "fixture-model",
        "tool_calls": [
            {
                "agent_step_id": "step-2",
                "tool_call_id": "search-1",
                "name": "search",
                "input": {"query": "alpha"},
                "output": "alpha result",
            }
        ],
        "records": [
            _record("step-1", "llm-1", "req-1"),
            _record("step-3", "llm-2", "req-2"),
        ],
    }

    run = VLLMTelemetryProvider().build_run(data)

    assert [step.agent_step_id for step in run.steps] == ["step-1", "step-2", "step-3"]
    assert len(run.tool_calls) == 1
    assert run.llm_calls[0].prompt_components[0].metadata["role"] == "planner"


def _tool_bloat_run() -> AgentRun:
    tool_output = " ".join(f"evidence{i}" for i in range(1200))
    return parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "tool-bloat",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "prompt": {"system": " ".join(["plan"] * 50)},
                                "input_tokens": 50,
                            }
                        ],
                    },
                    {
                        "agent_step_id": "step-2",
                        "tool_calls": [
                            {
                                "tool_call_id": "search-1",
                                "name": "search",
                                "output": tool_output,
                            }
                        ],
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-2",
                                "prompt": [
                                    {
                                        "name": "history",
                                        "text": " ".join(["previous"] * 100),
                                    },
                                    {
                                        "name": "tool_results",
                                        "text": tool_output,
                                        "metadata": {
                                            "source_tool_call_ids": ["search-1"]
                                        },
                                    },
                                ],
                                "input_tokens": 1300,
                            }
                        ],
                    },
                    {
                        "agent_step_id": "step-3",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-3",
                                "prompt": [
                                    {
                                        "name": "history",
                                        "text": " ".join(["previous"] * 150),
                                    },
                                    {
                                        "name": "tool_results",
                                        "text": tool_output,
                                        "metadata": {
                                            "source_tool_call_ids": ["search-1"]
                                        },
                                    },
                                ],
                                "input_tokens": 1450,
                            }
                        ],
                    },
                ],
            }
        }
    )


def _record(step_id: str, call_id: str, request_id: str) -> dict[str, object]:
    return {
        "agent_step_id": step_id,
        "llm_call_id": call_id,
        "client_request_id": request_id,
        "prompt_components": [
            {
                "name": "system",
                "text": "planner",
                "metadata": {"role": "planner"},
            }
        ],
        "response": {
            "id": f"cmpl-{request_id}",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "choices": [{"text": "ok", "token_ids": [1]}],
        },
    }
