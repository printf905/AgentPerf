from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agentperf.metrics.attribution import ComponentTokenAttribution, ContextGrowthRow
from agentperf.metrics.latency import percentile
from agentperf.metrics.tokens import call_input_tokens, call_output_tokens
from agentperf.schema.findings import Finding
from agentperf.schema.trace import AgentRun

SourceLayer = Literal[
    "agent_trace",
    "provider_usage",
    "agentperf_component_attribution",
    "serving_backend",
    "client_streaming",
    "derived",
]


@dataclass(frozen=True)
class MetricProvenance:
    name: str
    value: Any
    unit: str
    source_layer: SourceLayer
    source_field: str
    aggregation: str
    semantic_meaning: str
    availability: str = "available"


def metric_provenance_rows(
    run: AgentRun,
    *,
    attribution: ComponentTokenAttribution | None,
    context_growth: list[ContextGrowthRow],
    findings: list[Finding],
) -> list[MetricProvenance]:
    rows = [
        MetricProvenance(
            name="agent_trace_input_tokens",
            value=sum(call_input_tokens(call) for call in run.llm_calls),
            unit="tokens",
            source_layer="agent_trace",
            source_field="LLMCall.input_tokens or prompt_components",
            aggregation="sum over LLM calls",
            semantic_meaning=(
                "Input tokens as represented in the normalized agent trace. "
                "When explicit provider usage is absent, AgentPerf estimates from "
                "prompt components."
            ),
        ),
        MetricProvenance(
            name="agent_trace_output_tokens",
            value=sum(call_output_tokens(call) for call in run.llm_calls),
            unit="tokens",
            source_layer="agent_trace",
            source_field="LLMCall.output_tokens",
            aggregation="sum over LLM calls",
            semantic_meaning="Output tokens recorded on normalized LLM calls.",
        ),
    ]
    if context_growth:
        rows.append(
            MetricProvenance(
                name="agent_trace_step_input_tokens",
                value=[row.input_tokens for row in context_growth],
                unit="tokens",
                source_layer="agent_trace",
                source_field="ContextGrowthRow.input_tokens",
                aggregation="per LLM call in execution order",
                semantic_meaning="Per-step prompt size from the normalized agent trace.",
            )
        )
    if attribution is not None:
        rows.append(
            MetricProvenance(
                name="component_processed_tokens",
                value=attribution.total_processed_tokens,
                unit="tokens",
                source_layer="agentperf_component_attribution",
                source_field="prompt_components grouped by component kind",
                aggregation="sum over processed prompt components",
                semantic_meaning=(
                    "Cumulative AgentPerf attribution of which context components "
                    "caused prompt processing."
                ),
                availability="approximate" if attribution.approximate else "structured",
            )
        )

    serving_inputs = [
        float(request.input_tokens)
        for request in run.serving_requests
        if request.input_tokens is not None
    ]
    if serving_inputs:
        rows.append(
            MetricProvenance(
                name="serving_request_input_p95_tokens",
                value=round(percentile(serving_inputs, 0.95) or 0, 1),
                unit="tokens",
                source_layer="serving_backend",
                source_field="ServingRequest.input_tokens",
                aggregation="P95 over serving requests using AgentPerf percentile interpolation",
                semantic_meaning=(
                    "Prompt/input token count reported by serving telemetry. This may "
                    "differ from agent-trace prompt-component estimates."
                ),
            )
        )

    serving_uncached = []
    for request in run.serving_requests:
        if request.prefix_cache_miss_tokens is not None:
            serving_uncached.append(float(request.prefix_cache_miss_tokens))
        elif request.input_tokens is not None:
            serving_uncached.append(float(request.input_tokens))
    if serving_uncached:
        rows.append(
            MetricProvenance(
                name="serving_uncached_prompt_p95_tokens",
                value=round(percentile(serving_uncached, 0.95) or 0, 1),
                unit="tokens",
                source_layer="serving_backend",
                source_field="ServingRequest.prefix_cache_miss_tokens fallback input_tokens",
                aggregation="P95 over serving requests using AgentPerf percentile interpolation",
                semantic_meaning=(
                    "Serving prompt tokens that were not reported as prefix-cache hits. "
                    "Missing cache telemetry is treated as unavailable elsewhere; this "
                    "fallback is used only by detectors that explicitly allow it."
                ),
            )
        )

    ttfts = [
        float(request.ttft_ms) for request in run.serving_requests if request.ttft_ms is not None
    ]
    if ttfts:
        rows.append(
            MetricProvenance(
                name="serving_ttft_p95_ms",
                value=round(percentile(ttfts, 0.95) or 0, 1),
                unit="ms",
                source_layer="serving_backend",
                source_field="ServingRequest.ttft_ms",
                aggregation="P95 over serving requests using AgentPerf percentile interpolation",
                semantic_meaning=(
                    "Time-to-first-token evidence as recorded by the backend/client "
                    "adapter. It is not automatically GPU kernel prefill latency."
                ),
            )
        )

    rows.extend(_finding_metric_rows(findings))
    return _dedupe(rows)


def _finding_metric_rows(findings: list[Finding]) -> list[MetricProvenance]:
    rows: list[MetricProvenance] = []
    for finding in findings:
        if finding.id == "CACHEABILITY_HEADROOM":
            avg = finding.evidence.get("average_input_tokens")
            if avg is not None:
                rows.append(
                    MetricProvenance(
                        name="cacheability_agent_trace_average_input_tokens",
                        value=avg,
                        unit="tokens",
                        source_layer="agent_trace",
                        source_field="correlated LLM prompt components",
                        aggregation="mean over correlated LLM calls in prefix group",
                        semantic_meaning=(
                            "Average agent-trace prompt size for the cacheability "
                            "prefix group."
                        ),
                    )
                )
    return rows


def _dedupe(rows: list[MetricProvenance]) -> list[MetricProvenance]:
    seen: set[str] = set()
    result: list[MetricProvenance] = []
    for row in rows:
        if row.name in seen:
            continue
        seen.add(row.name)
        result.append(row)
    return result
