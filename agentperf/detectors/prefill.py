from __future__ import annotations

from dataclasses import dataclass

from agentperf.detectors.base import DetectorContext
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import (
    percentile,
    prefill_fraction_of_ttft,
    prefill_or_path_label,
    prefill_or_path_latency_ms,
)
from agentperf.schema.findings import Finding, FindingProvenance, Severity
from agentperf.schema.trace import ServingRequest


@dataclass(frozen=True)
class PrefillBottleneckConfig:
    min_affected_requests: int = 2
    min_prefill_fraction_of_ttft: float = 0.60
    min_p95_input_tokens: int = 100
    min_material_ttft_p95_ms: float = 100.0
    min_material_uncached_input_p95_tokens: int = 1000


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
        ttft_p50 = percentile([float(value) for value in ttfts], 0.50)
        ttft_p95 = percentile([float(value) for value in ttfts], 0.95)
        uncached_inputs: list[int] = []
        for request in affected:
            uncached_input = _uncached_input_tokens(request)
            if uncached_input is not None:
                uncached_inputs.append(uncached_input)
        p95_uncached_input = percentile([float(value) for value in uncached_inputs], 0.95)
        prefill_fractions = [prefill_fraction_of_ttft(request) or 0 for request in affected]
        hit_ratio = prefix_cache_hit_ratio(affected)
        affected_ids = _affected_span_ids(context, affected)
        latency_semantics = prefill_or_path_label(affected)
        fraction_key = (
            "prefill_path_proxy_fraction_of_ttft_avg"
            if latency_semantics == "prefill_path_proxy"
            else "prefill_fraction_of_ttft_avg"
        )
        material = (
            ttft_p95 is not None
            and ttft_p95 >= self.config.min_material_ttft_p95_ms
            and p95_uncached_input is not None
            and p95_uncached_input >= self.config.min_material_uncached_input_p95_tokens
        )
        finding_id = (
            "MATERIAL_PREFILL_BOTTLENECK" if material else "PREFILL_PATH_DOMINANCE"
        )
        severity: Severity = _severity(material, max(prefill_fractions), ttft_p95)

        evidence = {
            "affected_requests": len(affected),
            fraction_key: round(
                sum(prefill_fractions) / len(prefill_fractions),
                4,
            ),
            "latency_semantics": latency_semantics,
            "p95_input_tokens": int(round(p95_input)),
            "p95_uncached_input_tokens": (
                int(round(p95_uncached_input)) if p95_uncached_input is not None else None
            ),
            "ttft_p50_ms": round(ttft_p50, 1) if ttft_p50 is not None else None,
            "ttft_p95_ms": round(ttft_p95, 1) if ttft_p95 is not None else None,
            "materiality_threshold_ttft_p95_ms": self.config.min_material_ttft_p95_ms,
            "materiality_threshold_uncached_input_p95_tokens": (
                self.config.min_material_uncached_input_p95_tokens
            ),
        }
        if hit_ratio is not None:
            evidence["prefix_cache_hit_ratio"] = round(hit_ratio, 4)
        affected_request_ids = {request.serving_request_id for request in affected}

        return [
            Finding(
                id=finding_id,
                severity=severity,
                title=_title(material),
                summary=_summary(material),
                evidence=evidence,
                affected_spans=affected_ids,
                recommendation=(
                    "Evaluate prompt-structure, context-length, and prefix-cache changes "
                    "before tuning decode-oriented settings."
                    if material
                    else (
                        "Treat this as attribution, not a proven bottleneck. Prioritize it "
                        "only if absolute TTFT or uncached input volume becomes material."
                    )
                ),
                confidence="HIGH" if material else "MEDIUM",
                validation_plan=[
                    (
                        "Replay the workload and compare TTFT P50/P95, prefill/prefill-path "
                        "latency, input length, and task quality."
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
                        "prefill_path_latency_ms": [
                            prefill_or_path_latency_ms(request) for request in affected
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
                        (
                            "Prefill-path dominance uses true prefill latency when available; "
                            "otherwise it uses an explicitly labeled proxy."
                        ),
                        (
                            "Material bottleneck severity requires relative dominance plus "
                            "absolute TTFT and uncached-token evidence."
                        ),
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


def _uncached_input_tokens(request: ServingRequest) -> int | None:
    if request.prefix_cache_miss_tokens is not None:
        return request.prefix_cache_miss_tokens
    return request.input_tokens


def _severity(material: bool, max_fraction: float, ttft_p95: float | None) -> Severity:
    if not material:
        return "LOW"
    if max_fraction >= 0.75 and ttft_p95 is not None and ttft_p95 >= 200:
        return "HIGH"
    return "MEDIUM"


def _title(material: bool) -> str:
    if material:
        return "Material prefill-path bottleneck"
    return "Prefill path dominates but is not yet material"


def _summary(material: bool) -> str:
    if material:
        return (
            "Serving telemetry attributes most time-to-first-token latency to the "
            "prefill path, and affected requests have high uncached input volume."
        )
    return (
        "Serving telemetry attributes most time-to-first-token latency to the prefill "
        "path, but absolute TTFT and uncached input volume do not yet justify labeling "
        "it as an operational bottleneck."
    )
