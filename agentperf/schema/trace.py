from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


class TraceParseError(ValueError):
    """Raised when a trace file cannot be normalized."""


PROMPT_COMPONENT_ORDER = (
    "system",
    "history",
    "tool_schemas",
    "tool_results",
    "other_context",
    "user",
)

TokenizationMode = Literal["EXACT", "APPROXIMATE", "UNKNOWN"]


@dataclass(frozen=True)
class PromptComponent:
    name: str
    text: str


@dataclass(frozen=True)
class ServingRequest:
    serving_request_id: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    llm_request_id: str | None = None
    model: str | None = None
    backend: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    queue_latency_ms: float | None = None
    prefill_latency_ms: float | None = None
    prefill_path_latency_ms: float | None = None
    decode_latency_ms: float | None = None
    ttft_ms: float | None = None
    tpot_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    prefix_cache_hit_tokens: int | None = None
    prefix_cache_miss_tokens: int | None = None
    kv_cache_used_tokens: int | None = None
    kv_cache_capacity_tokens: int | None = None
    kv_cache_evictions: int | None = None
    tokenization_mode: TokenizationMode = "UNKNOWN"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_model_latency_ms(self) -> float | None:
        prefill_or_path = (
            self.prefill_latency_ms
            if self.prefill_latency_ms is not None
            else self.prefill_path_latency_ms
        )
        parts = [self.queue_latency_ms, prefill_or_path, self.decode_latency_ms]
        known = [part for part in parts if part is not None]
        if known:
            return float(sum(known))
        return self.ttft_ms


@dataclass(frozen=True)
class LLMCall:
    llm_call_id: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    agent_step_id: str | None = None
    llm_request_id: str | None = None
    serving_request_id: str | None = None
    model: str | None = None
    provider: str | None = None
    backend: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    prompt_components: list[PromptComponent] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_token_ids: list[int] | None = None
    output_token_ids: list[int] | None = None
    tokenization_mode: TokenizationMode = "UNKNOWN"
    ttft_ms: float | None = None
    tpot_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def prompt_text(self) -> str:
        return "\n".join(component.text for component in self.prompt_components if component.text)

    def prompt_component_texts(self) -> list[str]:
        return [component.text for component in self.prompt_components if component.text]


