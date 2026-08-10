from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from agentperf.instrumentation import TraceRecorder
from agentperf.metrics.tokens import token_count
from agentperf.schema.trace import PromptComponent


class MiniSweModelLike(Protocol):
    def query(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]: ...

    def format_message(self, **kwargs: Any) -> dict[str, Any]: ...

    def format_observation_messages(
        self,
        message: dict[str, Any],
        outputs: list[dict[str, Any]],
        template_vars: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]: ...

    def serialize(self) -> dict[str, Any]: ...


class MiniSweEnvironmentLike(Protocol):
    def execute(
        self,
        action: dict[str, Any],
        cwd: str = "",
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]: ...

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]: ...

    def serialize(self) -> dict[str, Any]: ...


class AgentPerfMiniSweModelWrapper:
    """mini-SWE-agent model wrapper that records each agent query as an LLM call."""

    def __init__(
        self,
        model: MiniSweModelLike,
        recorder: TraceRecorder,
        *,
        model_name: str | None = None,
        provider: str = "mini-swe-agent",
        tool_output_lookup: Callable[[str], list[str]] | None = None,
        call_id_prefix: str = "mini-swe-llm",
    ) -> None:
        self.model = model
        self.recorder = recorder
        self.model_name = model_name or _model_name(model)
        self.provider = provider
        self.tool_output_lookup = tool_output_lookup
        self.call_id_prefix = call_id_prefix
        self.calls = 0

    def query(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        llm_call_id = f"{self.call_id_prefix}-{self.calls}"
        started_at = _now_iso()
        start = time.perf_counter()
        output = self.model.query(messages, **kwargs)
        latency_ms = (time.perf_counter() - start) * 1000
        ended_at = _now_iso()
        usage = _usage_from_output(output)
        request_id = _request_id_from_output(output)
        response_model = _response_model_from_output(output)

        self.recorder.record_llm_call(
            llm_call_id=llm_call_id,
            llm_request_id=request_id or llm_call_id,
            prompt_components=prompt_components_from_mini_swe_messages(
                messages,
                tool_output_lookup=self.tool_output_lookup,
            ),
            model=response_model or self.model_name,
            provider=self.provider,
            input_tokens=_usage_value(usage, "prompt_tokens", "input_tokens"),
            output_tokens=_usage_value(usage, "completion_tokens", "output_tokens"),
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            tokenization_mode="APPROXIMATE",
            metadata={
                "framework": "mini-swe-agent",
                "response_id": request_id,
                "message_role": str(output.get("role", "")),
                "actions": output.get("extra", {}).get("actions", []),
            },
        )
        return output

    def format_message(self, **kwargs: Any) -> dict[str, Any]:
        return self.model.format_message(**kwargs)

    def format_observation_messages(
        self,
        message: dict[str, Any],
        outputs: list[dict[str, Any]],
        template_vars: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self.model.format_observation_messages(message, outputs, template_vars)

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]:
        return self.model.get_template_vars(**kwargs)

    def serialize(self) -> dict[str, Any]:
        return self.model.serialize()


class AgentPerfMiniSweEnvironmentWrapper:
    """mini-SWE-agent environment wrapper that records shell actions as tool calls."""

    def __init__(
        self,
        environment: MiniSweEnvironmentLike,
        recorder: TraceRecorder,
        *,
        tool_name: str = "bash",
        tool_call_id_prefix: str = "mini-swe-tool",
    ) -> None:
        self.environment = environment
        self.recorder = recorder
        self.tool_name = tool_name
        self.tool_call_id_prefix = tool_call_id_prefix
        self.calls = 0
        self._output_to_tool_ids: dict[str, list[str]] = {}

    def execute(
        self,
        action: dict[str, Any],
        cwd: str = "",
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        tool_call_id = str(action.get("tool_call_id") or f"{self.tool_call_id_prefix}-{self.calls}")
        started_at = _now_iso()
        start = time.perf_counter()
        try:
            output = self.environment.execute(action, cwd, timeout=timeout)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self.recorder.record_tool_call(
                tool_call_id=tool_call_id,
                name=self.tool_name,
                input=action,
                output=None,
                started_at=started_at,
                ended_at=_now_iso(),
                latency_ms=latency_ms,
                metadata={
                    "framework": "mini-swe-agent",
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                },
            )
            raise
        latency_ms = (time.perf_counter() - start) * 1000
        self.recorder.record_tool_call(
            tool_call_id=tool_call_id,
            name=self.tool_name,
            input=action,
            output=output.get("output"),
            started_at=started_at,
            ended_at=_now_iso(),
            latency_ms=latency_ms,
            metadata={
                "framework": "mini-swe-agent",
                "returncode": output.get("returncode"),
                "exception_info": output.get("exception_info"),
            },
        )
        text = str(output.get("output", ""))
        if text:
            self._output_to_tool_ids.setdefault(text, []).append(tool_call_id)
        return output

    def tool_call_ids_for_observation(self, text: str) -> list[str]:
        matches: list[str] = []
        for output, tool_ids in self._output_to_tool_ids.items():
            if output and output in text:
                matches.extend(tool_ids)
        return matches

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]:
        return self.environment.get_template_vars(**kwargs)

    def serialize(self) -> dict[str, Any]:
        return self.environment.serialize()


def prompt_components_from_mini_swe_messages(
    messages: list[dict[str, Any]],
    *,
    tool_output_lookup: Callable[[str], list[str]] | None = None,
) -> list[PromptComponent]:
    components: list[PromptComponent] = []
    for index, message in enumerate(messages):
        role = str(message.get("role", ""))
        content = _message_text(message.get("content"))
        if not content:
            continue
        metadata: dict[str, Any] = {
            "framework": "mini-swe-agent",
            "message_index": index,
            "role": role,
        }
        kind = _component_name(role, content, index)
        if kind == "tool_result" and tool_output_lookup is not None:
            source_ids = tool_output_lookup(content)
            if source_ids:
                metadata["source_tool_call_ids"] = source_ids
        components.append(PromptComponent(name=kind, text=content, metadata=metadata))
    return components


def _component_name(role: str, content: str, index: int) -> str:
    if role == "system":
        return "system"
    if role == "user" and index <= 1:
        return "user"
    if role == "user" and _looks_like_observation(content):
        return "tool_result"
    if role == "assistant":
        return "history"
    return "history"


def _looks_like_observation(content: str) -> bool:
    return "<returncode>" in content and "<output>" in content


def _message_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _usage_from_output(output: dict[str, Any]) -> dict[str, Any]:
    response = output.get("extra", {}).get("response")
    if not isinstance(response, dict):
        return {}
    usage = response.get("usage")
    return usage if isinstance(usage, dict) else {}


def _request_id_from_output(output: dict[str, Any]) -> str | None:
    response = output.get("extra", {}).get("response")
    if not isinstance(response, dict):
        return None
    value = response.get("id") or response.get("request_id")
    return str(value) if value else None


def _response_model_from_output(output: dict[str, Any]) -> str | None:
    response = output.get("extra", {}).get("response")
    if not isinstance(response, dict):
        return None
    value = response.get("model")
    return str(value) if value else None


def _usage_value(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _model_name(model: object) -> str | None:
    config = getattr(model, "config", None)
    value = getattr(config, "model_name", None)
    if value is None:
        return None
    return str(value)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def approximate_message_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(token_count(_message_text(message.get("content"))) for message in messages)
