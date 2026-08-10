from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

from agentperf.instrumentation import TraceRecorder
from agentperf.schema.trace import AgentRun, PromptComponent

try:
    from agents import Model as _OpenAIAgentsModel
except ImportError:  # pragma: no cover - optional dependency boundary
    class _OpenAIAgentsModel:  # type: ignore[no-redef]
        pass


class _ModelLike(Protocol):
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
    ) -> Any: ...

    def stream_response(
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
    ) -> AsyncIterator[Any]: ...


class AgentPerfModelWrapper(_OpenAIAgentsModel):
    """OpenAI Agents SDK `Model` wrapper that records normalized LLM calls."""

    def __init__(
        self,
        model: _ModelLike,
        recorder: TraceRecorder,
        *,
        model_name: str | None = None,
        provider: str = "openai-agents-python",
        request_id_factory: Callable[[str], str] | None = None,
        request_extra_body: Mapping[str, Any] | None = None,
        request_id_body_key: str = "request_id",
        model_settings_transform: Callable[[str, Any, Any, list[Any]], Any] | None = None,
    ) -> None:
        self._model = model
        self._recorder = recorder
        self._model_name = model_name
        self._provider = provider
        self._calls = 0
        self._request_id_factory = request_id_factory
        self._request_extra_body = dict(request_extra_body or {})
        self._request_id_body_key = request_id_body_key
        self._model_settings_transform = model_settings_transform

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
    ) -> Any:
        self._calls += 1
        llm_call_id = f"openai-agents-llm-{self._calls}"
        if self._model_settings_transform is not None:
            model_settings = self._model_settings_transform(
                llm_call_id,
                input,
                model_settings,
                tools,
            )
        propagated_request_id = (
            self._request_id_factory(llm_call_id) if self._request_id_factory else None
        )
        if propagated_request_id is not None:
            model_settings = _with_extra_body(
                model_settings,
                {
                    self._request_id_body_key: propagated_request_id,
                    **self._request_extra_body,
                },
            )
        components = prompt_components_from_openai_agents_input(
            system_instructions=system_instructions,
            input=input,
            tools=tools,
        )
        start = time.perf_counter()
        started_at = _now_iso()
        response = await self._model.get_response(
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )
        ended_at = _now_iso()
        usage = _usage_dict(getattr(response, "usage", None))
        request_id = _optional_str(getattr(response, "request_id", None))
        response_id = _optional_str(getattr(response, "response_id", None))
        llm_request_id = propagated_request_id or request_id or response_id or llm_call_id
        self._record_tool_results_seen_in_prompt(input)
        self._recorder.record_llm_call(
            llm_call_id=llm_call_id,
            llm_request_id=llm_request_id,
            prompt_components=components,
            model=self._model_name or _optional_str(getattr(self._model, "model", None)),
            provider=self._provider,
            input_tokens=_token_usage_value(usage, "input_tokens", "prompt_tokens"),
            output_tokens=_token_usage_value(usage, "output_tokens", "completion_tokens"),
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=(time.perf_counter() - start) * 1000,
            tokenization_mode="APPROXIMATE",
            metadata={
                "framework": "openai-agents-python",
                "response_id": response_id,
                "previous_response_id": previous_response_id,
                "conversation_id": conversation_id,
                "model_settings": _stringify_model_settings(model_settings),
                "propagated_request_id": propagated_request_id,
                "explicit_request_correlation": propagated_request_id is not None,
            },
        )
        return response

    def stream_response(
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
    ) -> AsyncIterator[Any]:
        return self._model.stream_response(
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

    async def close(self) -> None:
        close = getattr(self._model, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def _cleanup_on_run_end(self, owner: object) -> None:
        cleanup = getattr(self._model, "_cleanup_on_run_end", None)
        if cleanup is not None:
            result = cleanup(owner)
            if hasattr(result, "__await__"):
                await result

    def get_retry_advice(self, request: Any) -> Any:
        retry = getattr(self._model, "get_retry_advice", None)
        if retry is None:
            return None
        return retry(request)

    def _record_tool_results_seen_in_prompt(self, input: Any) -> None:
        for item in _iter_input_items(input):
            if item.get("type") not in {"function_call_output", "tool_call_output"}:
                continue
            call_id = _optional_str(item.get("call_id") or item.get("tool_call_id"))
            if call_id is None:
                continue
            self._recorder.record_tool_call(
                tool_call_id=call_id,
                name=_optional_str(item.get("name")) or "function_tool",
                output=item.get("output"),
                metadata={
                    "framework": "openai-agents-python",
                    "source": "model_input_tool_result",
                },
            )


class OpenAIAgentsTraceProcessor:
    """Trace processor compatible with the OpenAI Agents SDK tracing API."""

    def __init__(self, recorder: TraceRecorder, *, capture_function_spans: bool = True) -> None:
        self.recorder = recorder
        self.capture_function_spans = capture_function_spans
        self.trace_exports: list[dict[str, Any]] = []
        self.span_exports: list[dict[str, Any]] = []

    def on_trace_start(self, trace: Any) -> None:
        exported = _export_item(trace)
        if exported:
            self.trace_exports.append(exported)
            self.recorder.metadata.setdefault("external_traces", []).append(exported)

    def on_trace_end(self, trace: Any) -> None:
        exported = _export_item(trace)
        if exported:
            self.recorder.metadata.setdefault("external_trace_ends", []).append(exported)

    def on_span_start(self, span: Any) -> None:
        return None

    def on_span_end(self, span: Any) -> None:
        exported = _export_item(span)
        if not exported:
            return
        self.span_exports.append(exported)
        span_data = _span_data(exported)
        span_type = _span_type(span_data)
        if span_type in {"task", "turn", "agent"}:
            self.recorder.metadata.setdefault("openai_agents_spans", []).append(exported)
        elif span_type == "function" and self.capture_function_spans:
            self._record_function_span(exported, span_data)

    def shutdown(self) -> None:
        return None

    def force_flush(self) -> None:
        return None

    def write_export(self, path: Path) -> None:
        payload = {
            "framework": "openai-agents-python",
            "traces": self.trace_exports,
            "spans": self.span_exports,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _record_function_span(self, exported: dict[str, Any], span_data: dict[str, Any]) -> None:
        self.recorder.record_tool_call(
            tool_call_id=(
                _optional_str(exported.get("id"))
                or f"openai-agents-tool-{len(self.span_exports)}"
            ),
            name=_optional_str(span_data.get("name")) or "function_tool",
            input=span_data.get("input"),
            output=span_data.get("output"),
            started_at=_optional_str(exported.get("started_at")),
            ended_at=_optional_str(exported.get("ended_at")),
            latency_ms=_duration_ms(exported),
            metadata={
                "framework": "openai-agents-python",
                "span_id": exported.get("id"),
                "parent_span_id": exported.get("parent_id"),
                "capture_source": "function_span",
            },
        )


def agent_run_from_openai_agents_export(data: dict[str, Any]) -> AgentRun:
    recorder = TraceRecorder(
        agent_run_id=_optional_str(data.get("agent_run_id")) or "openai-agents-export",
        name=_optional_str(data.get("name")) or "OpenAI Agents export",
        trace_id=_first_trace_id(data),
        metadata={"framework": "openai-agents-python", "source": "export"},
    )
    spans = [_dict(item) for item in _list(data.get("spans"))]
    for span in sorted(spans, key=lambda item: str(item.get("started_at") or "")):
        span_data = _span_data(span)
        span_type = _span_type(span_data)
        if span_type == "function":
            OpenAIAgentsTraceProcessor(recorder)._record_function_span(span, span_data)
        elif span_type in {"generation", "response"}:
            recorder.record_llm_call(
                llm_call_id=(
                    _optional_str(span.get("id"))
                    or f"llm-{len(recorder.to_agent_run().llm_calls) + 1}"
                ),
                llm_request_id=_optional_str(span_data.get("response_id")),
                model=_optional_str(span_data.get("model")),
                prompt_components=prompt_components_from_openai_agents_input(
                    system_instructions=None,
                    input=span_data.get("input"),
                    tools=[],
                ),
                input_tokens=_token_usage_value(
                    _dict(span_data.get("usage")),
                    "input_tokens",
                    "prompt_tokens",
                ),
                output_tokens=_token_usage_value(
                    _dict(span_data.get("usage")),
                    "output_tokens",
                    "completion_tokens",
                ),
                started_at=_optional_str(span.get("started_at")),
                ended_at=_optional_str(span.get("ended_at")),
                latency_ms=_duration_ms(span),
                tokenization_mode="APPROXIMATE",
                metadata={"framework": "openai-agents-python", "span_type": span_type},
            )
    return recorder.finish()


def prompt_components_from_openai_agents_input(
    *,
    system_instructions: str | None,
    input: Any,
    tools: Sequence[Any],
) -> list[PromptComponent]:
    components: list[PromptComponent] = []
    if system_instructions:
        components.append(PromptComponent(name="system", text=system_instructions))
    if tools:
        tool_names = [_tool_name(tool) for tool in tools]
        components.append(
            PromptComponent(
                name="tool_schema",
                text="\n".join(name for name in tool_names if name),
                metadata={"framework": "openai-agents-python", "representation": "tool_names"},
            )
        )
    for item in _iter_input_items(input):
        role = _optional_str(item.get("role"))
        item_type = _optional_str(item.get("type"))
        text = _text_from_input_item(item)
        if not text:
            continue
        if item_type in {"function_call_output", "tool_call_output"}:
            call_id = _optional_str(item.get("call_id") or item.get("tool_call_id"))
            components.append(
                PromptComponent(
                    name="tool_result",
                    text=text,
                    metadata={"source_tool_call_ids": [call_id] if call_id else []},
                )
            )
        elif role == "system":
            components.append(PromptComponent(name="system", text=text))
        elif role == "user":
            components.append(PromptComponent(name="user", text=text))
        elif role in {"assistant", "tool"}:
            components.append(PromptComponent(name="history", text=text))
        else:
            components.append(PromptComponent(name="other", text=text))
    if isinstance(input, str) and input:
        components.append(PromptComponent(name="user", text=input))
    return components


def _iter_input_items(input_value: Any) -> list[dict[str, Any]]:
    if isinstance(input_value, list):
        return [_dict(_model_dump(item)) for item in input_value]
    if isinstance(input_value, Mapping):
        return [_dict(input_value)]
    return []


def _text_from_input_item(item: dict[str, Any]) -> str:
    if "output" in item:
        return str(item.get("output") or "")
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            data = _dict(_model_dump(part))
            text = data.get("text") or data.get("content") or data.get("input_text")
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    if item.get("arguments"):
        return str(item.get("arguments"))
    return ""


def _usage_dict(usage: Any) -> dict[str, Any]:
    return _dict(_model_dump(usage))


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return vars(value)
    return value


def _export_item(value: Any) -> dict[str, Any]:
    if hasattr(value, "export"):
        exported = value.export()
        return _dict(exported)
    return _dict(value)


def _span_data(span: dict[str, Any]) -> dict[str, Any]:
    data = _dict(span.get("span_data"))
    if data.get("type") == "custom":
        nested = _dict(data.get("data"))
        if nested.get("sdk_span_type"):
            nested["type"] = str(nested["sdk_span_type"])
            return nested
    return data


def _span_type(span_data: dict[str, Any]) -> str:
    return str(span_data.get("type") or span_data.get("sdk_span_type") or "")


def _first_trace_id(data: dict[str, Any]) -> str | None:
    trace_id = _optional_str(data.get("trace_id"))
    if trace_id:
        return trace_id
    for trace in _list(data.get("traces")):
        trace_id = _optional_str(_dict(trace).get("id"))
        if trace_id:
            return trace_id
    for span in _list(data.get("spans")):
        trace_id = _optional_str(_dict(span).get("trace_id"))
        if trace_id:
            return trace_id
    return None


def _token_usage_value(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _duration_ms(span: dict[str, Any]) -> float | None:
    started_at = _optional_str(span.get("started_at"))
    ended_at = _optional_str(span.get("ended_at"))
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - start).total_seconds() * 1000


def _tool_name(tool: Any) -> str:
    return (
        _optional_str(getattr(tool, "name", None))
        or _optional_str(getattr(tool, "__name__", None))
        or type(tool).__name__
    )


def _stringify_model_settings(settings: Any) -> str | None:
    if settings is None:
        return None
    dumped = _model_dump(settings)
    if isinstance(dumped, dict):
        return json.dumps(dumped, sort_keys=True, default=str)
    return str(settings)


def _with_extra_body(settings: Any, extra_body: dict[str, Any]) -> Any:
    dumped = _model_dump(settings)
    existing_extra_body = _dict(dumped.get("extra_body")) if isinstance(dumped, dict) else {}
    merged = {**existing_extra_body, **extra_body}
    try:
        return replace(settings, extra_body=merged)
    except TypeError:
        settings.extra_body = merged
        return settings


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
