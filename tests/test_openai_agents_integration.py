from __future__ import annotations

import json
from pathlib import Path

from agentperf.cli import main
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.openai_agents import (
    OpenAIAgentsTraceProcessor,
    agent_run_from_openai_agents_export,
    prompt_components_from_openai_agents_input,
)


def test_prompt_components_map_openai_agents_inputs_to_agentperf_components() -> None:
    components = prompt_components_from_openai_agents_input(
        system_instructions="Use the lookup tool.",
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Where should this ticket go?"}],
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "POLICY-BILLING: route to billing.",
            },
        ],
        tools=[type("Tool", (), {"name": "lookup_policy"})()],
    )

    assert [component.name for component in components] == [
        "system",
        "tool_schema",
        "user",
        "tool_result",
    ]
    assert components[-1].metadata["source_tool_call_ids"] == ["call-1"]


def test_openai_agents_export_converts_generation_and_function_spans() -> None:
    run = agent_run_from_openai_agents_export(_openai_agents_export_fixture())

    assert run.trace_id == "trace-1"
    assert len(run.llm_calls) == 1
    assert len(run.tool_calls) == 1
    assert run.llm_calls[0].model == "fixture-model"
    assert run.llm_calls[0].input_tokens == 42
    assert run.llm_calls[0].output_tokens == 7
    assert run.tool_calls[0].name == "lookup_policy"
    assert run.serving_requests == []


def test_trace_processor_preserves_framework_spans_and_function_calls() -> None:
    recorder = TraceRecorder(agent_run_id="processor-test")
    processor = OpenAIAgentsTraceProcessor(recorder)
    span = _FakeSpan(_function_span("span-tool", "trace-1"))

    processor.on_span_end(span)
    run = recorder.finish()

    assert len(processor.span_exports) == 1
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0].metadata["framework"] == "openai-agents-python"


def test_cli_analyze_openai_agents_export_success(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "openai_agents_export.json"
    path.write_text(json.dumps(_openai_agents_export_fixture()), encoding="utf-8")

    code = main(["analyze-openai-agents-export", str(path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "AgentPerf Report" in captured.out
    assert "LLM calls                          1" in captured.out


def _openai_agents_export_fixture() -> dict[str, object]:
    return {
        "name": "fixture openai agents export",
        "traces": [{"id": "trace-1", "workflow_name": "fixture"}],
        "spans": [
            _function_span("span-tool", "trace-1"),
            {
                "object": "trace.span",
                "id": "span-generation",
                "trace_id": "trace-1",
                "parent_id": "span-agent",
                "started_at": "2026-08-10T00:00:01+00:00",
                "ended_at": "2026-08-10T00:00:02+00:00",
                "span_data": {
                    "type": "generation",
                    "model": "fixture-model",
                    "input": [
                        {"role": "system", "content": "Use tools."},
                        {"role": "user", "content": "Route this ticket."},
                    ],
                    "output": [{"role": "assistant", "content": "Done."}],
                    "usage": {"input_tokens": 42, "output_tokens": 7},
                },
            },
        ],
    }


def _function_span(span_id: str, trace_id: str) -> dict[str, object]:
    return {
        "object": "trace.span",
        "id": span_id,
        "trace_id": trace_id,
        "parent_id": "span-agent",
        "started_at": "2026-08-10T00:00:00+00:00",
        "ended_at": "2026-08-10T00:00:01+00:00",
        "span_data": {
            "type": "function",
            "name": "lookup_policy",
            "input": '{"query": "billing"}',
            "output": "POLICY-BILLING: route to billing.",
            "mcp_data": None,
        },
    }


class _FakeSpan:
    def __init__(self, exported: dict[str, object]) -> None:
        self._exported = exported

    def export(self) -> dict[str, object]:
        return self._exported
