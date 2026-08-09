from __future__ import annotations

from dataclasses import dataclass

from agentperf.metrics.latency import percentile
from agentperf.metrics.tokens import call_input_tokens, call_output_tokens
from agentperf.schema.trace import AgentRun, LLMCall


@dataclass(frozen=True)
class RoleProfile:
    role: str
    calls: int
    input_tokens: int
    output_tokens: int
    client_latency_p50_ms: float | None
    client_latency_p95_ms: float | None
    ttft_p50_ms: float | None
    ttft_p95_ms: float | None
    generation_latency_p50_ms: float | None
    generation_latency_p95_ms: float | None
    models: list[str]


def role_profiles(run: AgentRun) -> list[RoleProfile]:
    grouped: dict[str, list[LLMCall]] = {}
    for call in run.llm_calls:
        grouped.setdefault(
            _normalize_role(call.semantic_role or _metadata_role(call) or "unknown"),
            [],
        ).append(call)
    return [
        _profile(role, calls)
        for role, calls in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _profile(role: str, calls: list[LLMCall]) -> RoleProfile:
    client_latencies = [
        float(call.metadata["client_elapsed_ms"])
        for call in calls
        if isinstance(call.metadata.get("client_elapsed_ms"), int | float)
    ]
    ttfts = [float(call.ttft_ms) for call in calls if call.ttft_ms is not None]
    generation_latencies = [
        float(call.metadata["generation_latency_ms"])
        for call in calls
        if isinstance(call.metadata.get("generation_latency_ms"), int | float)
    ]
    return RoleProfile(
        role=role,
        calls=len(calls),
        input_tokens=sum(call_input_tokens(call) for call in calls),
        output_tokens=sum(call_output_tokens(call) for call in calls),
        client_latency_p50_ms=percentile(client_latencies, 0.50),
        client_latency_p95_ms=percentile(client_latencies, 0.95),
        ttft_p50_ms=percentile(ttfts, 0.50),
        ttft_p95_ms=percentile(ttfts, 0.95),
        generation_latency_p50_ms=percentile(generation_latencies, 0.50),
        generation_latency_p95_ms=percentile(generation_latencies, 0.95),
        models=sorted({call.model for call in calls if call.model}),
    )


def _metadata_role(call: LLMCall) -> str | None:
    role = call.metadata.get("semantic_role") or call.metadata.get("role")
    if role is None:
        return None
    return str(role)


def _normalize_role(role: str) -> str:
    if role == "evidence-review":
        return "evidence_reviewer"
    if role == "final":
        return "final_synthesizer"
    return role
