from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, ParamSpec, TypeVar, cast
from uuid import uuid4

from agentperf.metrics.tokens import token_count
from agentperf.schema.trace import (
    AgentRun,
    AgentStep,
    LLMCall,
    PromptComponent,
    TokenizationMode,
    ToolCall,
)

_CURRENT_RECORDER: ContextVar[TraceRecorder | None] = ContextVar(
    "agentperf_current_recorder",
    default=None,
)
_CURRENT_SPAN_STACKS: ContextVar[dict[int, tuple[str, ...]] | None] = ContextVar(
    "agentperf_current_span_stacks",
    default=None,
)
P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class _StepBuilder:
    step_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    started_at: str
    ended_at: str | None = None
    llm_calls: list[LLMCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TraceRecorder:
    """Small public recorder for framework adapters and hand-written agents."""

    def __init__(
        self,
        *,
        agent_run_id: str | None = None,
        name: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.agent_run_id = agent_run_id or f"run-{uuid4().hex}"
        self.trace_id = trace_id or f"trace-{uuid4().hex}"
        self.name = name
        self.started_at = _now_iso()
        self.ended_at: str | None = None
        self.metadata = metadata or {}
        self._steps: list[_StepBuilder] = []
        self._steps_by_id: dict[str, _StepBuilder] = {}
        self._steps_by_span_id: dict[str, _StepBuilder] = {}
        self._counter = 0
        self._llm_call_count = 0
        self._tool_call_count = 0
        self._tool_call_ids: set[str] = set()
        self._tool_calls_by_id: dict[str, ToolCall] = {}
        self._completion_callback: Callable[[str], None] | None = None

    def set_completion_callback(self, callback: Callable[[str], None] | None) -> None:
        """Register a local callback for completed trace evidence events."""

        self._completion_callback = callback

    @contextmanager
    def as_current(self) -> Iterator[TraceRecorder]:
        recorder_token = _CURRENT_RECORDER.set(self)
        stacks = dict(_CURRENT_SPAN_STACKS.get() or {})
        stacks[id(self)] = ()
        stack_token = _CURRENT_SPAN_STACKS.set(stacks)
        try:
            yield self
        finally:
            _CURRENT_SPAN_STACKS.reset(stack_token)
            _CURRENT_RECORDER.reset(recorder_token)

    @contextmanager
    def step(
        self,
        name: str,
        *,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        step = self.start_step(
            name,
            span_id=span_id,
            parent_span_id=parent_span_id,
            metadata=metadata,
        )
        try:
            yield step.step_id
        finally:
            self.end_step(step.step_id)

    def start_step(
        self,
        name: str,
        *,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> _StepBuilder:
        self._counter += 1
        actual_span_id = span_id or f"span-{self._counter}"
        span_stack = self._span_stack()
        step = _StepBuilder(
            step_id=f"step-{self._counter}-{_safe_id(name)}",
            trace_id=self.trace_id,
            span_id=actual_span_id,
            parent_span_id=parent_span_id or (span_stack[-1] if span_stack else None),
            started_at=_now_iso(),
            metadata={"name": name, **(metadata or {})},
        )
        self._steps.append(step)
        self._steps_by_id[step.step_id] = step
        self._steps_by_span_id[actual_span_id] = step
        self._set_span_stack((*span_stack, actual_span_id))
        return step

    def end_step(self, step_id: str) -> None:
        step = self._find_step(step_id)
        if step is None:
            return
        was_open = step.ended_at is None
        step.ended_at = _now_iso()
        span_stack = self._span_stack()
        if span_stack and span_stack[-1] == step.span_id:
            self._set_span_stack(span_stack[:-1])
        if was_open:
            self._notify_completed("step")

    def record_llm_call(
        self,
        *,
        prompt_components: list[PromptComponent] | Mapping[str, object] | None = None,
        model: str | None = None,
        provider: str | None = None,
        backend: str | None = None,
        role: str | None = None,
        semantic_role: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        llm_call_id: str | None = None,
        llm_request_id: str | None = None,
        serving_request_id: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        latency_ms: float | None = None,
        tokenization_mode: TokenizationMode = "APPROXIMATE",
        metadata: dict[str, Any] | None = None,
    ) -> LLMCall:
        resolved_role = _resolve_role(role=role, semantic_role=semantic_role)
        step = self._current_or_new_step("llm")
        components = _normalize_components(prompt_components)
        observed_input_tokens = input_tokens
        if observed_input_tokens is None and components:
            observed_input_tokens = sum(token_count(component.text) for component in components)
        self._llm_call_count += 1
        call = LLMCall(
            llm_call_id=llm_call_id or f"llm-{self._llm_call_count}",
            trace_id=self.trace_id,
            span_id=f"span-llm-{uuid4().hex[:12]}",
            parent_span_id=step.span_id,
            agent_step_id=step.step_id,
            llm_request_id=llm_request_id,
            serving_request_id=serving_request_id,
            model=model,
            semantic_role=resolved_role,
            provider=provider,
            backend=backend,
            started_at=started_at,
            ended_at=ended_at,
            prompt_components=components,
            input_tokens=observed_input_tokens,
            output_tokens=output_tokens,
            tokenization_mode=tokenization_mode,
            metadata={"latency_ms": latency_ms, **(metadata or {})},
        )
        step.llm_calls.append(call)
        self._notify_completed("llm_call")
        return call

    def trace_llm(
        self,
        *,
        prompt_components: list[PromptComponent] | Mapping[str, object] | None = None,
        components: list[PromptComponent] | Mapping[str, object] | None = None,
        model: str | None = None,
        provider: str | None = None,
        backend: str | None = None,
        role: str | None = None,
        semantic_role: str | None = None,
        llm_call_id: str | None = None,
        tokenization_mode: TokenizationMode = "APPROXIMATE",
        metadata: dict[str, Any] | None = None,
    ) -> LLMCallTrace:
        """Create a context manager that records one LLM call.

        The call is appended when the context exits so timing, response usage,
        request IDs, and failures can be captured together. Unknown provider
        usage or request IDs should be left unset rather than fabricated.
        """

        return LLMCallTrace(
            self,
            prompt_components=prompt_components if prompt_components is not None else components,
            model=model,
            provider=provider,
            backend=backend,
            role=role,
            semantic_role=semantic_role,
            llm_call_id=llm_call_id,
            tokenization_mode=tokenization_mode,
            metadata=metadata,
        )

    def trace_tool(
        self,
        *,
        name: str,
        tool_call_id: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolCallTrace:
        """Create a context manager that records one tool call."""

        return ToolCallTrace(
            self,
            name=name,
            tool_call_id=tool_call_id,
            input=input,
            metadata=metadata,
        )

    def record_tool_call(
        self,
        *,
        name: str,
        tool_call_id: str | None = None,
        input: Any | None = None,
        output: Any | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        latency_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolCall:
        self._tool_call_count += 1
        actual_id = tool_call_id or f"tool-{self._tool_call_count}"
        if actual_id in self._tool_call_ids:
            existing = self._find_tool_call(actual_id)
            if existing is not None:
                return existing
        step = self._current_or_new_step("tool")
        call = ToolCall(
            tool_call_id=actual_id,
            name=name,
            trace_id=self.trace_id,
            span_id=f"span-tool-{uuid4().hex[:12]}",
            parent_span_id=step.span_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            input=input,
            output=output,
            metadata=metadata or {},
        )
        step.tool_calls.append(call)
        self._tool_call_ids.add(actual_id)
        self._tool_calls_by_id[actual_id] = call
        self._notify_completed("tool_call")
        return call

    def finish(self) -> AgentRun:
        self.ended_at = self.ended_at or _now_iso()
        for step in self._steps:
            step.ended_at = step.ended_at or self.ended_at
        return self.to_agent_run()

    def to_agent_run(self) -> AgentRun:
        return AgentRun(
            agent_run_id=self.agent_run_id,
            trace_id=self.trace_id,
            name=self.name,
            started_at=self.started_at,
            ended_at=self.ended_at,
            steps=[
                AgentStep(
                    agent_step_id=step.step_id,
                    trace_id=step.trace_id,
                    span_id=step.span_id,
                    parent_span_id=step.parent_span_id,
                    started_at=step.started_at,
                    ended_at=step.ended_at,
                    llm_calls=list(step.llm_calls),
                    tool_calls=list(step.tool_calls),
                    metadata=dict(step.metadata),
                )
                for step in self._steps
            ],
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "agentperf.trace.v1",
            "agent_run": asdict(self.finish()),
        }

    def write_json(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def _current_or_new_step(self, name: str) -> _StepBuilder:
        span_stack = self._span_stack()
        if span_stack:
            step = self._steps_by_span_id.get(span_stack[-1])
            if step is not None and step.ended_at is None:
                return step
        if self._steps and self._steps[-1].ended_at is None:
            return self._steps[-1]
        return self.start_step(name)

    def _find_step(self, step_id: str) -> _StepBuilder | None:
        return self._steps_by_id.get(step_id)

    def _find_tool_call(self, tool_call_id: str) -> ToolCall | None:
        return self._tool_calls_by_id.get(tool_call_id)

    def _span_stack(self) -> tuple[str, ...]:
        return (_CURRENT_SPAN_STACKS.get() or {}).get(id(self), ())

    def _set_span_stack(self, stack: tuple[str, ...]) -> None:
        stacks = dict(_CURRENT_SPAN_STACKS.get() or {})
        stacks[id(self)] = stack
        _CURRENT_SPAN_STACKS.set(stacks)

    def _notify_completed(self, event: str) -> None:
        if self._completion_callback is not None:
            self._completion_callback(event)


@contextmanager
def trace_run(
    name: str | None = None,
    *,
    task_id: str | None = None,
    execution_id: str | None = None,
    agent_run_id: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[TraceRecorder]:
    active = current_recorder()
    run_name = name or task_id or "agent-run"
    if active is not None and agent_run_id is None and trace_id is None:
        step_metadata = {
            "instrumentation": "agentperf.trace_run",
            **({"task_id": task_id} if task_id is not None else {}),
            **({"execution_id": execution_id} if execution_id is not None else {}),
            **(metadata or {}),
        }
        with active.step(run_name, metadata=step_metadata):
            yield active
        return

    recorder = TraceRecorder(
        agent_run_id=agent_run_id,
        name=run_name,
        trace_id=trace_id,
        metadata={
            **({"task_id": task_id} if task_id is not None else {}),
            **({"execution_id": execution_id} if execution_id is not None else {}),
            **(metadata or {}),
        },
    )
    with recorder.as_current():
        try:
            yield recorder
        finally:
            recorder.finish()


def current_recorder() -> TraceRecorder | None:
    return _CURRENT_RECORDER.get()


class LLMCallTrace:
    """Context manager for recording one framework-free LLM call."""

    def __init__(
        self,
        recorder: TraceRecorder,
        *,
        prompt_components: list[PromptComponent] | Mapping[str, object] | None = None,
        model: str | None = None,
        provider: str | None = None,
        backend: str | None = None,
        role: str | None = None,
        semantic_role: str | None = None,
        llm_call_id: str | None = None,
        tokenization_mode: TokenizationMode = "APPROXIMATE",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._recorder = recorder
        self._prompt_components = prompt_components
        self._model = model
        self._provider = provider
        self._backend = backend
        self._semantic_role = _resolve_role(role=role, semantic_role=semantic_role)
        self._llm_call_id = llm_call_id
        self._tokenization_mode = tokenization_mode
        self._metadata = metadata or {}
        self._started_at: str | None = None
        self._start_perf: float | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._llm_request_id: str | None = None
        self._serving_request_id: str | None = None
        self._ttft_ms: float | None = None
        self._tpot_ms: float | None = None
        self.call: LLMCall | None = None

    def __enter__(self) -> LLMCallTrace:
        self._started_at = _now_iso()
        self._start_perf = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        ended_at = _now_iso()
        latency_ms = (
            (time.perf_counter() - self._start_perf) * 1000
            if self._start_perf is not None
            else None
        )
        metadata = {
            "instrumentation": "agentperf.trace_llm",
            "status": "FAILED" if exc is not None else "COMPLETE",
            **self._metadata,
        }
        if exc is not None:
            metadata["error"] = f"{type(exc).__name__}: {exc}"
        if self._ttft_ms is not None:
            metadata["client_ttft_ms"] = self._ttft_ms
        if self._tpot_ms is not None:
            metadata["client_tpot_ms"] = self._tpot_ms
        self.call = self._recorder.record_llm_call(
            prompt_components=self._prompt_components,
            model=self._model,
            provider=self._provider,
            backend=self._backend,
            semantic_role=self._semantic_role,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            llm_call_id=self._llm_call_id,
            llm_request_id=self._llm_request_id,
            serving_request_id=self._serving_request_id,
            started_at=self._started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            tokenization_mode=self._tokenization_mode,
            metadata=metadata,
        )
        return False

    def record_response(
        self,
        *,
        output: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        request_id: str | None = None,
        llm_request_id: str | None = None,
        serving_request_id: str | None = None,
        ttft_ms: float | None = None,
        tpot_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Attach provider response evidence to the current LLM call."""

        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._llm_request_id = llm_request_id or request_id
        self._serving_request_id = serving_request_id
        self._ttft_ms = ttft_ms
        self._tpot_ms = tpot_ms
        if output is not None:
            self._metadata["output_preview_chars"] = min(len(output), 200)
        if metadata:
            self._metadata.update(metadata)


class ToolCallTrace:
    """Context manager for recording one framework-free tool call."""

    def __init__(
        self,
        recorder: TraceRecorder,
        *,
        name: str,
        tool_call_id: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._recorder = recorder
        self._name = name
        self._tool_call_id = tool_call_id
        self._input = input
        self._metadata = metadata or {}
        self._started_at: str | None = None
        self._start_perf: float | None = None
        self.output: Any | None = None
        self.call: ToolCall | None = None

    def __enter__(self) -> ToolCallTrace:
        self._started_at = _now_iso()
        self._start_perf = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        metadata = {
            "instrumentation": "agentperf.trace_tool",
            "status": "FAILED" if exc is not None else "COMPLETE",
            **self._metadata,
        }
        if exc is not None:
            metadata["error"] = f"{type(exc).__name__}: {exc}"
        self.call = self._recorder.record_tool_call(
            name=self._name,
            tool_call_id=self._tool_call_id,
            input=self._input,
            output=self.output,
            started_at=self._started_at,
            ended_at=_now_iso(),
            latency_ms=(
                (time.perf_counter() - self._start_perf) * 1000
                if self._start_perf is not None
                else None
            ),
            metadata=metadata,
        )
        return False

    def record_output(self, output: Any) -> None:
        """Attach a redaction-friendly tool result value to the recorded call."""

        self.output = output


class _ToolDecoratorContext:
    def __init__(
        self,
        name: str | None = None,
        *,
        tool_call_id: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._tool_call_id = tool_call_id
        self._input = input
        self._metadata = metadata or {}
        self._context: ToolCallTrace | None = None

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            recorder = current_recorder()
            if recorder is None:
                return func(*args, **kwargs)
            tool_name = self._name or cast(str, getattr(func, "__name__", "tool"))
            with recorder.trace_tool(
                name=tool_name,
                input={"args": args, "kwargs": kwargs},
                metadata={**self._metadata, "decorator": True},
            ) as call:
                output = func(*args, **kwargs)
                call.record_output(output)
                return output

        return wrapper

    def __enter__(self) -> ToolCallTrace:
        recorder = _require_current_recorder("trace_tool")
        self._context = recorder.trace_tool(
            name=self._name or "tool",
            tool_call_id=self._tool_call_id,
            input=self._input,
            metadata=self._metadata,
        )
        return self._context.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if self._context is None:
            return False
        return self._context.__exit__(exc_type, exc, traceback)


def trace_llm(
    *,
    prompt_components: list[PromptComponent] | Mapping[str, object] | None = None,
    components: list[PromptComponent] | Mapping[str, object] | None = None,
    model: str | None = None,
    provider: str | None = None,
    backend: str | None = None,
    role: str | None = None,
    semantic_role: str | None = None,
    llm_call_id: str | None = None,
    tokenization_mode: TokenizationMode = "APPROXIMATE",
    metadata: dict[str, Any] | None = None,
) -> LLMCallTrace:
    """Record a framework-free LLM call in the current AgentPerf run/session."""

    return _require_current_recorder("trace_llm").trace_llm(
        prompt_components=prompt_components,
        components=components,
        model=model,
        provider=provider,
        backend=backend,
        role=role,
        semantic_role=semantic_role,
        llm_call_id=llm_call_id,
        tokenization_mode=tokenization_mode,
        metadata=metadata,
    )


def trace_tool(
    name: str | None = None,
    *,
    tool_call_id: str | None = None,
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> _ToolDecoratorContext:
    """Record a tool call as either a decorator or context manager."""

    return _ToolDecoratorContext(
        name,
        tool_call_id=tool_call_id,
        input=input,
        metadata=metadata,
    )


def _require_current_recorder(api_name: str) -> TraceRecorder:
    recorder = current_recorder()
    if recorder is None:
        raise RuntimeError(f"{api_name} requires an active trace_run or ExperimentSession")
    return recorder


def _resolve_role(*, role: str | None, semantic_role: str | None) -> str | None:
    if role is not None and semantic_role is not None and role != semantic_role:
        raise ValueError("trace_llm role and semantic_role must match when both are provided")
    return semantic_role or role


def _normalize_components(
    components: list[PromptComponent] | Mapping[str, object] | None,
) -> list[PromptComponent]:
    if components is None:
        return []
    if isinstance(components, Mapping):
        return [
            PromptComponent(name=str(name), text=_component_text(value))
            for name, value in components.items()
            if value is not None
        ]
    return components


def _component_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return "\n".join(str(item) for item in value)
    return str(value)


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-") or "step"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
