from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agentperf.schema.trace import (
    AgentRun,
    AgentStep,
    LLMCall,
    PromptComponent,
    ServingRequest,
    ToolCall,
)


@dataclass(frozen=True)
class SGLangMetricReliability:
    directly_observed: list[str]
    derived: list[str]
    unavailable: list[str]
    proxy: list[str]


@dataclass(frozen=True)
class SGLangServingCapabilities:
    request_tokens: bool
    client_ttft: bool
    server_queue: bool
    server_first_token: bool
    cache_per_request: bool
    cache_aggregate: bool
    generation_latency: bool


SGLANG_REAL_TELEMETRY_RELIABILITY = SGLangMetricReliability(
    directly_observed=[
        "OpenAI-compatible response id when present",
        "input_tokens/output_tokens from OpenAI-compatible usage when present",
        "client TTFT from streaming client timestamps when recorded",
        "client end-to-end latency from client timestamps when recorded",
        "aggregate Prometheus metrics when collected separately",
        "request trace spans when SGLang OpenTelemetry tracing is enabled",
    ],
    derived=[
        "decode_latency_ms = client_e2e_latency_ms - client_ttft_ms when both are recorded",
        "tpot_ms from decode latency and output token count when no direct TPOT exists",
    ],
    unavailable=[
        "per-request queue latency from ordinary OpenAI-compatible responses",
        "per-request prefill kernel latency from ordinary OpenAI-compatible responses",
        (
            "per-request prefix-cache hit/miss tokens unless usage.prompt_tokens_details "
            "is exported, for example with --enable-cache-report"
        ),
    ],
    proxy=[
        "client TTFT is client-observed first-token latency, not a server prefill metric",
        (
            "aggregate cache_hit_rate is workload/server-level cache evidence, "
            "not per-request cached tokens"
        ),
    ],
)


