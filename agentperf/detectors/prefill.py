from __future__ import annotations

from dataclasses import dataclass

from agentperf.detectors.base import DetectorContext
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import percentile, prefill_fraction_of_ttft
from agentperf.schema.findings import Finding, FindingProvenance, Severity
from agentperf.schema.trace import ServingRequest


@dataclass(frozen=True)
class PrefillBottleneckConfig:
    min_affected_requests: int = 2
    min_prefill_fraction_of_ttft: float = 0.60
    min_p95_input_tokens: int = 100


class PrefillBottleneckDetector:
    def __init__(self, config: PrefillBottleneckConfig | None = None) -> None:
        self.config = config or PrefillBottleneckConfig()

    def detect(self, context: DetectorContext) -> list[Finding]:
        correlated_requests = list(context.correlation.llm_to_serving.values())
        requests = correlated_requests or context.run.serving_requests
        affected = [
            request
            for request in requests
            if (fraction := prefill_fraction_of_ttft(request)) is not None
            and fraction >= self.config.min_prefill_fraction_of_ttft
        ]
        input_lengths = [
            request.input_tokens for request in requests if request.input_tokens is not None
        ]
        p95_input = percentile([float(value) for value in input_lengths], 0.95)
        if len(affected) < self.config.min_affected_requests:
            return []
        if p95_input is None or p95_input < self.config.min_p95_input_tokens:
            return []

        ttfts = [request.ttft_ms for request in requests if request.ttft_ms is not None]
        prefill_fractions = [prefill_fraction_of_ttft(request) or 0 for request in affected]
        hit_ratio = prefix_cache_hit_ratio(affected)
        affected_ids = _affected_span_ids(context, affected)
        severity: Severity = "HIGH" if max(prefill_fractions) >= 0.75 else "MEDIUM"

        evidence = {
            "affected_requests": len(affected),
            "prefill_fraction_of_ttft_avg": round(
                sum(prefill_fractions) / len(prefill_fractions),
                4,
            ),
            "p95_input_tokens": int(round(p95_input)),
            "ttft_p95_ms": round(percentile([float(value) for value in ttfts], 0.95) or 0, 1),
        }
        if hit_ratio is not None:
            evidence["prefix_cache_hit_ratio"] = round(hit_ratio, 4)
        affected_request_ids = {request.serving_request_id for request in affected}

        return [
            Finding(
                id="PREFILL_BOTTLENECK",
                severity=severity,
                title="Prefill dominates TTFT for long prompts",
                summary=(
                    "Serving telemetry attributes most time-to-first-token latency to prefill, "
                    "and the affected requests have long input prompts."
                ),
                evidence=evidence,
                affected_spans=affected_ids,
                recommendation=(
                    "Evaluate prompt-structure, context-length, and prefix-cache changes before "
                    "tuning decode-oriented settings."
                ),
                confidence="HIGH",
                validation_plan=[
                    (
                        "Replay the workload and compare TTFT P50/P95, prefill latency, "
                        "input length, and task quality."
                    ),
                    (
                        "If prefix-cache telemetry is available, compare hit ratio before "
                        "and after the change."
                    ),
                ],
                provenance=FindingProvenance(
                    llm_call_ids=[
                        call_id
                        for call_id, request in context.correlation.llm_to_serving.items()
                        if request.serving_request_id in affected_request_ids
                    ],
                    serving_request_ids=sorted(affected_request_ids),
                    raw_metrics={
                        "prefill_latency_ms": [
                            request.prefill_latency_ms for request in affected
                        ],
                        "queue_latency_ms": [
                            request.queue_latency_ms for request in affected
                        ],
                        "decode_latency_ms": [
                            request.decode_latency_ms for request in affected
                        ],
                        "ttft_ms": [request.ttft_ms for request in affected],
                        "input_tokens": [request.input_tokens for request in affected],
                    },
                    derived_metrics=evidence,
                    notes=[
                        "Prefill dominance uses normalized serving timings when available.",
                    ],
                ),
            )
        ]


def _affected_span_ids(context: DetectorContext, affected: list[ServingRequest]) -> list[str]:
    request_ids = {request.serving_request_id for request in affected}
    call_ids = [
        call_id
        for call_id, request in context.correlation.llm_to_serving.items()
        if request.serving_request_id in request_ids
    ]
    return call_ids + sorted(request_ids)
