from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agentperf.schema.trace import AgentRun, AgentStep, LLMCall, ServingRequest


@dataclass(frozen=True)
class VLLMMetricReliability:
    directly_exposed: list[str]
    derived: list[str]
    unavailable: list[str]
    approximated: list[str]


VLLM_REAL_TELEMETRY_RELIABILITY = VLLMMetricReliability(
    directly_exposed=[
        "llm_request_id/request_id",
        "input_tokens",
        "output_tokens",
        "prompt_token_ids when return_token_ids=true",
        "prefix_cache_hit_tokens from usage.prompt_tokens_details.cached_tokens",
        "queue_latency_ms from per-request queue_time_ms",
        "ttft_ms from per-request time_to_first_token_ms",
        "decode_latency_ms from per-request generation_time_ms",
        "tpot_ms from per-request mean_itl_ms",
    ],
    derived=[
        "prefix_cache_miss_tokens = input_tokens - cached_tokens",
        "prefill_latency_ms = time_to_first_token_ms as closest request-level prefill proxy",
    ],
    unavailable=[
        "request-level KV-cache capacity",
        "request-level KV-cache evictions",
        "pure request-level prefill kernel time separate from first-token time",
    ],
    approximated=[
        (
            "prefill_latency_ms because vLLM per-request metrics do not isolate pure "
            "prefill kernel time"
        ),
        "decode_latency_ms when only mean_itl_ms is available",
    ],
)


class VLLMTelemetryProvider:
    """Converts recorded vLLM OpenAI-compatible responses into AgentPerf schema."""

    backend_name = "vllm"

    def build_run(self, data: dict[str, Any]) -> AgentRun:
        run_id = str(data.get("agent_run_id", "vllm-recorded-run"))
        model = str(data.get("model", "unknown"))
        records = _as_list(data.get("records"))

        llm_calls: list[LLMCall] = []
        serving_requests: list[ServingRequest] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError("vLLM records must be objects")
            prompt_components = record.get("prompt_components") or {}
            response = _as_dict(record.get("response"))
            response_id = _optional_str(response.get("id"))
            client_request_id = str(
                record.get("client_request_id")
                or record.get("llm_request_id")
                or record.get("request_id")
                or response_id
                or f"vllm-request-{index}"
            )
            serving_request_id = str(
                record.get("serving_request_id")
                or response_id
                or record.get("request_id")
                or client_request_id
            )
            usage = _as_dict(response.get("usage"))
            metrics = _as_dict(response.get("metrics"))
            prompt_details = _as_dict(usage.get("prompt_tokens_details"))

            prompt_token_ids = _int_list(response.get("prompt_token_ids"))
            output_token_ids = _collect_output_token_ids(response)
            input_tokens = _optional_int(usage.get("prompt_tokens"))
            if input_tokens is None and prompt_token_ids is not None:
                input_tokens = len(prompt_token_ids)
            output_tokens = _optional_int(usage.get("completion_tokens"))
            if output_tokens is None and output_token_ids is not None:
                output_tokens = len(output_token_ids)

            cached_tokens = _optional_int(prompt_details.get("cached_tokens"))
            miss_tokens = None
            if input_tokens is not None and cached_tokens is not None:
                miss_tokens = max(input_tokens - cached_tokens, 0)

            queue_ms = _metric_ms(metrics, ms_keys=["queue_time_ms"], second_keys=["queue_time"])
            ttft_ms = _metric_ms(
                metrics,
                ms_keys=["time_to_first_token_ms"],
                second_keys=["time_to_first_token", "ttft"],
            )
            decode_ms = _metric_ms(
                metrics,
                ms_keys=["generation_time_ms"],
                second_keys=["generation_time"],
            )
            tpot_ms = _metric_ms(
                metrics,
                ms_keys=["mean_itl_ms", "time_per_output_token_ms"],
                second_keys=["mean_itl", "time_per_output_token", "tpot"],
            )
            prefill_ms = ttft_ms
            if decode_ms is None and tpot_ms is not None and output_tokens is not None:
                decode_ms = tpot_ms * max(output_tokens - 1, 0)

            llm_calls.append(
                LLMCall(
                    llm_call_id=str(record.get("llm_call_id") or f"llm-{index}"),
                    trace_id=_optional_str(record.get("trace_id")),
                    span_id=_optional_str(record.get("span_id")),
                    parent_span_id=_optional_str(record.get("parent_span_id")),
                    agent_step_id=str(record.get("agent_step_id") or f"step-{index}"),
                    llm_request_id=client_request_id,
                    serving_request_id=serving_request_id,
                    model=model,
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
                    metadata={
                        "prompt_components": prompt_components,
                        "raw_response_id": response.get("id"),
                        "client_request_id": client_request_id,
                    },
                )
            )
            llm_calls[-1] = _with_prompt_components(llm_calls[-1], prompt_components)
            serving_requests.append(
                ServingRequest(
                    serving_request_id=serving_request_id,
                    trace_id=_optional_str(record.get("trace_id")),
                    span_id=_optional_str(record.get("serving_span_id")),
                    llm_request_id=client_request_id,
                    model=model,
                    backend=self.backend_name,
                    queue_latency_ms=queue_ms,
                    prefill_latency_ms=prefill_ms,
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
                        "metric_reliability": {
                            "prefill_latency_ms": "approximated_from_time_to_first_token_ms",
                            "decode_latency_ms": (
                                "direct_generation_time_ms"
                                if "generation_time_ms" in metrics
                                else "derived_from_tpot"
                            ),
                        },
                    },
                )
            )

        return AgentRun(
            agent_run_id=run_id,
            name=str(data.get("name", "vLLM recorded run")),
            steps=[
                AgentStep(
                    agent_step_id="vllm-recorded-step",
                    llm_calls=llm_calls,
                    tool_calls=[],
                )
            ],
            serving_requests=serving_requests,
            synthetic=False,
            schema_version="0.1",
            metadata={
                "backend": self.backend_name,
                "model": model,
                "environment": data.get("environment", {}),
                "telemetry_reliability": VLLM_REAL_TELEMETRY_RELIABILITY.__dict__,
            },
        )


def _with_prompt_components(call: LLMCall, prompt_components: Any) -> LLMCall:
    from agentperf.schema.trace import PromptComponent

    if not isinstance(prompt_components, dict):
        prompt_components = {"other_context": str(prompt_components or "")}
    return replace(
        call,
        prompt_components=[
            PromptComponent(name=str(name), text=str(text))
            for name, text in prompt_components.items()
            if text is not None
        ],
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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_list(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None
    return [int(item) for item in value]