class SGLangTelemetryProvider:
    """Converts recorded SGLang OpenAI-compatible evidence into AgentPerf schema."""

    backend_name = "sglang"

    def build_run(self, data: dict[str, Any]) -> AgentRun:
        run_id = str(data.get("agent_run_id", "sglang-recorded-run"))
        model = str(data.get("model", "unknown"))
        records = _as_list(data.get("records"))

        llm_calls: list[LLMCall] = []
        serving_requests: list[ServingRequest] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError("SGLang records must be objects")
            response = _as_dict(record.get("response"))
            response_id = _optional_str(response.get("id"))
            usage = _as_dict(response.get("usage"))
            prompt_details = _as_dict(usage.get("prompt_tokens_details"))
            metrics = _as_dict(record.get("metrics")) or _as_dict(response.get("metrics"))
            server_metrics = _as_dict(record.get("server_metrics"))
            prompt_components = record.get("prompt_components") or {}

            client_request_id = str(
                record.get("client_request_id")
                or record.get("llm_request_id")
                or record.get("request_id")
                or response_id
                or f"sglang-request-{index}"
            )
            serving_request_id = str(
                record.get("serving_request_id")
                or response_id
                or record.get("request_id")
                or client_request_id
            )

            prompt_token_ids = _int_list(response.get("prompt_token_ids"))
            output_token_ids = _collect_output_token_ids(response)
            input_tokens = _optional_int(usage.get("prompt_tokens"))
            if input_tokens is None and prompt_token_ids is not None:
                input_tokens = len(prompt_token_ids)
            output_tokens = _optional_int(usage.get("completion_tokens"))
            if output_tokens is None and output_token_ids is not None:
                output_tokens = len(output_token_ids)

            ttft_ms = _metric_ms(
                metrics,
                ms_keys=["client_ttft_ms", "time_to_first_token_ms", "ttft_ms"],
                second_keys=["client_ttft", "time_to_first_token", "ttft"],
            )
            client_e2e_ms = _metric_ms(
                metrics,
                ms_keys=["client_e2e_latency_ms", "e2e_latency_ms"],
                second_keys=["client_e2e_latency", "e2e_latency"],
            )
            queue_ms = _metric_ms(
                metrics,
                ms_keys=["server_queue_time_ms", "queue_time_ms"],
                second_keys=["server_queue_time", "queue_time"],
            )
            decode_ms = _metric_ms(
                metrics,
                ms_keys=["generation_latency_ms", "decode_latency_ms"],
                second_keys=["generation_latency", "decode_latency"],
            )
            if decode_ms is None and client_e2e_ms is not None and ttft_ms is not None:
                decode_ms = max(client_e2e_ms - ttft_ms, 0.0)
            tpot_ms = _metric_ms(
                metrics,
                ms_keys=["time_per_output_token_ms", "tpot_ms"],
                second_keys=["time_per_output_token", "tpot"],
            )
            if tpot_ms is None and decode_ms is not None and output_tokens is not None:
                tpot_ms = decode_ms / max(output_tokens - 1, 1)

            cached_tokens = _optional_int(prompt_details.get("cached_tokens"))
            miss_tokens = None
            if input_tokens is not None and cached_tokens is not None:
                miss_tokens = max(input_tokens - cached_tokens, 0)

            capabilities = _capabilities(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                ttft_ms=ttft_ms,
                queue_ms=queue_ms,
                decode_ms=decode_ms,
                cached_tokens=cached_tokens,
                server_metrics=server_metrics,
            )
            record_metadata = _as_dict(record.get("metadata"))
            record_model = str(record.get("model") or model)
            llm_metadata = {
                **record_metadata,
                "prompt_components": prompt_components,
                "raw_response_id": response_id,
                "client_request_id": client_request_id,
                "telemetry_backend": self.backend_name,
                "metric_reliability": SGLANG_REAL_TELEMETRY_RELIABILITY.__dict__,
            }
            if client_e2e_ms is not None:
                llm_metadata["client_e2e_latency_ms"] = client_e2e_ms

            llm_call = LLMCall(
                llm_call_id=str(record.get("llm_call_id") or f"llm-{index}"),
                trace_id=_optional_str(record.get("trace_id")),
                span_id=_optional_str(record.get("span_id")),
                parent_span_id=_optional_str(record.get("parent_span_id")),
                agent_step_id=str(record.get("agent_step_id") or f"step-{index}"),
                llm_request_id=client_request_id,
                serving_request_id=serving_request_id,
                model=record_model,
                semantic_role=_semantic_role(record, record_metadata),
                provider="local",
                backend=self.backend_name,
                prompt_components=[],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                prompt_token_ids=prompt_token_ids,
                output_token_ids=output_token_ids,
                tokenization_mode="EXACT" if prompt_token_ids is not None else "APPROXIMATE",
                ttft_ms=ttft_ms,
                tpot_ms=tpot_ms,
                metadata=llm_metadata,
            )
            llm_calls.append(_with_prompt_components(llm_call, prompt_components))
            serving_requests.append(
                ServingRequest(
                    serving_request_id=serving_request_id,
                    trace_id=_optional_str(record.get("trace_id")),
                    span_id=_optional_str(record.get("serving_span_id")),
                    parent_span_id=_optional_str(record.get("serving_parent_span_id")),
                    llm_request_id=client_request_id,
                    model=record_model,
                    backend=self.backend_name,
                    queue_latency_ms=queue_ms,
                    prefill_latency_ms=None,
                    prefill_path_latency_ms=None,
                    decode_latency_ms=decode_ms,
                    ttft_ms=ttft_ms,
                    tpot_ms=tpot_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    prefix_cache_hit_tokens=cached_tokens,
                    prefix_cache_miss_tokens=miss_tokens,
                    tokenization_mode="EXACT" if prompt_token_ids is not None else "UNKNOWN",
                    metadata={
                        "raw_metrics": metrics,
                        "aggregate_server_metrics": server_metrics,
                        "capabilities": capabilities.__dict__,
                        "metric_reliability": {
                            "backend": self.backend_name,
                            "prefill_latency_ms": "unavailable",
                            "prefill_path_latency_ms": "unavailable",
                            "cache_per_request": (
                                "direct_from_usage.prompt_tokens_details.cached_tokens"
                                if cached_tokens is not None
                                else "unavailable"
                            ),
                            "cache_aggregate": (
                                "available_in_aggregate_server_metrics"
                                if server_metrics
                                else "unavailable"
                            ),
                            "measurement_semantics": {
                                "ttft_ms": "client_time_to_first_token",
                                "queue_latency_ms": (
                                    "server_queue_time"
                                    if queue_ms is not None
                                    else "unavailable"
                                ),
                                "decode_latency_ms": _decode_semantics(metrics, decode_ms),
                            },
                            "measurement_quality": {
                                "ttft_ms": (
                                    "direct_client" if ttft_ms is not None else "unavailable"
                                ),
                                "queue_latency_ms": (
                                    "direct_server_trace"
                                    if queue_ms is not None
                                    else "unavailable"
                                ),
                                "decode_latency_ms": _decode_quality(metrics, decode_ms),
                            },
                        },
                    },
                )
            )

        steps = _build_steps(llm_calls, data.get("tool_calls"))
        return AgentRun(
            agent_run_id=run_id,
            name=str(data.get("name", "SGLang recorded run")),
            steps=steps,
            serving_requests=serving_requests,
            synthetic=False,
            schema_version="0.1",
            metadata={
                "backend": self.backend_name,
                "model": model,
                "environment": data.get("environment", {}),
                "telemetry_reliability": SGLANG_REAL_TELEMETRY_RELIABILITY.__dict__,
            },
        )


