from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar, cast
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
        self._span_stack: list[str] = []
        self._counter = 0
        self._tool_call_ids: set[str] = set()

    @contextmanager
    def as_current(self) -> Iterator[TraceRecorder]:
        token = _CURRENT_RECORDER.set(self)
        try:
            yield self
        finally:
            _CURRENT_RECORDER.reset(token)

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
        step = _StepBuilder(
            step_id=f"step-{self._counter}-{_safe_id(name)}",
            trace_id=self.trace_id,
            span_id=actual_span_id,
            parent_span_id=parent_span_id or (self._span_stack[-1] if self._span_stack else None),
            started_at=_now_iso(),
            metadata={"name": name, **(metadata or {})},
        )
        self._steps.append(step)
        self._span_stack.append(actual_span_id)
        return step

    def end_step(self, step_id: str) -> None:
        step = self._find_step(step_id)
        if step is None:
            return
        step.ended_at = _now_iso()
        if self._span_stack and self._span_stack[-1] == step.span_id:
            self._span_stack.pop()

    def record_llm_call(
        self,
        *,
        prompt_components: list[PromptComponent] | dict[str, str] | None = None,
        model: str | None = None,
        provider: str | None = None,
        backend: str | None = None,
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
        step = self._current_or_new_step("llm")
        components = _normalize_components(prompt_components)
        observed_input_tokens = input_tokens
        if observed_input_tokens is None and components:
            observed_input_tokens = sum(token_count(component.text) for component in components)
        call = LLMCall(
            llm_call_id=llm_call_id or f"llm-{len(self.to_agent_run().llm_calls) + 1}",
            trace_id=self.trace_id,
            span_id=f"span-llm-{uuid4().hex[:12]}",
            parent_span_id=step.span_id,
            agent_step_id=step.step_id,
            llm_request_id=llm_request_id,
            serving_request_id=serving_request_id,
            model=model,
            semantic_role=semantic_role,
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
        return call

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
        actual_id = tool_call_id or f"tool-{len(self.to_agent_run().tool_calls) + 1}"
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
        if self._steps and self._steps[-1].ended_at is None:
            return self._steps[-1]
        return self.start_step(name)

    def _find_step(self, step_id: str) -> _StepBuilder | None:
        return next((step for step in self._steps if step.step_id == step_id), None)

    def _find_tool_call(self, tool_call_id: str) -> ToolCall | None:
        for step in self._steps:
            for call in step.tool_calls:
                if call.tool_call_id == tool_call_id:
                    return call
        return None


@contextmanager
def trace_run(
    name: str,
    *,
    agent_run_id: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[TraceRecorder]:
    recorder = TraceRecorder(
        agent_run_id=agent_run_id,
        name=name,
        trace_id=trace_id,
        metadata=metadata,
    )
    with recorder.as_current():
        try:
            yield recorder
        finally:
            recorder.finish()


def current_recorder() -> TraceRecorder | None:
    return _CURRENT_RECORDER.get()


def trace_tool(name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            recorder = current_recorder()
            start = time.perf_counter()
            started_at = _now_iso()
            output: R | None = None
            try:
                output = func(*args, **kwargs)
                return output
            finally:
                if recorder is not None:
                    tool_name = name or cast(str, getattr(func, "__name__", "tool"))
                    recorder.record_tool_call(
                        name=tool_name,
                        input={"args": args, "kwargs": kwargs},
                        output=output,
                        started_at=started_at,
                        ended_at=_now_iso(),
                        latency_ms=(time.perf_counter() - start) * 1000,
                        metadata={"instrumentation": "agentperf.trace_tool"},
                    )

        return wrapper

    return decorator


def _normalize_components(
    components: list[PromptComponent] | dict[str, str] | None,
) -> list[PromptComponent]:
    if components is None:
        return []
    if isinstance(components, dict):
        return [PromptComponent(name=name, text=text) for name, text in components.items()]
    return components


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-") or "step"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
