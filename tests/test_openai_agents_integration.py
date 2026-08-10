from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agentperf.backends.vllm import VLLMTelemetryProvider
from agentperf.cli import main
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.openai_agents import (
    AgentPerfModelWrapper,
    OpenAIAgentsTraceProcessor,
    agent_run_from_openai_agents_export,
    prompt_components_from_openai_agents_input,
)
from agentperf.integrations.openai_compatible import (
    OpenAICompatibleRequestRecorder,
    build_vllm_recording_from_agent_run,
    correlation_summary,
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


def test_model_wrapper_injects_explicit_request_id_into_extra_body() -> None:
    asyncio.run(_assert_model_wrapper_injects_explicit_request_id_into_extra_body())


async def _assert_model_wrapper_injects_explicit_request_id_into_extra_body() -> None:
    from agents import ModelResponse, ModelSettings, Usage

    class CapturingModel:
        model = "fixture-model"

        def __init__(self) -> None:
            self.extra_body: dict[str, Any] | None = None

        async def get_response(
            self,
            system_instructions: str | None,
            input: Any,
            model_settings: Any,
            tools: list[Any],
            output_schema: Any,
            handoffs: list[Any],
            tracing: Any,
            *,
            previous_response_id: str | None,
            conversation_id: str | None,
            prompt: Any,
        ) -> ModelResponse:
            self.extra_body = dict(model_settings.extra_body)
            return ModelResponse(
                output=[],
                usage=Usage(input_tokens=3, output_tokens=2, total_tokens=5),
                response_id="resp-1",
            )

        def stream_response(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    recorder = TraceRecorder(agent_run_id="request-id-wrapper")
    model = CapturingModel()
    wrapper = AgentPerfModelWrapper(
        model,
        recorder,
        request_id_factory=lambda llm_call_id: f"agentperf-{llm_call_id}",
        request_extra_body={"return_token_ids": True},
    )

    await wrapper.get_response(
        "system",
        "hello",
        ModelSettings(extra_body={"temperature_seed": 7}),
        [],
        None,
        [],
        type("Tracing", (), {"is_disabled": lambda self: True})(),
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
    )

    assert model.extra_body == {
        "temperature_seed": 7,
        "request_id": "agentperf-openai-agents-llm-1",
        "return_token_ids": True,
    }
    run = recorder.finish()
    assert run.llm_calls[0].llm_request_id == "agentperf-openai-agents-llm-1"
    assert run.llm_calls[0].metadata["explicit_request_correlation"] is True


def test_model_wrapper_applies_model_settings_transform() -> None:
    asyncio.run(_assert_model_wrapper_applies_model_settings_transform())


async def _assert_model_wrapper_applies_model_settings_transform() -> None:
    from dataclasses import replace

    from agents import ModelResponse, ModelSettings, Usage

    class CapturingModel:
        model = "fixture-model"

        def __init__(self) -> None:
            self.extra_args: dict[str, Any] | None = None

        async def get_response(
            self,
            system_instructions: str | None,
            input: Any,
            model_settings: Any,
            tools: list[Any],
            output_schema: Any,
            handoffs: list[Any],
            tracing: Any,
            *,
            previous_response_id: str | None,
            conversation_id: str | None,
            prompt: Any,
        ) -> ModelResponse:
            self.extra_args = dict(model_settings.extra_args)
            return ModelResponse(
                output=[],
                usage=Usage(input_tokens=3, output_tokens=2, total_tokens=5),
                response_id="resp-1",
            )

        def stream_response(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

    recorder = TraceRecorder(agent_run_id="settings-transform")
    model = CapturingModel()
    wrapper = AgentPerfModelWrapper(
        model,
        recorder,
        model_settings_transform=lambda _id, _input, settings, _tools: replace(
            settings,
            extra_args={
                "tool_choice": {"type": "function", "function": {"name": "lookup_policy"}}
            },
        ),
    )

    await wrapper.get_response(
        "system",
        "hello",
        ModelSettings(),
        [],
        None,
        [],
        type("Tracing", (), {"is_disabled": lambda self: True})(),
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
    )

    assert model.extra_args == {
        "tool_choice": {"type": "function", "function": {"name": "lookup_policy"}}
    }


def test_openai_compatible_recorder_captures_and_merges_vllm_response() -> None:
    asyncio.run(_assert_openai_compatible_recorder_captures_and_merges_vllm_response())


async def _assert_openai_compatible_recorder_captures_and_merges_vllm_response() -> None:
    recorder = OpenAICompatibleRequestRecorder()
    await recorder.capture_response(
        _FakeHTTPResponse(
            url="http://localhost:8000/v1/chat/completions",
            request_body={"model": "fixture-model", "request_id": "agentperf-req-1"},
            response_body={
                "id": "chatcmpl-agentperf-req-1",
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
                "prompt_token_ids": [10, 11],
                "choices": [{"token_ids": [12]}],
                "metrics": {
                    "queue_time_ms": 1.0,
                    "time_to_first_token_ms": 2.0,
                    "generation_time_ms": 3.0,
                    "mean_itl_ms": 3.0,
                },
            },
        )
    )
    trace = TraceRecorder(agent_run_id="cross-layer-fixture")
    trace.record_llm_call(
        llm_call_id="llm-1",
        llm_request_id="agentperf-req-1",
        prompt_components={"user": "hello"},
    )
    trace.record_tool_call(tool_call_id="tool-1", name="lookup_policy", output="policy")
    agent_run = trace.finish()

    recording = build_vllm_recording_from_agent_run(
        agent_run=agent_run,
        captured_records=recorder.records,
        model="fixture-model",
        environment={"backend": "vllm"},
    )
    run = VLLMTelemetryProvider().build_run(recording)

    assert correlation_summary(recording, expected_llm_calls=1) == {
        "expected_llm_calls": 1,
        "correlated_serving_requests": 1,
        "missing_correlations": [],
        "correlation_success_rate": 1.0,
    }
    assert run.llm_calls[0].llm_request_id == "agentperf-req-1"
    assert run.llm_calls[0].serving_request_id == "chatcmpl-agentperf-req-1"
    assert run.serving_requests[0].queue_latency_ms == 1.0
    assert run.tool_calls[0].name == "lookup_policy"


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


class _FakeRequest:
    def __init__(self, url: str, request_body: dict[str, Any]) -> None:
        self.url = url
        self.content = json.dumps(request_body).encode("utf-8")
        self.headers = {"traceparent": "00-" + ("1" * 32) + "-" + ("2" * 16) + "-01"}


class _FakeHTTPResponse:
    def __init__(
        self,
        *,
        url: str,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
    ) -> None:
        self.request = _FakeRequest(url, request_body)
        self.content = json.dumps(response_body).encode("utf-8")
        self.status_code = 200

    async def aread(self) -> bytes:
        return bytes(self.content)