def _with_prompt_components(call: LLMCall, prompt_components: Any) -> LLMCall:
    if not isinstance(prompt_components, dict):
        if isinstance(prompt_components, list):
            return replace(
                call,
                prompt_components=[
                    PromptComponent(
                        name=str(item.get("name", f"component_{index}")),
                        text=str(item.get("text", "")),
                        metadata=_as_dict(item.get("metadata")),
                    )
                    if isinstance(item, dict)
                    else PromptComponent(name=f"component_{index}", text=str(item))
                    for index, item in enumerate(prompt_components)
                ],
            )
        prompt_components = {"other_context": str(prompt_components or "")}
    return replace(
        call,
        prompt_components=[
            PromptComponent(name=str(name), text=str(text))
            for name, text in prompt_components.items()
            if text is not None
        ],
    )


def _build_steps(llm_calls: list[LLMCall], tool_call_data: Any) -> list[AgentStep]:
    llm_by_step: dict[str, list[LLMCall]] = {}
    for call in llm_calls:
        step_id = call.agent_step_id or "sglang-recorded-step"
        llm_by_step.setdefault(step_id, []).append(call)

    tools_by_step: dict[str, list[ToolCall]] = {}
    for item in _as_list(tool_call_data):
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("agent_step_id") or "sglang-recorded-step")
        tools_by_step.setdefault(step_id, []).append(
            ToolCall(
                tool_call_id=str(item.get("tool_call_id") or item.get("id") or "tool"),
                name=str(item.get("name") or "tool"),
                trace_id=_optional_str(item.get("trace_id")),
                span_id=_optional_str(item.get("span_id")),
                parent_span_id=_optional_str(item.get("parent_span_id")),
                started_at=_optional_str(item.get("started_at")),
                ended_at=_optional_str(item.get("ended_at")),
                latency_ms=_optional_float_value(item.get("latency_ms")),
                input=item.get("input"),
                output=item.get("output"),
                metadata=_as_dict(item.get("metadata")),
            )
        )

    ordered_step_ids = sorted(set(llm_by_step) | set(tools_by_step), key=_step_sort_key)
    return [
        AgentStep(
            agent_step_id=step_id,
            llm_calls=llm_by_step.get(step_id, []),
            tool_calls=tools_by_step.get(step_id, []),
        )
        for step_id in ordered_step_ids
    ]


def _capabilities(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    ttft_ms: float | None,
    queue_ms: float | None,
    decode_ms: float | None,
    cached_tokens: int | None,
    server_metrics: dict[str, Any],
) -> SGLangServingCapabilities:
    return SGLangServingCapabilities(
        request_tokens=input_tokens is not None or output_tokens is not None,
        client_ttft=ttft_ms is not None,
        server_queue=queue_ms is not None,
        server_first_token=False,
        cache_per_request=cached_tokens is not None,
        cache_aggregate=bool(server_metrics),
        generation_latency=decode_ms is not None,
    )


def _semantic_role(record: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    return (
        _optional_str(record.get("semantic_role"))
        or _optional_str(metadata.get("semantic_role"))
        or _optional_str(metadata.get("role"))
    )


def _collect_output_token_ids(response: dict[str, Any]) -> list[int] | None:
    token_ids: list[int] = []
    choices = response.get("choices")
    if not isinstance(choices, list):
        return None
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        choice_tokens = _int_list(choice.get("token_ids"))
        if choice_tokens:
            token_ids.extend(choice_tokens)
    return token_ids or None


def _decode_semantics(metrics: dict[str, Any], decode_ms: float | None) -> str:
    if decode_ms is None:
        return "unavailable"
    if any(key in metrics for key in ("generation_latency_ms", "generation_latency")):
        return "client_or_exported_generation_latency"
    return "derived_from_client_e2e_minus_ttft"


def _decode_quality(metrics: dict[str, Any], decode_ms: float | None) -> str:
    if decode_ms is None:
        return "unavailable"
    if any(key in metrics for key in ("generation_latency_ms", "generation_latency")):
        return "direct_recorded"
    return "derived"


def _first_present(data: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return float(value)
    return None


def _metric_ms(
    data: dict[str, Any],
    *,
    ms_keys: list[str],
    second_keys: list[str],
) -> float | None:
    milliseconds = _first_present(data, ms_keys)
    if milliseconds is not None:
        return milliseconds
    seconds = _first_present(data, second_keys)
    if seconds is not None:
        return seconds * 1000
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float_value(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _step_sort_key(step_id: str) -> tuple[str, int, str]:
    prefix, _, suffix = step_id.rpartition("-")
    if suffix.isdigit():
        return (prefix, int(suffix), step_id)
    return (step_id, 0, step_id)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_list(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None
    return [int(item) for item in value]