@dataclass(frozen=True)
class ToolCall:
    tool_call_id: str
    name: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    latency_ms: float | None = None
    input: Any | None = None
    output: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentStep:
    agent_step_id: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    llm_calls: list[LLMCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRun:
    agent_run_id: str
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    name: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    steps: list[AgentStep] = field(default_factory=list)
    serving_requests: list[ServingRequest] = field(default_factory=list)
    synthetic: bool = False
    schema_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def llm_calls(self) -> list[LLMCall]:
        return [call for step in self.steps for call in step.llm_calls]

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [call for step in self.steps for call in step.tool_calls]

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.ended_at:
            start = parse_datetime(self.started_at)
            end = parse_datetime(self.ended_at)
            if start and end:
                return (end - start).total_seconds() * 1000
        return None


def parse_agentperf_trace(data: dict[str, Any]) -> AgentRun:
    if not isinstance(data, dict):
        raise TraceParseError("trace root must be a JSON object")

    agent_run_data = data.get("agent_run")
    serving_requests = [
        _parse_serving_request(item) for item in _list(data.get("serving_requests"))
    ]

    if agent_run_data is None:
        if not serving_requests:
            raise TraceParseError("trace must contain agent_run or serving_requests")
        agent_run_data = {"agent_run_id": "serving-only", "steps": []}

    if not isinstance(agent_run_data, dict):
        raise TraceParseError("agent_run must be an object")

    agent_run_id = _required_str(agent_run_data, "agent_run_id", "agent run")
    steps = [_parse_step(item) for item in _list(agent_run_data.get("steps"))]

    inline_serving = [
        _parse_serving_request(item) for item in _list(agent_run_data.get("serving_requests"))
    ]
    return AgentRun(
        agent_run_id=agent_run_id,
        trace_id=_optional_str(agent_run_data, "trace_id"),
        span_id=_optional_str(agent_run_data, "span_id"),
        parent_span_id=_optional_str(agent_run_data, "parent_span_id"),
        name=_optional_str(agent_run_data, "name"),
        started_at=_optional_str(agent_run_data, "started_at"),
        ended_at=_optional_str(agent_run_data, "ended_at"),
        steps=steps,
        serving_requests=serving_requests + inline_serving,
        synthetic=bool(data.get("synthetic", False)),
        schema_version=_optional_str(data, "schema_version"),
        metadata=_dict(agent_run_data.get("metadata")),
    )


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_step(data: Any) -> AgentStep:
    if not isinstance(data, dict):
        raise TraceParseError("agent_run.steps entries must be objects")
    step_id = _required_str(data, "agent_step_id", "agent step")
    return AgentStep(
        agent_step_id=step_id,
        trace_id=_optional_str(data, "trace_id"),
        span_id=_optional_str(data, "span_id"),
        parent_span_id=_optional_str(data, "parent_span_id"),
        started_at=_optional_str(data, "started_at"),
        ended_at=_optional_str(data, "ended_at"),
        llm_calls=[_parse_llm_call(item, step_id) for item in _list(data.get("llm_calls"))],
        tool_calls=[_parse_tool_call(item) for item in _list(data.get("tool_calls"))],
        metadata=_dict(data.get("metadata")),
    )


def _parse_llm_call(data: Any, step_id: str) -> LLMCall:
    if not isinstance(data, dict):
        raise TraceParseError("llm_calls entries must be objects")
    return LLMCall(
        llm_call_id=_required_str(data, "llm_call_id", "llm call"),
        trace_id=_optional_str(data, "trace_id"),
        span_id=_optional_str(data, "span_id"),
        parent_span_id=_optional_str(data, "parent_span_id"),
        agent_step_id=_optional_str(data, "agent_step_id") or step_id,
        llm_request_id=_optional_str(data, "llm_request_id"),
        serving_request_id=_optional_str(data, "serving_request_id"),
        model=_optional_str(data, "model"),
        provider=_optional_str(data, "provider"),
        backend=_optional_str(data, "backend"),
        started_at=_optional_str(data, "started_at"),
        ended_at=_optional_str(data, "ended_at"),
        prompt_components=_parse_prompt(data.get("prompt")),
        input_tokens=_optional_int(data, "input_tokens"),
        output_tokens=_optional_int(data, "output_tokens"),
        prompt_token_ids=_optional_int_list(data, "prompt_token_ids"),
        output_token_ids=_optional_int_list(data, "output_token_ids"),
        tokenization_mode=_tokenization_mode(data.get("tokenization_mode")),
        ttft_ms=_optional_float(data, "ttft_ms"),
        tpot_ms=_optional_float(data, "tpot_ms"),
        metadata=_dict(data.get("metadata")),
    )


def _parse_prompt(prompt: Any) -> list[PromptComponent]:
    if prompt is None:
        return []
    if isinstance(prompt, dict):
        components: list[PromptComponent] = []
        seen: set[str] = set()
        for name in PROMPT_COMPONENT_ORDER:
            value = prompt.get(name)
            if value is not None:
                components.append(PromptComponent(name=name, text=str(value)))
                seen.add(name)
        for name, value in prompt.items():
            if name not in seen and value is not None:
                components.append(PromptComponent(name=str(name), text=str(value)))
        return components
    if isinstance(prompt, list):
        components = []
        for index, item in enumerate(prompt):
            if isinstance(item, dict):
                name = str(item.get("name", f"component_{index}"))
                text = str(item.get("text", ""))
            else:
                name = f"component_{index}"
                text = str(item)
            components.append(PromptComponent(name=name, text=text))
        return components
    return [PromptComponent(name="other_context", text=str(prompt))]


def _parse_tool_call(data: Any) -> ToolCall:
    if not isinstance(data, dict):
        raise TraceParseError("tool_calls entries must be objects")
    return ToolCall(
        tool_call_id=_required_str(data, "tool_call_id", "tool call"),
        name=_required_str(data, "name", "tool call"),
        trace_id=_optional_str(data, "trace_id"),
        span_id=_optional_str(data, "span_id"),
        parent_span_id=_optional_str(data, "parent_span_id"),
        started_at=_optional_str(data, "started_at"),
        ended_at=_optional_str(data, "ended_at"),
        latency_ms=_optional_float(data, "latency_ms"),
        input=data.get("input"),
        output=data.get("output"),
        metadata=_dict(data.get("metadata")),
    )


def _parse_serving_request(data: Any) -> ServingRequest:
    if not isinstance(data, dict):
        raise TraceParseError("serving_requests entries must be objects")
    return ServingRequest(
        serving_request_id=_required_str(data, "serving_request_id", "serving request"),
        trace_id=_optional_str(data, "trace_id"),
        span_id=_optional_str(data, "span_id"),
        parent_span_id=_optional_str(data, "parent_span_id"),
        llm_request_id=_optional_str(data, "llm_request_id"),
        model=_optional_str(data, "model"),
        backend=_optional_str(data, "backend"),
        started_at=_optional_str(data, "started_at"),
        ended_at=_optional_str(data, "ended_at"),
        queue_latency_ms=_optional_float(data, "queue_latency_ms"),
        prefill_latency_ms=_optional_float(data, "prefill_latency_ms"),
        prefill_path_latency_ms=_optional_float(data, "prefill_path_latency_ms"),
        decode_latency_ms=_optional_float(data, "decode_latency_ms"),
        ttft_ms=_optional_float(data, "ttft_ms"),
        tpot_ms=_optional_float(data, "tpot_ms"),
        input_tokens=_optional_int(data, "input_tokens"),
        output_tokens=_optional_int(data, "output_tokens"),
        prefix_cache_hit_tokens=_optional_int(data, "prefix_cache_hit_tokens"),
        prefix_cache_miss_tokens=_optional_int(data, "prefix_cache_miss_tokens"),
        kv_cache_used_tokens=_optional_int(data, "kv_cache_used_tokens"),
        kv_cache_capacity_tokens=_optional_int(data, "kv_cache_capacity_tokens"),
        kv_cache_evictions=_optional_int(data, "kv_cache_evictions"),
        tokenization_mode=_tokenization_mode(data.get("tokenization_mode")),
        metadata=_dict(data.get("metadata")),
    )


def _required_str(data: dict[str, Any], key: str, owner: str) -> str:
    value = data.get(key)
    if value is None or str(value) == "":
        raise TraceParseError(f"{owner} missing required field: {key}")
    return str(value)


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    return str(value)


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise TraceParseError(f"{key} must be numeric") from exc


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TraceParseError(f"{key} must be an integer") from exc


def _optional_int_list(data: dict[str, Any], key: str) -> list[int] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise TraceParseError(f"{key} must be a list of integers")
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise TraceParseError(f"{key} must be a list of integers") from exc


def _tokenization_mode(value: Any) -> TokenizationMode:
    if value is None:
        return "UNKNOWN"
    mode = str(value).upper()
    if mode == "EXACT":
        return "EXACT"
    if mode == "APPROXIMATE":
        return "APPROXIMATE"
    if mode == "UNKNOWN":
        return "UNKNOWN"
    raise TraceParseError("tokenization_mode must be EXACT, APPROXIMATE, or UNKNOWN")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TraceParseError("expected a list")
    return value


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TraceParseError("metadata must be an object")
    return value
