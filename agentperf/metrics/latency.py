from __future__ import annotations

from statistics import mean

from agentperf.schema.trace import AgentRun, ServingRequest


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def prefill_fraction_of_ttft(request: ServingRequest) -> float | None:
    if request.prefill_latency_ms is None:
        return None
    denominator = request.ttft_ms
    if denominator is None:
        denominator = (request.queue_latency_ms or 0) + request.prefill_latency_ms
    if denominator <= 0:
        return None
    return request.prefill_latency_ms / denominator


def total_tool_latency_ms(run: AgentRun) -> float:
    return sum(call.latency_ms or 0 for call in run.tool_calls)


def mean_prefill_fraction(requests: list[ServingRequest]) -> float | None:
    fractions = [
        fraction
        for request in requests
        if (fraction := prefill_fraction_of_ttft(request)) is not None
    ]
    if not fractions:
        return None
    return mean(fractions)
