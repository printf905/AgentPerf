from __future__ import annotations

import json

import agentperf
from agentperf.analyzer import analyze_run
from agentperf.instrumentation import (
    TraceRecorder,
    current_recorder,
    trace_llm,
    trace_run,
    trace_tool,
)
from agentperf.schema.trace import PromptComponent, parse_agentperf_trace


def test_trace_run_records_nested_llm_and_tool_spans() -> None:
    with trace_run("external-agent", agent_run_id="run-1") as recorder:
        assert current_recorder() is recorder
        with recorder.step("planner"):
            recorder.record_llm_call(
                llm_call_id="llm-1",
                prompt_components={"system": "stable instructions", "user": "task"},
                model="fixture-model",
                input_tokens=4,
                output_tokens=2,
            )
            recorder.record_tool_call(
                tool_call_id="tool-1",
                name="search",
                input={"query": "task"},
                output="result text",
            )

    run = recorder.to_agent_run()

    assert run.agent_run_id == "run-1"
    assert len(run.steps) == 1
    assert len(run.llm_calls) == 1
    assert len(run.tool_calls) == 1
    assert run.serving_requests == []


def test_trace_tool_decorator_gracefully_noops_without_current_run() -> None:
    @trace_tool("lookup")
    def lookup(value: str) -> str:
        return value.upper()

    assert lookup("a") == "A"


def test_trace_tool_decorator_records_with_current_run() -> None:
    @trace_tool("lookup")
    def lookup(value: str) -> str:
        return value.upper()

    with trace_run("tool-run") as recorder:
        assert lookup("a") == "A"

    assert len(recorder.to_agent_run().tool_calls) == 1
    assert recorder.to_agent_run().tool_calls[0].name == "lookup"


def test_context_manager_trace_llm_and_trace_tool_record_public_byoa_shape() -> None:
    with trace_run("support-agent", agent_run_id="run-ctx") as recorder, trace_run(
        task_id="ticket-1",
        name="ticket",
    ):
        with trace_llm(
            model="fixture-model",
            provider="fixture-provider",
            components={"system": "stable instructions", "user": "ticket"},
        ) as call:
            call.record_response(
                output="answer",
                input_tokens=5,
                output_tokens=1,
                request_id="req-1",
            )
        with trace_tool("lookup", tool_call_id="tool-1", input={"q": "ticket"}) as tool:
            tool.record_output("policy")

    run = recorder.to_agent_run()

    assert run.steps[0].metadata["task_id"] == "ticket-1"
    assert len(run.llm_calls) == 1
    assert run.llm_calls[0].llm_request_id == "req-1"
    assert run.llm_calls[0].metadata["status"] == "COMPLETE"
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0].metadata["status"] == "COMPLETE"


def test_context_manager_trace_llm_records_failure_and_propagates() -> None:
    with trace_run("failure", agent_run_id="run-fail") as recorder:
        try:
            with trace_llm(components={"user": "fail"}):
                raise RuntimeError("provider failed")
        except RuntimeError:
            pass

    call = recorder.to_agent_run().llm_calls[0]

    assert call.metadata["status"] == "FAILED"
    assert "provider failed" in str(call.metadata["error"])


def test_context_manager_trace_tool_records_failure_and_propagates() -> None:
    with trace_run("failure", agent_run_id="run-tool-fail") as recorder:
        try:
            with trace_tool("lookup"):
                raise RuntimeError("tool failed")
        except RuntimeError:
            pass

    call = recorder.to_agent_run().tool_calls[0]

    assert call.metadata["status"] == "FAILED"
    assert "tool failed" in str(call.metadata["error"])


def test_trace_llm_requires_active_recorder() -> None:
    try:
        with trace_llm(components={"user": "missing"}):
            pass
    except RuntimeError as exc:
        assert "requires an active" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("trace_llm should require an active recorder")


def test_recorder_json_round_trip_and_agent_only_analysis() -> None:
    recorder = TraceRecorder(agent_run_id="round-trip")
    recorder.record_tool_call(tool_call_id="tool-1", name="lookup", output="stable result")
    recorder.record_llm_call(
        llm_call_id="llm-1",
        prompt_components=[
            PromptComponent(name="system", text="stable instructions"),
            PromptComponent(
                name="tool_result",
                text="stable result",
                metadata={"source_tool_call_ids": ["tool-1"]},
            ),
        ],
    )
    data = json.loads(json.dumps(recorder.to_dict()))
    run = parse_agentperf_trace(data)
    report = analyze_run(run)

    assert len(run.llm_calls) == 1
    assert [component.name for component in run.llm_calls[0].prompt_components] == [
        "system",
        "tool_result",
    ]
    assert [call.llm_call_id for call in report.correlation.unresolved_llm_calls] == ["llm-1"]
    assert report.token_attribution is not None


def test_package_root_exports_public_instrumentation_api() -> None:
    assert agentperf.TraceRecorder is TraceRecorder
    assert agentperf.trace_run is trace_run
    assert agentperf.trace_llm is trace_llm
